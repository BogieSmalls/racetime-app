"""Ordinary unittest helpers for the isolated browser integration stack."""

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import Page, sync_playwright


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
READY_SENTINEL = REPOSITORY_ROOT / "artifacts" / "integration" / ".ready"
EXPECTED_ORIGIN = "https://integration.racetime.test:8443"


@dataclass(frozen=True)
class IntegrationEndpoints:
    origin: str
    category: str = "z1rr"

    @classmethod
    def from_env(cls):
        origin = os.environ.get("RACETIME_INTEGRATION_ORIGIN", EXPECTED_ORIGIN)
        parsed = urlsplit(origin)
        if (
            origin != EXPECTED_ORIGIN
            or parsed.scheme != "https"
            or parsed.hostname != "integration.racetime.test"
            or parsed.port != 8443
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("E2E tests accept only the fixed integration origin.")
        return cls(origin=origin)

    @property
    def category_url(self):
        return f"{self.origin}/{self.category}"

    @property
    def websocket_origin(self):
        return "wss://integration.racetime.test:8443"

    def require_ready(self):
        if not READY_SENTINEL.is_file():
            raise unittest.SkipTest(
                "integration stack is not running; use scripts/integration-up.ps1"
            )
        try:
            payload = json.loads(READY_SENTINEL.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError("Integration readiness evidence is invalid.") from error
        if payload.get("origin") != self.origin or payload.get("project") != (
            "z1rr-racetime-integration"
        ):
            raise RuntimeError("Integration readiness evidence does not match the stack.")


@dataclass
class FixtureActor:
    subject: str
    display_name: str
    page: Page


@dataclass(frozen=True)
class FixtureRoom:
    endpoints: IntegrationEndpoints
    path: str
    slug: str
    creator: FixtureActor

    @property
    def url(self):
        return self.endpoints.origin + self.path

    def action(self, suffix):
        return f"{self.path}/{suffix.lstrip('/')}"


@contextmanager
def chromium_page(endpoints):
    endpoints.require_ready()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--host-resolver-rules=MAP integration.racetime.test 127.0.0.1",
            ],
        )
        context = browser.new_context(
            base_url=endpoints.origin,
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(15_000)
        try:
            yield page
        finally:
            browser.close()


def _set_fixture_subject(page, subject):
    if not isinstance(subject, str) or not subject.isascii() or not subject.isdecimal():
        raise ValueError("Fixture Discord subjects must be decimal strings.")
    page.context.add_cookies(
        [
            {
                "name": "fixture_discord_subject",
                "value": subject,
                "domain": "integration.racetime.test",
                "path": "/",
                "secure": True,
                "sameSite": "Lax",
            }
        ]
    )


def fixture_discord_account(page, *, subject, display_name):
    _set_fixture_subject(page, subject)
    page.goto("/account/discord", wait_until="networkidle")
    if page.locator('input[name="name"]').count():
        page.locator('input[name="name"]').fill(display_name)
        page.get_by_role("button", name="Create account").click()
        page.wait_for_load_state("networkidle")
    if "/account/discord" in page.url:
        raise AssertionError("Fixture Discord login did not complete.")
    return FixtureActor(subject=subject, display_name=display_name, page=page)


def _post(page, path, data=None):
    result = page.evaluate(
        """
        async ({path, data}) => {
          const csrf = document.cookie.split('; ')
            .find(value => value.startsWith('csrftoken='));
          if (!csrf) return {status: 0, error: 'missing-csrf'};
          const body = new URLSearchParams(data || {});
          const response = await fetch(path, {
            method: 'POST',
            credentials: 'same-origin',
            redirect: 'follow',
            headers: {
              'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
              'X-CSRFToken': decodeURIComponent(csrf.substring('csrftoken='.length)),
              'X-Requested-With': 'XMLHttpRequest'
            },
            body: body.toString()
          });
          return {status: response.status, ok: response.ok};
        }
        """,
        {"path": path, "data": data or {}},
    )
    if not result.get("ok"):
        raise AssertionError(
            f"Integration POST failed for {path}: status={result.get('status')}"
        )


def _race_data(actor, room):
    result = actor.page.evaluate(
        """async path => {
          const response = await fetch(path, {credentials: 'same-origin'});
          return {status: response.status, payload: response.ok ? await response.json() : null};
        }""",
        room.action("data"),
    )
    if result["status"] != 200 or not isinstance(result["payload"], dict):
        raise AssertionError(f"Race data unavailable: status={result['status']}")
    return result["payload"]


def _wait_for_race_state(actor, room, expected, timeout=45):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = _race_data(actor, room).get("status", {}).get("value")
        if last == expected:
            return
        time.sleep(0.25)
    raise AssertionError(f"Race state did not become {expected!r}; last={last!r}")


def create_race(page, actor, *, goal):
    endpoints = IntegrationEndpoints.from_env()
    page.goto(f"/{endpoints.category}/startrace", wait_until="networkidle")
    page.locator('select[name="goal"]').select_option(label=goal)
    ranked = page.locator('input[name="ranked"]')
    if ranked.count() and not ranked.is_checked():
        ranked.check()
    streaming = page.locator('input[name="streaming_required"]')
    if streaming.count() and streaming.is_checked():
        streaming.uncheck()
    page.get_by_role("button", name="Start race").click()
    page.wait_for_load_state("networkidle")
    parsed = urlsplit(page.url)
    pieces = [value for value in parsed.path.split("/") if value]
    if len(pieces) != 2 or pieces[0] != endpoints.category:
        raise AssertionError(f"Race creation returned an unexpected path: {parsed.path}")
    room = FixtureRoom(
        endpoints=endpoints,
        path=parsed.path,
        slug=pieces[1],
        creator=actor,
    )
    _post(page, room.action("join"))
    return room


def join_with_fixture_discord(page, room, *, subject, display_name):
    browser = page.context.browser
    if browser is None:
        raise RuntimeError("The Playwright browser is unavailable.")
    context = browser.new_context(
        base_url=room.endpoints.origin,
        ignore_https_errors=True,
    )
    entrant_page = context.new_page()
    entrant_page.set_default_timeout(15_000)
    actor = fixture_discord_account(
        entrant_page,
        subject=subject,
        display_name=display_name,
    )
    entrant_page.goto(room.url, wait_until="networkidle")
    _post(entrant_page, room.action("join"))
    return actor


def complete_two_entrant_race(page, room, first, second):
    for actor in (first, second):
        actor.page.goto(room.url, wait_until="domcontentloaded")
        _post(actor.page, room.action("ready"))

    data = _race_data(first, room)
    if data.get("entrants_count") != 2:
        raise AssertionError("The integration room does not contain two entrants.")

    _post(first.page, room.action("message"), {"message": "Integration lifecycle"})
    _post(first.page, room.action("monitor/begin"))
    _wait_for_race_state(first, room, "in_progress")
    time.sleep(5.25)
    _post(first.page, room.action("done"))
    _post(second.page, room.action("done"))
    _wait_for_race_state(first, room, "finished")
    _post(first.page, room.action("monitor/record"))


def assert_recorded_leaderboard(page, room, *, expected_names):
    data = _race_data(room.creator, room)
    if not data.get("recorded"):
        raise AssertionError("The completed integration race was not recorded.")
    page.goto(
        f"/{room.endpoints.category}/leaderboards",
        wait_until="networkidle",
    )
    body = page.locator("body").inner_text()
    for name in expected_names:
        if name not in body:
            raise AssertionError(f"Leaderboard does not contain {name!r}.")
