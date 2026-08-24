#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

fail() {
    printf 'ROLLBACK=FAIL %s\n' "$1" >&2
    exit 1
}

usage() {
    printf '%s\n' \
        'Usage: rollback.sh --environment production|integration --target-manifest FILE [--emergency-change-id ID]' >&2
    exit 2
}

environment=''
target_manifest=''
emergency_change_id=''
while (($#)); do
    case "$1" in
        --environment) (($# >= 2)) || usage; environment="$2"; shift 2 ;;
        --target-manifest) (($# >= 2)) || usage; target_manifest="$2"; shift 2 ;;
        --emergency-change-id) (($# >= 2)) || usage; emergency_change_id="$2"; shift 2 ;;
        *) usage ;;
    esac
done
[[ "$environment" == production || "$environment" == integration ]] \
    || fail 'invalid environment'
[[ -r "$target_manifest" ]] || fail 'target release manifest unavailable'
if [[ -n "$emergency_change_id" ]]; then
    [[ "$emergency_change_id" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$ ]] \
        || fail 'emergency change ID invalid'
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON_BIN:-python3}"
release_tool="$script_dir/release_tool.py"
deploy_script="${Z1RR_DEPLOY_SCRIPT:-$script_dir/deploy.sh}"
config="${Z1RR_DEPLOY_CONFIG:-/etc/z1rr-racetime/deploy.env}"
[[ -r "$config" && "$(stat -c '%u' "$config")" == 0 ]] \
    || fail 'root-owned deployment configuration is required'
# shellcheck disable=SC1090
source "$config"
: "${Z1RR_DEPLOY_STATE_DIR:?missing deployment state directory}"
state_dir="${Z1RR_DEPLOY_STATE_DIR%/}"
[[ "$state_dir" == /* && "$state_dir" != / && -d "$state_dir" ]] \
    || fail 'unsafe or absent deployment state directory'
[[ -r "$deploy_script" ]] || fail 'deployment controller unavailable'

current_record="$state_dir/current-release.json"
previous_record="$state_dir/previous-release.json"
[[ -r "$current_record" ]] || fail 'current release record unavailable'
"$python_bin" "$release_tool" validate --manifest "$target_manifest" \
    || fail 'target release manifest invalid'
record_get() {
    "$python_bin" "$release_tool" record-get \
        --record "$1" --field "$2"
}
target_get() {
    "$python_bin" "$release_tool" get \
        --manifest "$target_manifest" --field "$1"
}

current_sha="$(record_get "$current_record" manifest.release_sha)"
rollback_class="$(record_get "$current_record" manifest.migrations.rollback_class)"
current_minimum_digest="$(record_get \
    "$current_record" manifest.minimum_rollback_digest)"
target_sha="$(target_get release_sha)"
target_digest="$(target_get images.application.digest)"
reverse_target=''

matches_previous() {
    [[ -r "$previous_record" ]] || return 1
    local previous_sha previous_digest
    previous_sha="$(record_get "$previous_record" manifest.release_sha)"
    previous_digest="$(record_get \
        "$previous_record" manifest.images.application.digest)"
    [[ "$target_sha" == "$previous_sha" \
        && "$target_digest" == "$previous_digest" ]]
}

case "$rollback_class" in
    code-only)
        matches_previous \
            || fail 'code-only rollback target is not the prior pinned release'
        [[ "$target_digest" == "$current_minimum_digest" ]] \
            || fail 'code-only rollback target violates the compatibility floor'
        ;;
    forward-fix)
        approved_fix="$(record_get \
            "$current_record" manifest.migrations.forward_fix_release)"
        [[ "$target_sha" == "$approved_fix" ]] \
            || fail 'forward-fix target is not the manifest-approved release'
        ;;
    reversible)
        matches_previous \
            || fail 'reversible rollback target is not the prior pinned release'
        [[ "$target_digest" == "$current_minimum_digest" ]] \
            || fail 'reversible rollback target violates the compatibility floor'
        reverse_target="$(record_get \
            "$current_record" manifest.migrations.reverse_target)"
        [[ "$reverse_target" =~ ^[a-z][a-z0-9_]*\.[0-9]{4}_[a-z0-9_]+$ ]] \
            || fail 'reviewed reverse migration target is absent'
        ;;
    *) fail 'unknown rollback class' ;;
esac

deploy_args=(
    --environment "$environment"
    --manifest "$target_manifest"
    --expected-current-release "$current_sha"
)
[[ -n "$reverse_target" ]] \
    && deploy_args+=(--reverse-target "$reverse_target")
[[ -n "$emergency_change_id" ]] \
    && deploy_args+=(--emergency-change-id "$emergency_change_id")

export Z1RR_DEPLOY_ACTION=rollback
bash "$deploy_script" "${deploy_args[@]}"
printf 'ROLLBACK=PASS class=%s from=%s to=%s\n' \
    "$rollback_class" "$current_sha" "$target_sha"
