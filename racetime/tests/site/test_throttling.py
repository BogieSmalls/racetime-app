from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from types import SimpleNamespace
import threading
import unittest
import uuid
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver

from racetime.throttling import (
    ThrottleDecision,
    check_throttle_configuration,
    client_ip,
    evaluate_throttle,
    reset_emergency_throttles,
    throttle_response,
    throttle_view,
)


TEST_HMAC_KEY = "test-only-dedicated-throttle-key-0123456789abcdef"
TRUSTED_PROXY = "172.30.0.2/32"


class AtomicMemoryCache:
    def __init__(self):
        self.values = {}
        self.lock = threading.Lock()

    def add(self, key, value, timeout=None):
        with self.lock:
            if key in self.values:
                return False
            self.values[key] = value
            return True

    def incr(self, key, delta=1):
        with self.lock:
            if key not in self.values:
                raise ValueError("missing key")
            self.values[key] += delta
            return self.values[key]


class BrokenCache:
    def add(self, key, value, timeout=None):
        raise ConnectionError("redis unavailable with secret detail")

    def incr(self, key, delta=1):
        raise ConnectionError("redis unavailable with secret detail")


def make_request(
    *,
    remote="192.0.2.10",
    forwarded=None,
    user_id=None,
    session=True,
    path="/protected",
):
    meta = {"REMOTE_ADDR": remote}
    if forwarded is not None:
        meta["HTTP_X_FORWARDED_FOR"] = forwarded
    user = (
        SimpleNamespace(is_authenticated=True, pk=user_id)
        if user_id is not None
        else AnonymousUser()
    )
    request = SimpleNamespace(
        META=meta,
        user=user,
        method="POST",
        path=path,
        headers={},
    )
    if session:
        request.session = {"racetime_throttle_session": "session-marker"}
    return request


