#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON_BIN:-python3}"
config="${Z1RR_BACKUP_CONFIG:-/etc/z1rr-racetime/backup.env}"
[[ -r "$config" && "$(stat -c '%u' "$config")" == '0' ]] || {
    printf '%s\n' 'SCHEDULED_BACKUP=FAIL configuration' >&2
    exit 1
}
# shellcheck disable=SC1090
source "$config"
: "${RACETIME_RELEASE_SHA:?missing RACETIME_RELEASE_SHA}"
: "${BACKUP_STATUS_DIR:?missing BACKUP_STATUS_DIR}"
: "${OCI_NAMESPACE:?missing OCI_NAMESPACE}"
: "${OCI_BUCKET:?missing OCI_BUCKET}"
: "${OCI_PREFIX:?missing OCI_PREFIX}"
[[ "$RACETIME_RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 1
[[ "$OCI_PREFIX" == production ]] || exit 1

status_file="${BACKUP_STATUS_DIR%/}/scheduled-backup-status.json"
failure_file="${BACKUP_STATUS_DIR%/}/scheduled-backup-failure"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
on_exit() {
    local result=$?
    trap - EXIT
    local completed_at
    completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if ((result == 0)); then
        printf '{"schema":1,"status":"pass","started_at":"%s","completed_at":"%s"}\n' \
            "$started_at" "$completed_at" >"$status_file"
        rm -f -- "$failure_file"
    else
        printf '{"schema":1,"status":"failure","started_at":"%s","completed_at":"%s"}\n' \
            "$started_at" "$completed_at" >"$status_file"
        printf '%s\n' "$completed_at" >"$failure_file"
        if [[ -n "${BACKUP_ALERT_HOOK:-}" && -x "$BACKUP_ALERT_HOOK" ]]; then
            "$BACKUP_ALERT_HOOK" backup-cycle failure >/dev/null 2>&1 || true
        fi
    fi
    exit "$result"
}
trap on_exit EXIT

"$script_dir/backup.sh" --type database --release-sha "$RACETIME_RELEASE_SHA"
if [[ "$(date -u +%H)" == '00' ]]; then
    "$script_dir/backup.sh" --type media --release-sha "$RACETIME_RELEASE_SHA"
    # Nightly coverage captures any automatic certificate renewal since the
    # prior run; explicit issuance/config-change captures remain event-driven.
    "$script_dir/backup.sh" --type production-caddy-state \
        --reason renewal --release-sha "$RACETIME_RELEASE_SHA"
fi

retention_plan="${BACKUP_STATUS_DIR%/}/last-retention-plan.json"
"$python_bin" "$script_dir/retention.py" \
    --remote \
    --namespace "$OCI_NAMESPACE" \
    --bucket "$OCI_BUCKET" \
    --prefix "$OCI_PREFIX/" \
    --apply \
    --output "$retention_plan"

printf '%s\n' 'SCHEDULED_BACKUP=PASS'
