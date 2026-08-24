#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

fail() {
    printf 'PREFLIGHT=FAIL %s\n' "$1" >&2
    exit 1
}

usage() {
    printf '%s\n' \
        'Usage: preflight.sh --environment production|integration --release-sha <40-hex> [--emergency-change-id ID]' >&2
    exit 2
}

environment=''
release_sha=''
emergency_change_id=''
while (($#)); do
    case "$1" in
        --environment)
            (($# >= 2)) || usage
            environment="$2"
            shift 2
            ;;
        --release-sha)
            (($# >= 2)) || usage
            release_sha="$2"
            shift 2
            ;;
        --emergency-change-id)
            (($# >= 2)) || usage
            emergency_change_id="$2"
            shift 2
            ;;
        *) usage ;;
    esac
done

[[ "$environment" == 'production' || "$environment" == 'integration' ]] \
    || fail 'environment must be production or integration'
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] \
    || fail 'release SHA must be exactly 40 lowercase hexadecimal characters'
if [[ -n "$emergency_change_id" ]]; then
    [[ "$emergency_change_id" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$ ]] \
        || fail 'emergency-change-id has an invalid format'
elif [[ -n "${Z1RR_ALLOW_ACTIVE_RACES:-}" ]]; then
    fail 'active-race continuation requires --emergency-change-id'
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
compose_file="${Z1RR_COMPOSE_FILE:-$repo_root/deploy/compose.production.yml}"
python_bin="${PYTHON_BIN:-python3}"
backup_script="${Z1RR_BACKUP_SCRIPT:-$repo_root/deploy/backup/backup.sh}"
backup_config="${Z1RR_BACKUP_CONFIG:-/etc/z1rr-racetime/backup.env}"
minimum_free_kb="${MIN_FREE_DISK_KB:-5242880}"

for command_name in docker "$python_bin" df timedatectl age zstd oci sha256sum stat awk grep; do
    command -v "$command_name" >/dev/null 2>&1 \
        || fail "required command unavailable: $command_name"
done

[[ "${RACETIME_IMAGE:-}" == *":$release_sha" ]] \
    || fail 'application image is not tagged with the requested release SHA'
[[ "${RACETIME_IMAGE_DIGEST:-}" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || fail 'application image digest is not immutable'
[[ "${RACETIME_MAINTENANCE_IMAGE:-}" == *":$release_sha" ]] \
    || fail 'maintenance image is not tagged with the requested release SHA'
[[ "${RACETIME_MAINTENANCE_IMAGE_DIGEST:-}" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || fail 'maintenance image digest is not immutable'
[[ -x "$backup_script" ]] || fail 'backup prerequisite unavailable'
[[ -r "$backup_config" ]] || fail 'backup configuration unavailable'

if [[ "$environment" == 'production' ]]; then
    preflight_config="${Z1RR_PREFLIGHT_CONFIG:-/etc/z1rr-racetime/preflight.env}"
    [[ -r "$preflight_config" ]] || fail 'root-owned preflight config is required'
    [[ "$(stat -c '%u' "$preflight_config")" == '0' ]] \
        || fail 'root-owned preflight config is required'
    [[ "$(stat -c '%u' "$backup_config")" == '0' ]] \
        || fail 'root-owned backup config is required'

    # This trusted file contains only evidence paths and hashes. It is kept
    # outside the repository and is writable only by root on the host.
    # shellcheck disable=SC1090
    source "$preflight_config"
    : "${Z1RR_G1_ACTIVATION_RECORD:?missing activation record path}"
    : "${Z1RR_G2_EVIDENCE_PATH:?missing G2 evidence path}"
    : "${Z1RR_G2_EVIDENCE_SHA256:?missing G2 evidence hash}"
    [[ -s "$Z1RR_G1_ACTIVATION_RECORD" ]] \
        || fail 'G1 activation record is absent or empty'
    [[ -s "$Z1RR_G2_EVIDENCE_PATH" ]] \
        || fail 'G2 evidence is absent or empty'
    [[ "$Z1RR_G2_EVIDENCE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
        || fail 'G2 evidence hash is invalid'
    actual_evidence_hash="$(sha256sum "$Z1RR_G2_EVIDENCE_PATH" | awk '{print $1}')"
    [[ "$actual_evidence_hash" == "$Z1RR_G2_EVIDENCE_SHA256" ]] \
        || fail 'G2 evidence hash mismatch'
fi

if ! "$python_bin" "$repo_root/deploy/validate-config.py" >/dev/null; then
    fail 'configuration validation failed'
fi

compose=(docker compose -f "$compose_file")
if ! "${compose[@]}" config --quiet >/dev/null; then
    fail 'Compose configuration invalid'
fi

[[ "$minimum_free_kb" =~ ^[0-9]+$ ]] && ((minimum_free_kb > 0)) \
    || fail 'MIN_FREE_DISK_KB must be a positive integer'
free_kb="$(df -Pk "$repo_root" | awk 'NR == 2 {print $4}')"
[[ "$free_kb" =~ ^[0-9]+$ ]] \
    || fail 'disk headroom probe returned invalid data'
((free_kb >= minimum_free_kb)) || fail 'insufficient disk headroom'

ntp_state="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
[[ "$ntp_state" == 'yes' ]] || fail 'time synchronization unavailable'

if ! running_services="$("${compose[@]}" ps --status running --services)"; then
    fail 'unable to inspect stack health'
fi
for service in caddy web racebot db redis; do
    grep -Fxq "$service" <<<"$running_services" \
        || fail "service not running: $service"
    container_id="$("${compose[@]}" ps -q "$service")"
    [[ -n "$container_id" ]] || fail "service container missing: $service"
    health_state="$(docker inspect --format \
        '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
        "$container_id")"
    [[ "$health_state" == 'healthy' ]] \
        || fail "service unhealthy: $service"
done

application_preflight=(
    exec -T web python manage.py deployment_preflight --json
)
if [[ -n "$emergency_change_id" ]]; then
    application_preflight+=(--allow-active-races)
    printf 'PREFLIGHT_AUDIT emergency_change_id=%s\n' "$emergency_change_id"
fi
if ! "${compose[@]}" "${application_preflight[@]}"; then
    fail 'authoritative application preflight failed'
fi

printf 'PREFLIGHT=PASS environment=%s release_sha=%s\n' \
    "$environment" "$release_sha"
