#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

fail() {
    printf 'RESTORE_TEST=FAIL %s\n' "$1" >&2
    exit 1
}

database_manifest=''
media_manifest=''
caddy_manifest=''
release_sha=''
while (($#)); do
    case "$1" in
        --database-manifest) database_manifest="$2"; shift 2 ;;
        --media-manifest) media_manifest="$2"; shift 2 ;;
        --caddy-manifest) caddy_manifest="$2"; shift 2 ;;
        --release-sha) release_sha="$2"; shift 2 ;;
        *) fail 'invalid argument' ;;
    esac
done
[[ -n "$database_manifest" && -n "$media_manifest" && -n "$caddy_manifest" ]] \
    || fail 'all three manifest objects are required'
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid release SHA'
for object_name in "$database_manifest" "$media_manifest" "$caddy_manifest"; do
    [[ "$object_name" == production/*.manifest.json \
        && "$object_name" != *qualification* ]] \
        || fail 'qualification or unsafe manifest is restore-ineligible'
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
config="${Z1RR_BACKUP_CONFIG:-/etc/z1rr-racetime/backup.env}"
[[ -r "$config" && "$(stat -c '%u' "$config")" == '0' ]] \
    || fail 'root-owned backup configuration is required'
# shellcheck disable=SC1090
source "$config"
: "${OCI_NAMESPACE:?missing OCI_NAMESPACE}"
: "${OCI_BUCKET:?missing OCI_BUCKET}"
: "${AGE_IDENTITY_FILE:?missing AGE_IDENTITY_FILE}"
: "${BACKUP_SCRATCH_ROOT:?missing BACKUP_SCRATCH_ROOT}"
: "${BACKUP_STATUS_DIR:?missing BACKUP_STATUS_DIR}"
: "${RACETIME_COMPOSE_FILE:?missing RACETIME_COMPOSE_FILE}"
: "${ARCHIVE_HELPER_IMAGE:?missing ARCHIVE_HELPER_IMAGE}"
: "${CADDY_IMAGE:?missing CADDY_IMAGE}"
: "${CADDY_ENV_FILE:?missing CADDY_ENV_FILE}"
: "${PRODUCTION_SECRET_VOLUME:?missing PRODUCTION_SECRET_VOLUME}"
[[ "$PRODUCTION_SECRET_VOLUME" != *qualification* ]] \
    || fail 'qualification secrets are ineligible'
[[ "$PRODUCTION_SECRET_VOLUME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] \
    || fail 'production secret volume name is unsafe'
[[ "$ARCHIVE_HELPER_IMAGE" == *@sha256:* && "$CADDY_IMAGE" == *@sha256:* ]] \
    || fail 'restore helper images must be immutable'

scratch_root="${BACKUP_SCRATCH_ROOT%/}"
status_dir="${BACKUP_STATUS_DIR%/}"
[[ "$scratch_root" == /* && "$scratch_root" != '/' && -d "$scratch_root" ]] \
    || fail 'unsafe scratch root'
[[ "$status_dir" == /* && "$status_dir" != '/' && -d "$status_dir" ]] \
    || fail 'unsafe status directory'
restore_started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
scratch_dir="$(mktemp -d "$scratch_root/z1rr-restore-test.XXXXXX")"
run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM"
project="z1rr-restore-test-$run_id"
state_generation="restore-test-$run_id"
media_volume="z1rr-racetime-$state_generation-media"
caddy_volume="z1rr-restore-test-$run_id-caddy"
secret_volume="z1rr-racetime-$state_generation-secrets"
[[ "$project" == z1rr-restore-test-* && "$state_generation" == restore-test-* ]] \
    || fail 'production replacement is forbidden'
[[ "$media_volume" != 'z1rr-racetime-production-media' \
    && "$caddy_volume" != "$PRODUCTION_CADDY_STATE_VOLUME" ]] \
    || fail 'production replacement is forbidden'

export RACETIME_STATE_GENERATION="$state_generation"
export CADDY_STATE_VOLUME="$caddy_volume"
compose=(docker compose --project-name "$project" -f "$RACETIME_COMPOSE_FILE")
stack_initialized=0
cleanup() {
    local result=$?
    trap - EXIT
    set +e
    if ((stack_initialized == 1)); then
        "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1
        docker volume rm -f "$media_volume" "$caddy_volume" "$secret_volume" >/dev/null 2>&1
    fi
    case "$scratch_dir" in
        "$scratch_root"/z1rr-restore-test.*) rm -rf -- "$scratch_dir" ;;
    esac
    local completed_at
    completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if ((result == 0)); then
        printf '{"schema":1,"status":"pass","started_at":"%s","completed_at":"%s"}\n' \
            "$restore_started_at" "$completed_at" >"$status_dir/restore-test-status.json"
        rm -f -- "$status_dir/restore-test-failure"
    else
        printf '{"schema":1,"status":"failure","started_at":"%s","completed_at":"%s"}\n' \
            "$restore_started_at" "$completed_at" >"$status_dir/restore-test-status.json"
        printf '%s\n' "$completed_at" >"$status_dir/restore-test-failure"
        if [[ -n "${BACKUP_ALERT_HOOK:-}" && -x "$BACKUP_ALERT_HOOK" ]]; then
            "$BACKUP_ALERT_HOOK" restore-test failure >/dev/null 2>&1 || true
        fi
    fi
    exit "$result"
}
trap cleanup EXIT

docker volume inspect "$PRODUCTION_SECRET_VOLUME" >/dev/null 2>&1 \
    || fail 'production secret volume unavailable'

oci_get() {
    oci os object get --namespace "$OCI_NAMESPACE" --bucket-name "$OCI_BUCKET" \
        --auth instance_principal --name "$1" --file "$2"
}
field() {
    "$python_bin" "$script_dir/manifest.py" get --manifest "$1" --field "$2"
}
download_point() {
    local expected_type="$1" manifest_object="$2" label="$3"
    local local_manifest="$scratch_dir/$label.manifest.json"
    local local_artifact="$scratch_dir/$label.age"
    oci_get "$manifest_object" "$local_manifest" \
        || fail "unable to download $label manifest"
    "$python_bin" "$script_dir/manifest.py" validate \
        --manifest "$local_manifest" --require-verified \
        || fail "$label manifest invalid"
    [[ "$(field "$local_manifest" type)" == "$expected_type" ]] \
        || fail "$label manifest type mismatch"
    [[ "$(field "$local_manifest" release_sha)" == "$release_sha" ]] \
        || fail "$label release mismatch"
    local object_name
    object_name="$(field "$local_manifest" object_storage.object)"
    [[ "$object_name" == production/*.age && "$object_name" != *qualification* ]] \
        || fail "$label object is restore-ineligible"
    oci_get "$object_name" "$local_artifact" \
        || fail "unable to download $label artifact"
    "$script_dir/verify.sh" --manifest "$local_manifest" --artifact "$local_artifact" \
        >/dev/null || fail "$label verification failed"
    printf '%s|%s\n' "$local_manifest" "$local_artifact"
}

database_point="$(download_point database "$database_manifest" database)"
media_point="$(download_point media "$media_manifest" media)"
caddy_point="$(download_point production-caddy-state "$caddy_manifest" caddy)"
database_local_manifest="${database_point%%|*}"
database_artifact="${database_point#*|}"
media_artifact="${media_point#*|}"
caddy_artifact="${caddy_point#*|}"

restore_payload() {
    local artifact="$1" output="$2"
    age --decrypt --identity "$AGE_IDENTITY_FILE" "$artifact" \
        | zstd --decompress --stdout >"$output"
}
database_payload="$scratch_dir/database.payload"
media_payload="$scratch_dir/media.tar"
caddy_payload="$scratch_dir/caddy.tar"
restore_payload "$database_artifact" "$database_payload" \
    || fail 'database decrypt failed'
restore_payload "$media_artifact" "$media_payload" || fail 'media decrypt failed'
restore_payload "$caddy_artifact" "$caddy_payload" || fail 'Caddy-state decrypt failed'

docker volume create "$media_volume" >/dev/null
docker volume create "$caddy_volume" >/dev/null
docker volume create "$secret_volume" >/dev/null
stack_initialized=1
docker run --rm --network none -v "$PRODUCTION_SECRET_VOLUME:/source:ro" \
    -v "$secret_volume:/target" "$ARCHIVE_HELPER_IMAGE" \
    sh -ec 'cp -a /source/. /target/' \
    || fail 'isolated working-secret copy failed'
docker run --rm --network none -v "$media_volume:/target" \
    -v "$scratch_dir:/restore:ro" "$ARCHIVE_HELPER_IMAGE" \
    tar -C /target -xf /restore/media.tar \
    || fail 'isolated media restore failed'
docker run --rm --network none -v "$caddy_volume:/target" \
    -v "$scratch_dir:/restore:ro" "$ARCHIVE_HELPER_IMAGE" \
    tar -C /target -xf /restore/caddy.tar \
    || fail 'isolated Caddy-state restore failed'

"${compose[@]}" up -d db redis
ready=0
for _attempt in $(seq 1 60); do
    if "${compose[@]}" exec -T db mariadb-admin ping --silent >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 1
done
((ready == 1)) || fail 'isolated database did not become ready'
"${compose[@]}" exec -T db /bin/sh -ec \
    'MYSQL_PWD="$(cat "$MARIADB_ROOT_PASSWORD_FILE")"; export MYSQL_PWD; exec mariadb' \
    <"$database_payload" \
    || fail 'isolated database restore failed'
"${compose[@]}" up -d web racebot
"${compose[@]}" exec -T web python manage.py migrate --check \
    || fail 'restored migration set is not current'

# Leaderboard sampling uses the upstream UserRanking model.
validation_code='from pathlib import Path; from racetime.models import User,Category,Race,UserRanking; assert User.objects.exists(); assert Category.objects.filter(slug="z1rr",active=True).exists(); assert Race.objects.exists(); assert UserRanking.objects.exists(); refs=[str(v) for v in list(Category.objects.exclude(image="").values_list("image",flat=True))]; assert all((Path("/srv/racetime/media")/v).is_file() for v in refs)'
"${compose[@]}" exec -T web python manage.py shell -c "$validation_code" \
    || fail 'account/category/race/Leaderboard/media sample validation failed'

# Validate restored Caddy state and current config with networking disabled so
# this exercise cannot contact production ACME.
docker run --rm --network none -v "$caddy_volume:/data:ro" \
    --entrypoint /bin/sh "$CADDY_IMAGE" \
    -c 'find /data -type f -path "*/certificates/*" -size +0c | grep -q .' \
    || fail 'restored Caddy certificate state is empty'
docker run --rm --network none --env-file "$CADDY_ENV_FILE" \
    -v "$repo_root/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" \
    "$CADDY_IMAGE" validate --config /etc/caddy/Caddyfile \
    --adapter caddyfile || fail 'Caddy configuration validation failed'

printf 'RESTORE_TEST=PASS project=%s database_manifest=%s\n' \
    "$project" "$(basename "$database_local_manifest")"
