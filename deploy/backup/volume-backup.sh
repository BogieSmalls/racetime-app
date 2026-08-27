#!/usr/bin/env bash
# Media and Caddy-state backups. These volumes change far more slowly than the
# database, so they run once a day on their own timer rather than riding the
# six-hourly database cycle. Retention runs from scheduled-backup.sh and prunes
# the whole production/ prefix, so it is deliberately not repeated here.
set -Eeuo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
config="${Z1RR_BACKUP_CONFIG:-/etc/z1rr-racetime/backup.env}"
[[ -r "$config" && "$(stat -c '%u' "$config")" == '0' ]] || {
    printf '%s\n' 'VOLUME_BACKUP=FAIL configuration' >&2
    exit 1
}
# shellcheck disable=SC1090
source "$config"
: "${RACETIME_RELEASE_SHA:?missing RACETIME_RELEASE_SHA}"
: "${BACKUP_STATUS_DIR:?missing BACKUP_STATUS_DIR}"
: "${OCI_PREFIX:?missing OCI_PREFIX}"
[[ "$RACETIME_RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 1
[[ "$OCI_PREFIX" == production ]] || exit 1

status_file="${BACKUP_STATUS_DIR%/}/volume-backup-status.json"
failure_file="${BACKUP_STATUS_DIR%/}/volume-backup-failure"
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
            "$BACKUP_ALERT_HOOK" volume-backup failure >/dev/null 2>&1 || true
        fi
    fi
    exit "$result"
}
trap on_exit EXIT

"$script_dir/backup.sh" --type media --release-sha "$RACETIME_RELEASE_SHA"
# Daily coverage captures any automatic certificate renewal since the prior
# run; explicit issuance and config-change captures remain event-driven.
"$script_dir/backup.sh" --type production-caddy-state \
    --reason renewal --release-sha "$RACETIME_RELEASE_SHA"

printf '%s\n' 'VOLUME_BACKUP=PASS'
