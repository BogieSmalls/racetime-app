#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

fail() {
    printf 'DEPLOY=FAIL %s\n' "$1" >&2
    exit 1
}

usage() {
    printf '%s\n' \
        'Usage: deploy.sh --environment production|integration --manifest FILE [--emergency-change-id ID] [--expected-current-release SHA --reverse-target app.migration]' >&2
    exit 2
}

environment=''
manifest=''
emergency_change_id=''
expected_current_release=''
reverse_target=''
while (($#)); do
    case "$1" in
        --environment) (($# >= 2)) || usage; environment="$2"; shift 2 ;;
        --manifest) (($# >= 2)) || usage; manifest="$2"; shift 2 ;;
        --emergency-change-id) (($# >= 2)) || usage; emergency_change_id="$2"; shift 2 ;;
        --expected-current-release) (($# >= 2)) || usage; expected_current_release="$2"; shift 2 ;;
        --reverse-target) (($# >= 2)) || usage; reverse_target="$2"; shift 2 ;;
        *) usage ;;
    esac
done
[[ "$environment" == production || "$environment" == integration ]] \
    || fail 'invalid environment'
[[ -r "$manifest" ]] || fail 'release manifest unavailable'
if [[ -n "$emergency_change_id" ]]; then
    [[ "$emergency_change_id" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$ ]] \
        || fail 'emergency change ID invalid'
fi
if [[ -n "$expected_current_release" ]]; then
    [[ "$expected_current_release" =~ ^[0-9a-f]{40}$ ]] \
        || fail 'expected current release is invalid'
fi
if [[ -n "$reverse_target" ]]; then
    [[ -n "$expected_current_release" \
        && "$reverse_target" =~ ^[a-z][a-z0-9_]*\.[0-9]{4}_[a-z0-9_]+$ ]] \
        || fail 'reversible rollback arguments are incomplete'
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
release_tool="$script_dir/release_tool.py"
backup_manifest_tool="$repo_root/deploy/backup/manifest.py"
config="${Z1RR_DEPLOY_CONFIG:-/etc/z1rr-racetime/deploy.env}"
[[ -r "$config" && "$(stat -c '%u' "$config")" == 0 ]] \
    || fail 'root-owned deployment configuration is required'
set -a
# shellcheck disable=SC1090
source "$config"
set +a
: "${Z1RR_DEPLOY_STATE_DIR:?missing deployment state directory}"
: "${Z1RR_BACKUP_STATUS_DIR:?missing backup status directory}"
: "${Z1RR_COMPOSE_FILE:?missing Compose file}"
: "${Z1RR_APP_IMAGE_REPOSITORY:?missing application repository policy}"
: "${Z1RR_MAINTENANCE_IMAGE_REPOSITORY:?missing maintenance repository policy}"
: "${Z1RR_COSIGN_IDENTITY_REGEXP:?missing cosign identity policy}"
: "${Z1RR_COSIGN_OIDC_ISSUER:?missing cosign issuer policy}"
: "${Z1RR_PUBLIC_ORIGIN:?missing public origin}"
: "${Z1RR_SMOKE_WEBSOCKET_PATH:?missing WebSocket smoke path}"
: "${Z1RR_DEPLOY_ACTOR:?missing deployment actor}"
: "${RACETIME_ENV_FILE:?missing RaceTime environment file}"
: "${CADDY_ENV_FILE:?missing Caddy environment file}"
: "${RACETIME_STATE_GENERATION:?missing state generation}"
: "${CADDY_STATE_VOLUME:?missing Caddy state volume}"

state_dir="${Z1RR_DEPLOY_STATE_DIR%/}"
backup_status_dir="${Z1RR_BACKUP_STATUS_DIR%/}"
[[ "$state_dir" == /* && "$state_dir" != / && -d "$state_dir" ]] \
    || fail 'unsafe or absent deployment state directory'
[[ "$backup_status_dir" == /* && "$backup_status_dir" != / \
    && -d "$backup_status_dir" ]] || fail 'unsafe backup status directory'
expected_generation=qualification
[[ "$environment" == production ]] && expected_generation=production
[[ "$RACETIME_STATE_GENERATION" == "$expected_generation" ]] \
    || fail 'deployment environment and state generation disagree'
preflight_script="${Z1RR_PREFLIGHT_SCRIPT:-$script_dir/preflight.sh}"
backup_script="${Z1RR_BACKUP_SCRIPT:-$repo_root/deploy/backup/backup.sh}"
smoke_script="${Z1RR_SMOKE_SCRIPT:-$script_dir/smoke.py}"
[[ -r "$preflight_script" ]] || fail 'preflight script unavailable'
[[ -r "$backup_script" ]] || fail 'backup script unavailable'
[[ -r "$smoke_script" ]] || fail 'smoke script unavailable'
for command_name in "$python_bin" docker cosign flock stat; do
    command -v "$command_name" >/dev/null 2>&1 \
        || fail "required command unavailable: $command_name"
done

"$python_bin" "$release_tool" validate --manifest "$manifest" \
    || fail 'release manifest invalid'
get() {
    "$python_bin" "$release_tool" get --manifest "$manifest" --field "$1"
}
release_sha="$(get release_sha)"
app_repository="$(get images.application.repository)"
app_digest="$(get images.application.digest)"
maintenance_repository="$(get images.maintenance.repository)"
maintenance_digest="$(get images.maintenance.digest)"
migration_strategy="$(get migrations.strategy)"
rollback_class="$(get migrations.rollback_class)"
[[ "$app_repository" == "$Z1RR_APP_IMAGE_REPOSITORY" \
    && "$maintenance_repository" == "$Z1RR_MAINTENANCE_IMAGE_REPOSITORY" ]] \
    || fail 'release repository violates root-owned policy'
app_image="$app_repository:$release_sha"
maintenance_image="$maintenance_repository:$release_sha"
app_reference="$app_image@$app_digest"
maintenance_reference="$maintenance_image@$maintenance_digest"

current_record="$state_dir/current-release.json"
previous_record="$state_dir/previous-release.json"
audit_log="$state_dir/deploy-audit.jsonl"
lock_file="$state_dir/deploy.lock"
[[ -r "$current_record" ]] || fail 'current release record is required'
record_get() {
    "$python_bin" "$release_tool" record-get \
        --record "$current_record" --field "$1"
}
current_sha="$(record_get manifest.release_sha)"
current_app_repository="$(record_get manifest.images.application.repository)"
current_app_digest="$(record_get manifest.images.application.digest)"
current_maintenance_repository="$(record_get manifest.images.maintenance.repository)"
current_maintenance_digest="$(record_get manifest.images.maintenance.digest)"
current_app_image="$current_app_repository:$current_sha"
current_maintenance_image="$current_maintenance_repository:$current_sha"
if [[ -n "$expected_current_release" ]]; then
    [[ "$current_sha" == "$expected_current_release" ]] \
        || fail 'current release changed before rollback lock'
fi
if [[ -n "$reverse_target" ]]; then
    current_rollback_class="$(record_get manifest.migrations.rollback_class)"
    current_reverse_target="$(record_get manifest.migrations.reverse_target)"
    [[ "$current_rollback_class" == reversible \
        && "$current_reverse_target" == "$reverse_target" ]] \
        || fail 'blind or mismatched reverse migration refused'
fi

action="${Z1RR_DEPLOY_ACTION:-deploy}"
[[ "$action" == deploy || "$action" == rollback ]] \
    || fail 'deployment action invalid'
audit() {
    local stage="$1" status="$2"
    local args=(
        audit --log "$audit_log" --action "$action"
        --release-sha "$release_sha" --stage "$stage" --status "$status"
        --actor "$Z1RR_DEPLOY_ACTOR" --environment "$environment"
    )
    [[ -n "$emergency_change_id" ]] \
        && args+=(--emergency-change-id "$emergency_change_id")
    "$python_bin" "$release_tool" "${args[@]}"
}
run_stage() {
    local stage="$1"
    shift
    audit "$stage" start
    if [[ "${Z1RR_FAIL_STAGE:-}" == "$stage" ]]; then
        audit "$stage" fail
        return 97
    fi
    if "$@"; then
        audit "$stage" pass
    else
        local result=$?
        audit "$stage" fail || true
        return "$result"
    fi
}
skip_stage() {
    audit "$1" skipped
}

set_target_images() {
    export RACETIME_IMAGE="$app_image"
    export RACETIME_IMAGE_DIGEST="$app_digest"
    export RACETIME_MAINTENANCE_IMAGE="$maintenance_image"
    export RACETIME_MAINTENANCE_IMAGE_DIGEST="$maintenance_digest"
}
set_current_images() {
    export RACETIME_IMAGE="$current_app_image"
    export RACETIME_IMAGE_DIGEST="$current_app_digest"
    export RACETIME_MAINTENANCE_IMAGE="$current_maintenance_image"
    export RACETIME_MAINTENANCE_IMAGE_DIGEST="$current_maintenance_digest"
}
set_target_images
compose=(docker compose -f "$Z1RR_COMPOSE_FILE")
locked=0
services_changed=0
promoted=0
automatic_restore_allowed=0
[[ "$rollback_class" == code-only && -z "$reverse_target" ]] \
    && automatic_restore_allowed=1

restore_prior_services() {
    set_current_images
    "${compose[@]}" up -d web racebot >/dev/null
}
cleanup() {
    local result=$?
    trap - EXIT
    set +e
    if ((result != 0 && services_changed == 1 && promoted == 0)); then
        if ((automatic_restore_allowed == 1)); then
            audit restore_prior start
            if restore_prior_services; then
                audit restore_prior pass
            else
                audit restore_prior fail
            fi
        else
            audit manual_rollback_required fail
        fi
    fi
    if ((locked == 1)); then
        audit unlock start
        if flock -u 9; then
            audit unlock pass
        else
            audit unlock fail
        fi
    fi
    exit "$result"
}

exec 9>"$lock_file"
audit lock start
if [[ "${Z1RR_FAIL_STAGE:-}" == lock ]] || ! flock -n 9; then
    audit lock fail || true
    fail 'deployment lock unavailable'
fi
locked=1
audit lock pass
trap cleanup EXIT

# Recheck the record under the lock so rollback cannot race another promotion.
locked_current_sha="$(record_get manifest.release_sha)"
[[ "$locked_current_sha" == "$current_sha" ]] \
    || fail 'current release changed while acquiring lock'

preflight_args=(
    --environment "$environment" --release-sha "$release_sha"
)
[[ -n "$emergency_change_id" ]] \
    && preflight_args+=(--emergency-change-id "$emergency_change_id")
preflight_stage() {
    set_target_images
    bash "$preflight_script" "${preflight_args[@]}"
}
run_stage preflight preflight_stage

backup_stage() {
    local pin_until
    pin_until="$("$python_bin" "$release_tool" pin-until --days 30)"
    bash "$backup_script" --type database --release-sha "$current_sha" \
        --reason predeploy --pinned-until "$pin_until"
    local status_manifest="$backup_status_dir/last-database.json"
    "$python_bin" "$backup_manifest_tool" validate \
        --manifest "$status_manifest" --require-verified
    [[ "$("$python_bin" "$backup_manifest_tool" get \
        --manifest "$status_manifest" --field release_sha)" == "$current_sha" ]]
}
run_stage backup backup_stage

pull_stage() {
    docker pull "$app_reference"
    docker pull "$maintenance_reference"
}
run_stage pull pull_stage

verify_image() {
    local reference="$1"
    cosign verify \
        --certificate-identity-regexp "$Z1RR_COSIGN_IDENTITY_REGEXP" \
        --certificate-oidc-issuer "$Z1RR_COSIGN_OIDC_ISSUER" \
        "$reference" >/dev/null
    cosign verify-attestation \
        --certificate-identity-regexp "$Z1RR_COSIGN_IDENTITY_REGEXP" \
        --certificate-oidc-issuer "$Z1RR_COSIGN_OIDC_ISSUER" \
        --type spdxjson "$reference" >/dev/null
    cosign verify-attestation \
        --certificate-identity-regexp "$Z1RR_COSIGN_IDENTITY_REGEXP" \
        --certificate-oidc-issuer "$Z1RR_COSIGN_OIDC_ISSUER" \
        --type slsaprovenance "$reference" >/dev/null
}
supply_chain_stage() {
    verify_image "$app_reference"
    verify_image "$maintenance_reference"
}
run_stage supply_chain supply_chain_stage

migration_plan_stage() {
    if [[ -n "$reverse_target" ]]; then
        set_current_images
        local app_label="${reverse_target%%.*}"
        local migration_name="${reverse_target#*.}"
        "${compose[@]}" run --rm maintenance maintenance \
            python manage.py migrate "$app_label" "$migration_name" --plan
    else
        set_target_images
        "${compose[@]}" run --rm maintenance maintenance \
            python manage.py migrate --plan
    fi
}
run_stage migration_plan migration_plan_stage

migration_required=0
[[ "$migration_strategy" != none || -n "$reverse_target" ]] \
    && migration_required=1
if ((migration_required == 1)); then
    stop_writes_stage() {
        "${compose[@]}" stop web racebot
        services_changed=1
    }
    run_stage stop_writes stop_writes_stage

    migrate_stage() {
        if [[ -n "$reverse_target" ]]; then
            set_current_images
            local app_label="${reverse_target%%.*}"
            local migration_name="${reverse_target#*.}"
            "${compose[@]}" run --rm maintenance maintenance \
                python manage.py migrate "$app_label" "$migration_name" --noinput
        else
            set_target_images
            "${compose[@]}" --profile deploy run --rm migrate
        fi
    }
    run_stage migrate migrate_stage
else
    skip_stage stop_writes
    skip_stage migrate
fi

collectstatic_stage() {
    set_target_images
    "${compose[@]}" --profile deploy run --rm collectstatic
}
run_stage collectstatic collectstatic_stage

wait_for_service() {
    local service="$1"
    local attempt container_id state
    for attempt in $(seq 1 30); do
        container_id="$("${compose[@]}" ps -q "$service")"
        if [[ -n "$container_id" ]]; then
            state="$(docker inspect --format \
                '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
                "$container_id")"
            [[ "$state" == healthy ]] && return 0
        fi
        sleep 1
    done
    return 1
}
start_services_stage() {
    set_target_images
    "${compose[@]}" up -d web racebot
    services_changed=1
    local service
    for service in web racebot db redis; do
        wait_for_service "$service" || return 1
    done
}
run_stage start_services start_services_stage

smoke_stage() {
    local smoke_command=(bash "$smoke_script")
    [[ "$smoke_script" == *.py ]] \
        && smoke_command=("$python_bin" "$smoke_script")
    "${smoke_command[@]}" \
        --origin "$Z1RR_PUBLIC_ORIGIN" \
        --websocket-path "$Z1RR_SMOKE_WEBSOCKET_PATH"
    local command=(
        exec -T web python manage.py deployment_preflight --json
    )
    [[ -n "$emergency_change_id" ]] && command+=(--allow-active-races)
    "${compose[@]}" "${command[@]}" >/dev/null
}
run_stage smoke smoke_stage

promote_stage() {
    local args=(
        promote --manifest "$manifest" --current "$current_record"
        --previous "$previous_record" --actor "$Z1RR_DEPLOY_ACTOR"
    )
    [[ -n "$emergency_change_id" ]] \
        && args+=(--emergency-change-id "$emergency_change_id")
    "$python_bin" "$release_tool" "${args[@]}"
}
run_stage promote promote_stage
promoted=1

printf 'DEPLOY=PASS environment=%s release_sha=%s\n' \
    "$environment" "$release_sha"
