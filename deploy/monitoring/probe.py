#!/usr/bin/env python3
"""Secret-safe RaceTime health/capacity probe and rule evaluator."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


SCHEMA_VERSION = 1
PUBLIC_HOST = "racetime.z1rracing.com"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
CONTAINER_NAMES = ("web", "racebot", "db", "redis", "caddy")


def _utc(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(now: datetime | None = None) -> str:
    return _utc(now).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bare_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != PUBLIC_HOST
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("public_origin must be the canonical bare HTTPS origin")
    return f"https://{PUBLIC_HOST}"


def _validate_config(config: dict, environ: dict[str, str]) -> dict:
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported monitoring configuration schema")
    origin = _bare_origin(str(config.get("public_origin", "")))
    websocket = urlsplit(str(config.get("websocket_url", "")))
    if (
        websocket.scheme != "wss"
        or websocket.hostname != PUBLIC_HOST
        or websocket.username
        or websocket.password
        or websocket.fragment
    ):
        raise ValueError("websocket_url must use WSS on the canonical host")
    internal = urlsplit(str(config.get("internal_readiness_url", "")))
    if internal.scheme not in {"http", "https"} or internal.hostname not in LOOPBACK_HOSTS:
        raise ValueError("internal_readiness_url must be loopback-only")
    if str(config.get("tls_host", "")) != PUBLIC_HOST:
        raise ValueError("tls_host must be the canonical host")
    token_env = str(config.get("internal_token_env", ""))
    token = environ.get(token_env, "")
    if not token or token.lower() in {"changeme", "example", "placeholder"}:
        raise ValueError("internal readiness token is missing or placeholder")
    names = config.get("container_names")
    if not isinstance(names, list) or set(names) != set(CONTAINER_NAMES):
        raise ValueError("container_names must name web, racebot, db, redis, and caddy")
    timeout = config.get("timeout_seconds")
    if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 30:
        raise ValueError("timeout_seconds must be between 1 and 30")
    tls_port = config.get("tls_port")
    if not isinstance(tls_port, int) or not 1 <= tls_port <= 65535:
        raise ValueError("tls_port is invalid")
    admin_path = str(config.get("public_admin_path", ""))
    if not admin_path.startswith("/") or "?" in admin_path or "#" in admin_path:
        raise ValueError("public_admin_path must be an absolute path")
    for key in ("application_metrics_path", "backup_metrics_path", "oci_metrics_path"):
        if not str(config.get(key, "")).strip():
            raise ValueError(f"{key} is required")
    result = dict(config)
    result["public_origin"] = origin
    result["internal_token"] = token
    return result


class DefaultAdapters:
    """Concrete probes. Methods return metadata only, never response bodies."""

    def http_status(self, url, *, headers, timeout):
        request = Request(url, headers={"User-Agent": "z1rr-racetime-monitor/1", **headers})
        try:
            with urlopen(request, timeout=timeout) as response:
                return int(response.status)
        except HTTPError as exc:
            return int(exc.code)

    def websocket_ok(self, url, *, timeout):
        from websockets.sync.client import connect

        with connect(url, open_timeout=timeout, close_timeout=timeout) as websocket:
            websocket.close()
        return True

    def tls_days_remaining(self, host, port, *, timeout, now):
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as raw_socket:
            with context.wrap_socket(raw_socket, server_hostname=host) as tls_socket:
                not_after = tls_socket.getpeercert()["notAfter"]
        expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        return (expires - _utc(now)).total_seconds() / 86400

    def container_metrics(self, names):
        command = ["docker", "inspect", *names]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        records = json.loads(completed.stdout)
        by_name = {}
        for record in records:
            name = str(record.get("Name", "")).lstrip("/")
            state = record.get("State") or {}
            health = state.get("Health") or {}
            logical = next((item for item in names if name.endswith(f"-{item}-1")), name)
            by_name[logical] = {
                "running": bool(state.get("Running")),
                "healthy": health.get("Status", "healthy") == "healthy",
                "restart_count": int(record.get("RestartCount", 0)),
            }
        for name in names:
            by_name.setdefault(
                name,
                {"running": False, "healthy": False, "restart_count": 0},
            )
        return by_name

    def filesystem_metrics(self, path):
        usage = shutil.disk_usage(path)
        stat = os.statvfs(path)
        inode_total = stat.f_files
        inode_used = inode_total - stat.f_ffree
        memory_used = _memory_used_percent()
        cpu_count = max(1, os.cpu_count() or 1)
        load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
        return {
            "disk_used_percent": _percent(usage.used, usage.total),
            "inode_used_percent": _percent(inode_used, inode_total),
            "memory_used_percent": memory_used,
            "cpu_used_percent": min(100.0, 100.0 * load / cpu_count),
        }

    def read_json(self, path):
        target = Path(path)
        if target.is_symlink() or not target.is_file():
            raise ValueError("metrics source must be a regular non-symlink file")
        if target.stat().st_size > 1024 * 1024:
            raise ValueError("metrics source exceeds one MiB")
        with target.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("metrics source must contain an object")
        return value


def _percent(value: float, total: float) -> float:
    return 0.0 if total <= 0 else round(100.0 * value / total, 3)


def _memory_used_percent() -> float:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return 0.0
    values = {}
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        values[key] = float(raw.strip().split()[0])
    return _percent(values.get("MemTotal", 0), values.get("MemTotal", 0)) - _percent(
        values.get("MemAvailable", 0), values.get("MemTotal", 0)
    )


def _safe_check(callback, *, success):
    try:
        value = callback()
        return success(value)
    except Exception as exc:  # probe failures are data, not secret-bearing logs
        return {"ok": False, "error_code": type(exc).__name__.upper()}


def _safe_metrics(callback):
    try:
        value = callback()
        if not isinstance(value, dict):
            raise ValueError("metric adapter returned a non-object")
        return value
    except Exception as exc:
        return {"source_ok": False, "error_code": type(exc).__name__.upper()}


def collect_snapshot(config, *, adapters=None, environ=None, now=None):
    environ = dict(os.environ if environ is None else environ)
    current = _utc(now)
    validated = _validate_config(config, environ)
    adapters = adapters or DefaultAdapters()
    timeout = float(validated["timeout_seconds"])
    origin = validated["public_origin"]
    admin_url = urljoin(origin + "/", validated["public_admin_path"].lstrip("/"))
    token = validated.pop("internal_token")

    checks = {
        "https": _safe_check(
            lambda: adapters.http_status(origin + "/healthz", headers={}, timeout=timeout),
            success=lambda status: {"ok": status == 200, "status_code": status},
        ),
        "websocket": _safe_check(
            lambda: adapters.websocket_ok(validated["websocket_url"], timeout=timeout),
            success=lambda ok: {"ok": bool(ok)},
        ),
        "public_admin_denial": _safe_check(
            lambda: adapters.http_status(admin_url, headers={}, timeout=timeout),
            success=lambda status: {"ok": status == 404, "status_code": status},
        ),
        "internal_readiness": _safe_check(
            lambda: adapters.http_status(
                validated["internal_readiness_url"],
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            ),
            success=lambda status: {"ok": status == 200, "status_code": status},
        ),
        "tls": _safe_check(
            lambda: adapters.tls_days_remaining(
                validated["tls_host"],
                validated["tls_port"],
                timeout=timeout,
                now=current,
            ),
            success=lambda days: {"ok": days >= 21, "days_remaining": round(days, 3)},
        ),
    }
    metrics = {
        "containers": _safe_metrics(
            lambda: adapters.container_metrics(validated["container_names"])
        ),
        "system": _safe_metrics(
            lambda: adapters.filesystem_metrics(validated["filesystem_path"])
        ),
        "application": _safe_metrics(
            lambda: adapters.read_json(validated["application_metrics_path"])
        ),
        "backups": _safe_metrics(lambda: adapters.read_json(validated["backup_metrics_path"])),
        "oci": _safe_metrics(lambda: adapters.read_json(validated["oci_metrics_path"])),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": _timestamp(current),
        "checks": checks,
        "metrics": metrics,
    }


def empty_snapshot():
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": _timestamp(datetime(2000, 1, 1, tzinfo=timezone.utc)),
        "checks": {},
        "metrics": {"containers": {}, "system": {}, "application": {}, "backups": {}, "oci": {}},
    }


def default_rules():
    return {
        "service_consecutive_failures": 2,
        "container_restart_warning": 3,
        "cpu_used_percent": 80.0,
        "memory_used_percent": 70.0,
        "disk_used_percent": 80.0,
        "inode_used_percent": 80.0,
        "database_growth_bytes_24h": 1_073_741_824,
        "oauth_error_rate": 0.2,
        "oauth_minimum_requests": 10,
        "database_backup_age_hours": 7.0,
        "media_backup_age_hours": 26.0,
        "caddy_verified_generations": 3,
        "tls_days_remaining": 21.0,
        "a1_forecast_cutoff_hours": 2650.0,
        "a1_forecast_minimum_buffer_hours": 100.0,
        "a1_forecast_buffer_percent": 5.0,
        "a1_escalation_hours": 2900.0,
        "retained_volume_warning_usd": 4.61,
        "retained_volume_escalation_usd": 6.61,
        "object_storage_warning_percent": 75.0,
        "object_storage_escalation_percent": 90.0,
    }


def _event(code, severity, component, summary, details=None):
    return {
        "code": code,
        "severity": severity,
        "component": component,
        "summary": summary,
        "runbook": "docs/runbooks/monitoring.md",
        "details": details or {},
    }


def evaluate_rules(snapshot, rules=None):
    policy = default_rules()
    if rules:
        unknown = set(rules) - set(policy)
        if unknown:
            raise ValueError(f"unknown monitoring rules: {', '.join(sorted(unknown))}")
        policy.update(rules)
    events = []
    checks = snapshot.get("checks") or {}
    for name, code, component in (
        ("https", "HTTPS_UNAVAILABLE", "ingress"),
        ("websocket", "WSS_UNAVAILABLE", "websocket"),
        ("public_admin_denial", "PUBLIC_ADMIN_EXPOSED", "security"),
        ("internal_readiness", "INTERNAL_READINESS_FAILED", "application"),
    ):
        check = checks.get(name) or {}
        failures = int(check.get("consecutive_failures", 1 if check.get("ok") is False else 0))
        if check.get("ok") is False and failures >= policy["service_consecutive_failures"]:
            events.append(_event(code, "P1", component, f"{name} failed {failures} consecutive probes"))
    tls = checks.get("tls") or {}
    if isinstance(tls.get("days_remaining"), (int, float)) and tls["days_remaining"] < policy["tls_days_remaining"]:
        events.append(_event("TLS_EXPIRING", "P2", "tls", "Production TLS certificate has under 21 days remaining", {"days_remaining": tls["days_remaining"]}))

    metrics = snapshot.get("metrics") or {}
    containers = metrics.get("containers") or {}
    unhealthy = sorted(name for name, value in containers.items() if not value.get("running") or not value.get("healthy"))
    if unhealthy:
        events.append(_event("CONTAINER_UNHEALTHY", "P1", "containers", "One or more required containers are unavailable", {"containers": unhealthy}))
    restarting = sorted(name for name, value in containers.items() if int(value.get("restart_count", 0)) >= policy["container_restart_warning"])
    if restarting:
        events.append(_event("CONTAINER_RESTART_LOOP", "P1", "containers", "Container restart threshold exceeded", {"containers": restarting}))

    system = metrics.get("system") or {}
    exhausted = {
        key: system[key]
        for key in ("cpu_used_percent", "memory_used_percent", "disk_used_percent", "inode_used_percent")
        if isinstance(system.get(key), (int, float)) and system[key] >= policy[key]
    }
    if exhausted:
        events.append(_event("RESOURCE_HEADROOM", "P2", "host", "Host resource headroom threshold crossed", exhausted))

    application = metrics.get("application") or {}
    growth = application.get("database_growth_bytes_24h")
    if isinstance(growth, (int, float)) and growth >= policy["database_growth_bytes_24h"]:
        events.append(_event("DATABASE_GROWTH", "P3", "database", "Database 24-hour growth threshold crossed", {"growth_bytes_24h": growth}))
    oauth_requests = application.get("oauth_requests_5m", 0)
    oauth_errors = application.get("oauth_errors_5m", 0)
    if isinstance(oauth_requests, (int, float)) and isinstance(oauth_errors, (int, float)) and oauth_requests >= policy["oauth_minimum_requests"] and oauth_errors / max(oauth_requests, 1) >= policy["oauth_error_rate"]:
        events.append(_event("OAUTH_ERROR_RATE", "P2", "identity", "OAuth error-rate threshold crossed", {"errors": oauth_errors, "requests": oauth_requests}))

    backups = metrics.get("backups") or {}
    if backups.get("database_age_hours", 0) > policy["database_backup_age_hours"]:
        events.append(_event("DATABASE_BACKUP_STALE", "P1", "backup", "Verified database backup is older than seven hours", {"age_hours": backups["database_age_hours"]}))
    if backups.get("media_age_hours", 0) > policy["media_backup_age_hours"]:
        events.append(_event("MEDIA_BACKUP_STALE", "P2", "backup", "Verified media backup is older than 26 hours", {"age_hours": backups["media_age_hours"]}))
    if backups and (not backups.get("database_verified", False) or not backups.get("media_verified", False)):
        events.append(_event("BACKUP_UNVERIFIED", "P1", "backup", "Latest database or media backup is unverified"))
    generations = backups.get("production_caddy_verified_generations")
    if isinstance(generations, int) and generations < policy["caddy_verified_generations"]:
        events.append(_event("CADDY_BACKUP_GENERATIONS", "P2", "backup", "Fewer than three verified production Caddy-state generations remain", {"generations": generations}))

    oci = metrics.get("oci") or {}
    _evaluate_oci(oci, policy, events)
    observed_at = str(snapshot.get("observed_at") or _timestamp())
    for event in events:
        event.update(
            schema_version=SCHEMA_VERSION,
            event_id=f"{event['component']}:{event['code']}",
            status="firing",
            observed_at=observed_at,
        )
    return events


def _evaluate_oci(oci, policy, events):
    forecast = oci.get("a1_forecast_ocpu_hours")
    actual = oci.get("a1_actual_ocpu_hours")
    projected = oci.get("a1_projected_ocpu_hours")
    slope_72h = oci.get("a1_slope_projected_72h")
    numeric = all(isinstance(value, (int, float)) and math.isfinite(value) for value in (forecast, actual, projected, slope_72h))
    if numeric:
        if forecast < policy["a1_forecast_cutoff_hours"]:
            buffer_hours = max(policy["a1_forecast_minimum_buffer_hours"], forecast * policy["a1_forecast_buffer_percent"] / 100.0)
            if projected > forecast + buffer_hours or slope_72h > forecast + buffer_hours:
                events.append(_event("A1_FORECAST_VARIANCE", "P3", "cost", "A1 usage is projected to exceed the accepted forecast buffer; inspect Restream duty-cycling first", {"forecast_hours": forecast, "buffer_hours": buffer_hours, "projected_hours": projected, "slope_72h_hours": slope_72h}))
        else:
            events.append(_event("A1_HIGH_FORECAST_RECORDED", "P3", "cost", "Accepted high A1 forecast is recorded; relative warning suppressed", {"forecast_hours": forecast}))
        if max(actual, projected) >= policy["a1_escalation_hours"]:
            events.append(_event("A1_ALLOWANCE_ESCALATION", "P2", "cost", "A1 allowance utilization reached 2,900 hours; inspect Restream sleep automation, encoders, and control planes first", {"actual_hours": actual, "projected_hours": projected}))
    storage = max(float(oci.get("object_storage_bytes_percent", 0)), float(oci.get("object_storage_requests_percent", 0)))
    if storage >= policy["object_storage_escalation_percent"]:
        events.append(_event("OBJECT_STORAGE_ESCALATION", "P2", "cost", "Object Storage usage reached 90% of a verified entitlement", {"maximum_percent": storage}))
    elif storage >= policy["object_storage_warning_percent"]:
        events.append(_event("OBJECT_STORAGE_WARNING", "P3", "cost", "Object Storage usage reached 75% of a verified entitlement", {"maximum_percent": storage}))
    retained = float(oci.get("retained_volume_cost_usd", 0))
    if retained >= policy["retained_volume_escalation_usd"]:
        events.append(_event("RETAINED_VOLUME_ESCALATION", "P2", "cost", "Retained-volume cost exceeds the $3.61 baseline by at least $3", {"cost_usd": retained}))
    elif retained >= policy["retained_volume_warning_usd"]:
        events.append(_event("RETAINED_VOLUME_WARNING", "P3", "cost", "Retained-volume cost exceeds the $3.61 baseline by at least $1", {"cost_usd": retained}))
    if oci.get("billing_events"):
        events.append(_event("BILLING_EVENT", "P3", "cost", "Normalized OCI billing event requires attribution and forecast reconciliation", {"count": len(oci["billing_events"])}))


def _load_json(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("JSON input must contain an object")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--rules")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    config = _load_json(args.config)
    if "probe" in config:
        config = config["probe"]
    rules = _load_json(args.rules) if args.rules else None
    snapshot = collect_snapshot(config)
    snapshot["events"] = evaluate_rules(snapshot, rules)
    rendered = json.dumps(snapshot, sort_keys=True, indent=2) + "\n"
    if args.output:
        target = Path(args.output)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, target)
    else:
        sys.stdout.write(rendered)
    return 1 if any(event["severity"] in {"P0", "P1"} for event in snapshot["events"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