@override_settings(
    RT_THROTTLING_ENABLED=True,
    RT_THROTTLING_REQUIRE_REDIS=False,
    RACETIME_THROTTLE_HMAC_KEY=TEST_HMAC_KEY,
    RACETIME_TRUSTED_PROXY_CIDR=TRUSTED_PROXY,
)
class ThrottlePolicyTests(SimpleTestCase):
    def setUp(self):
        reset_emergency_throttles()

    def test_last_allowed_request_retry_after_and_window_reset(self):
        backend = AtomicMemoryCache()
        request = make_request()
        decisions = [
            evaluate_throttle(
                request,
                "discord_auth",
                bucket="discord_initiate",
                backend=backend,
                now=1000,
            )
            for _ in range(11)
        ]
        self.assertTrue(all(decision.allowed for decision in decisions[:10]))
        self.assertTrue(decisions[10].rate_limited)
        self.assertGreaterEqual(decisions[10].retry_after, 1)
        self.assertLessEqual(decisions[10].retry_after, 600)
        reset = evaluate_throttle(
            request,
            "discord_auth",
            bucket="discord_initiate",
            backend=backend,
            now=1200,
        )
        self.assertTrue(reset.allowed)

    def test_atomic_concurrency_honors_user_limit(self):
        backend = AtomicMemoryCache()
        request = make_request(user_id=8675309)

        def attempt(_):
            return evaluate_throttle(
                request,
                "race_create",
                bucket="create_race",
                backend=backend,
                now=1800,
            ).allowed

        with ThreadPoolExecutor(max_workers=16) as executor:
            allowed = list(executor.map(attempt, range(30)))
        self.assertEqual(sum(allowed), 5)

    def test_user_and_ip_buckets_are_isolated(self):
        backend = AtomicMemoryCache()
        first = make_request(remote="192.0.2.1", user_id=1)
        second_user = make_request(remote="192.0.2.1", user_id=2)
        second_ip = make_request(remote="192.0.2.2", user_id=1)
        independent = make_request(remote="192.0.2.2", user_id=3)
        for _ in range(5):
            self.assertTrue(
                evaluate_throttle(
                    first,
                    "race_create",
                    bucket="create_race",
                    backend=backend,
                    now=1800,
                ).allowed
            )
        self.assertTrue(
            evaluate_throttle(
                second_user,
                "race_create",
                bucket="create_race",
                backend=backend,
                now=1800,
            ).allowed
        )
        self.assertFalse(
            evaluate_throttle(
                second_ip,
                "race_create",
                bucket="create_race",
                backend=backend,
                now=1800,
            ).allowed
        )
        self.assertTrue(
            evaluate_throttle(
                independent,
                "race_create",
                bucket="create_race",
                backend=backend,
                now=1800,
            ).allowed
        )

    def test_cache_keys_never_contain_raw_user_ip_or_session(self):
        backend = AtomicMemoryCache()
        request = make_request(remote="198.51.100.77", user_id=987654321)
        request.session["racetime_throttle_session"] = "raw-session-secret"
        evaluate_throttle(
            request,
            "profile_mutation",
            bucket="edit_account",
            backend=backend,
            now=1800,
        )
        keys = " ".join(backend.values)
        for raw_value in (
            "198.51.100.77",
            "987654321",
            "raw-session-secret",
            TEST_HMAC_KEY,
        ):
            self.assertNotIn(raw_value, keys)

    def test_missing_user_and_session_are_bounded_without_crashing(self):
        backend = AtomicMemoryCache()
        request = make_request(session=False)
        decision = evaluate_throttle(
            request,
            "lookup",
            bucket="search",
            backend=backend,
            now=1800,
        )
        self.assertTrue(decision.allowed)

    @mock.patch("racetime.throttling.logger.error")
    def test_redis_loss_fails_closed_except_authoritative_race_actions(
        self, log_error
    ):
        request = make_request(user_id=42)
        for policy_name in (
            "discord_auth",
            "oauth_decision",
            "race_create",
            "profile_mutation",
            "admin_mutation",
            "chat_mutation",
            "lookup",
        ):
            with self.subTest(policy=policy_name):
                closed = evaluate_throttle(
                    request,
                    policy_name,
                    bucket="protected",
                    backend=BrokenCache(),
                    now=1800,
                )
                self.assertTrue(closed.unavailable)
                self.assertFalse(closed.allowed)

        degraded = evaluate_throttle(
            request,
            "in_race_transition",
            bucket="done",
            backend=BrokenCache(),
            now=1800,
        )
        self.assertTrue(degraded.allowed)
        self.assertTrue(degraded.degraded)
        log_error.assert_called()
        self.assertNotIn("secret detail", str(log_error.call_args_list))
        self.assertNotIn("192.0.2.10", str(log_error.call_args_list))
        self.assertNotIn("42", str(log_error.call_args_list))

    @mock.patch("racetime.throttling.logger.error")
    def test_generic_error_responses_never_echo_keys(self, _log_error):
        decision = evaluate_throttle(
            make_request(user_id=42),
            "profile_mutation",
            bucket="edit_account",
            backend=BrokenCache(),
            now=1800,
        )
        response = throttle_response(make_request(), decision)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(TEST_HMAC_KEY, response.content.decode("utf-8"))
        self.assertNotIn("secret detail", response.content.decode("utf-8"))

    @mock.patch("racetime.throttling.evaluate_throttle")
    def test_wrapper_fails_closed_without_invoking_protected_view(self, evaluate):
        evaluate.return_value = ThrottleDecision(
            allowed=False,
            unavailable=True,
            retry_after=5,
        )
        protected_view = mock.Mock(return_value=object())
        wrapped = throttle_view(
            "race_create",
            bucket="create_race",
            methods=("POST",),
        )(protected_view)
        response = wrapped(make_request())
        self.assertEqual(response.status_code, 503)
        protected_view.assert_not_called()

    @mock.patch("racetime.throttling.evaluate_throttle")
    def test_wrapper_preserves_authoritative_race_action_in_degraded_mode(
        self, evaluate
    ):
        evaluate.return_value = ThrottleDecision(allowed=True, degraded=True)
        sentinel = object()
        protected_view = mock.Mock(return_value=sentinel)
        wrapped = throttle_view(
            "in_race_transition",
            bucket="done",
            methods=("POST",),
        )(protected_view)
        request = make_request()
        response = wrapped(request)
        self.assertIs(response, sentinel)
        self.assertTrue(request.racetime_throttle_degraded)
        protected_view.assert_called_once_with(request)


@override_settings(RACETIME_TRUSTED_PROXY_CIDR=TRUSTED_PROXY)
class ClientIPTests(SimpleTestCase):
    def test_trusted_caddy_uses_exactly_one_normalized_forwarded_address(self):
        first = make_request(remote="172.30.0.2", forwarded="198.51.100.10")
        second = make_request(remote="172.30.0.2", forwarded="198.51.100.11")
        self.assertEqual(client_ip(first), "198.51.100.10")
        self.assertEqual(client_ip(second), "198.51.100.11")

    def test_direct_spoof_different_proxy_and_multi_value_are_ignored(self):
        direct = make_request(remote="203.0.113.8", forwarded="198.51.100.10")
        wrong_proxy = make_request(remote="172.30.0.3", forwarded="198.51.100.10")
        multi = make_request(
            remote="172.30.0.2",
            forwarded="198.51.100.10, 198.51.100.11",
        )
        self.assertEqual(client_ip(direct), "203.0.113.8")
        self.assertEqual(client_ip(wrong_proxy), "172.30.0.3")
        self.assertEqual(client_ip(multi), "172.30.0.2")

    def test_ipv4_and_ipv6_are_canonicalized(self):
        self.assertEqual(client_ip(make_request(remote="192.0.2.010")), "unavailable")
        self.assertEqual(
            client_ip(make_request(remote="2001:0db8:0:0:0:0:0:1")),
            "2001:db8::1",
        )
        self.assertEqual(
            client_ip(make_request(remote="::ffff:192.0.2.10")),
            "192.0.2.10",
        )


class ConfigurationTests(SimpleTestCase):
    @override_settings(
        RT_THROTTLING_ENABLED=True,
        RT_THROTTLING_REQUIRE_REDIS=False,
        RACETIME_THROTTLE_HMAC_KEY=None,
        RACETIME_TRUSTED_PROXY_CIDR=TRUSTED_PROXY,
    )
    def test_enabled_throttling_rejects_missing_dedicated_key(self):
        errors = check_throttle_configuration(None)
        self.assertTrue(errors)
        self.assertIn("dedicated", " ".join(str(error.msg) for error in errors))

    @override_settings(
        RT_THROTTLING_ENABLED=True,
        RT_THROTTLING_REQUIRE_REDIS=False,
        SECRET_KEY=TEST_HMAC_KEY,
        RACETIME_THROTTLE_HMAC_KEY=TEST_HMAC_KEY,
        RACETIME_TRUSTED_PROXY_CIDR=TRUSTED_PROXY,
    )
    def test_secret_key_reuse_is_rejected(self):
        self.assertTrue(check_throttle_configuration(None))

    @override_settings(
        RT_THROTTLING_ENABLED=True,
        RT_THROTTLING_REQUIRE_REDIS=False,
        RACETIME_THROTTLE_HMAC_KEY=TEST_HMAC_KEY,
        RACETIME_TRUSTED_PROXY_CIDR="172.30.0.0/24",
    )
    def test_proxy_must_be_the_rendered_caddy_host_only_cidr(self):
        errors = check_throttle_configuration(None)
        self.assertTrue(errors)
        self.assertIn("172.30.0.2/32", " ".join(str(error.msg) for error in errors))

    @override_settings(
        RT_THROTTLING_ENABLED=True,
        RT_THROTTLING_REQUIRE_REDIS=True,
        RACETIME_THROTTLE_HMAC_KEY=TEST_HMAC_KEY,
        RACETIME_TRUSTED_PROXY_CIDR=TRUSTED_PROXY,
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "must-fail-production-validation",
            }
        },
    )
    def test_redis_required_profile_rejects_locmem(self):
        errors = check_throttle_configuration(None)
        self.assertTrue(errors)
        self.assertIn("RedisCache", " ".join(str(error.msg) for error in errors))


def named_patterns(patterns=None):
    if patterns is None:
        patterns = get_resolver().url_patterns
    found = []
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            found.extend(named_patterns(pattern.url_patterns))
        elif isinstance(pattern, URLPattern) and pattern.name:
            found.append(pattern)
    return found


class RoutePolicyInventoryTests(SimpleTestCase):
    EXPECTED_POLICIES = {
        "discord_initiate": "discord_auth",
        "discord_callback": "discord_auth",
        "discord_create_account": "discord_auth",
        "edit_account": "profile_mutation",
        "delete_account": "profile_mutation",
        "twitch_auth": "profile_mutation",
        "create_team": "profile_mutation",
        "join_team": "profile_mutation",
        "leave_team": "profile_mutation",
        "twitch_disconnect": "profile_mutation",
        "oauth2_delete": "profile_mutation",
        "create_race": "race_create",
        "oauth2_create_race": "race_create",
        "rematch": "race_create",
        "search": "lookup",
        "autocomplete_user": "lookup",
        "oauth2_authorize": "oauth_decision",
        "oauth2_token": "oauth_decision",
        "oauth2_revoke": "oauth_decision",
        "star": "profile_mutation",
        "unstar": "profile_mutation",
        "add_comment": "profile_mutation",
        "change_comment": "profile_mutation",
        "message": "chat_mutation",
        "edit_team": "admin_mutation",
        "delete_team": "admin_mutation",
        "team_member_add": "admin_mutation",
        "team_member_remove": "admin_mutation",
        "team_owner_add": "admin_mutation",
        "team_owner_remove": "admin_mutation",
        "edit_category": "admin_mutation",
        "category_deactivate": "admin_mutation",
        "category_reactivate": "admin_mutation",
        "new_category_goal": "admin_mutation",
        "edit_category_goal": "admin_mutation",
        "new_category_bot": "admin_mutation",
        "deactivate_category_bot": "admin_mutation",
        "reactivate_category_bot": "admin_mutation",
        "category_owners_add": "admin_mutation",
        "category_owners_remove": "admin_mutation",
        "category_mods_add": "admin_mutation",
        "category_mods_remove": "admin_mutation",
        "category_teams": "admin_mutation",
        "category_emotes_add": "admin_mutation",
        "category_emotes_remove": "admin_mutation",
        "oauth2_edit_race": "admin_mutation",
        "oauth2_chat_pin": "admin_mutation",
        "oauth2_chat_unpin": "admin_mutation",
        "oauth2_chat_purge": "admin_mutation",
        "oauth2_chat_delete": "admin_mutation",
        "edit_race": "admin_mutation",
        "make_open": "admin_mutation",
        "make_invitational": "admin_mutation",
        "invite_to_race": "admin_mutation",
        "record_race": "admin_mutation",
        "unrecord_race": "admin_mutation",
        "chat_pin": "admin_mutation",
        "chat_unpin": "admin_mutation",
        "chat_delete": "admin_mutation",
        "chat_purge": "admin_mutation",
        "edit_race_result": "admin_mutation",
        "override_stream": "admin_mutation",
        "add_monitor": "admin_mutation",
        "remove_monitor": "admin_mutation",
    }
    IN_RACE_ROUTES = {
        "join",
        "leave",
        "request_invite",
        "cancel_invite",
        "accept_invite",
        "decline_invite",
        "set_team",
        "ready",
        "unready",
        "done",
        "undone",
        "split",
        "forfeit",
        "unforfeit",
        "begin_race",
        "cancel_race",
        "hold_race",
        "unhold_race",
        "accept_request",
        "force_unready",
        "remove",
        "disqualify",
        "undisqualify",
    }

    def test_sensitive_named_routes_have_explicit_policies(self):
        by_name = {}
        for pattern in named_patterns():
            by_name.setdefault(pattern.name, []).append(pattern.callback)
        for route_name, policy in self.EXPECTED_POLICIES.items():
            with self.subTest(route=route_name):
                self.assertIn(route_name, by_name)
                self.assertTrue(
                    all(
                        getattr(callback, "racetime_throttle_policy", None) == policy
                        for callback in by_name[route_name]
                    )
                )
        for route_name in self.IN_RACE_ROUTES:
            with self.subTest(route=route_name):
                self.assertIn(route_name, by_name)
                self.assertTrue(
                    all(
                        getattr(callback, "racetime_throttle_policy", None)
                        == "in_race_transition"
                        for callback in by_name[route_name]
                    )
                )


def _service_worker(arguments):
    policy, bucket, now, user_id = arguments
    request = make_request(user_id=user_id)
    return evaluate_throttle(
        request,
        policy,
        bucket=bucket,
        now=now,
    ).allowed


@unittest.skipUnless(
    getattr(settings, "RT_SERVICE_BACKED_CI", False),
    "requires the project.settings.ci service-backed profile",
)
class RedisProcessIntegrationTests(SimpleTestCase):
    def test_redis_counter_is_atomic_across_processes(self):
        bucket = "ci-process-" + uuid.uuid4().hex
        arguments = [("race_create", bucket, 1800, 4242)] * 12
        with multiprocessing.get_context("fork").Pool(processes=6) as pool:
            allowed = pool.map(_service_worker, arguments)
        self.assertEqual(sum(allowed), 5)
        cache.close()
