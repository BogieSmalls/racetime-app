#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

fail() {
    printf 'BACKUP=FAIL %s\n' "$1" >&2
    exit 1
}

backup_type=''
release_sha=''
reason=''
pinned_until=''
while (($#)); do
    case "$1" in
        --type) backup_type="$2"; shift 2 ;;
        --release-sha) release_sha="$2"; shift 2 ;;
        --reason) reason="$2"; shift 2 ;;
        --pinned-until) pinned_until="$2"; shift 2 ;;
        *) fail 'invalid argument' ;;
    esac
done
[[ "$backup_type" == 'database' || "$backup_type" == 'media' \
    || "$backup_type" == 'production-caddy-state' ]] \
    || fail 'invalid backup type'
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid release SHA'
if [[ "$backup_type" == 'production-caddy-state' ]]; then
    [[ "$reason" == 'initial-issuance' || "$reason" == 'renewal' \
        || "$reason" == 'material-change' ]] \
        || fail 'Caddy backup requires initial-issuance, renewal, or material-change reason'
else
    reason="${reason:-scheduled}"
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON_BIN:-python3}"
config="${Z1RR_BACKUP_CONFIG:-/etc/z1rr-racetime/backup.env}"
[[ -r "$config" ]] || fail 'root-owned backup configuration is required'
[[ "$(stat -c '%u' "$config")" == '0' ]] \
    || fail 'root-owned backup configuration is required'
# shellcheck disable=SC1090
source "$config"
: "${OCI_NAMESPACE:?missing OCI_NAMESPACE}"
: "${OCI_BUCKET:?missing OCI_BUCKET}"
: "${OCI_PREFIX:?missing OCI_PREFIX}"
: "${AGE_RECIPIENT:?missing AGE_RECIPIENT}"
: "${AGE_IDENTITY_FILE:?missing AGE_IDENTITY_FILE}"
: "${AGE_KEY_ID:?missing AGE_KEY_ID}"
: "${BACKUP_SCRATCH_ROOT:?missing BACKUP_SCRATCH_ROOT}"
: "${BACKUP_STATUS_DIR:?missing BACKUP_STATUS_DIR}"
: "${RACETIME_COMPOSE_FILE:?missing RACETIME_COMPOSE_FILE}"
: "${PRODUCTION_MEDIA_VOLUME:?missing PRODUCTION_MEDIA_VOLUME}"
: "${PRODUCTION_CADDY_STATE_VOLUME:?missing PRODUCTION_CADDY_STATE_VOLUME}"
: "${MARIADB_VERIFY_IMAGE:?missing MARIADB_VERIFY_IMAGE}"
: "${ARCHIVE_HELPER_IMAGE:?missing ARCHIVE_HELPER_IMAGE}"
: "${DB_SCHEMA_NAME:?missing DB_SCHEMA_NAME}"
[[ "$OCI_PREFIX" == 'production' ]] || fail 'only production backup prefix is eligible'
[[ -r "$AGE_IDENTITY_FILE" ]] || fail 'age identity unavailable'
[[ "$ARCHIVE_HELPER_IMAGE" == *@sha256:* ]] \
    || fail 'archive helper image must be immutable'

for command_name in docker age zstd oci sha256sum wc tar df stat mktemp date \
    "$python_bin"; do
    command -v "$command_name" >/dev/null 2>&1 \
        || fail "required command unavailable: $command_name"
done

scratch_root="${BACKUP_SCRATCH_ROOT%/}"
status_dir="${BACKUP_STATUS_DIR%/}"
[[ "$scratch_root" == /* && "$scratch_root" != '/' && -d "$scratch_root" ]] \
    || fail 'unsafe scratch root'
[[ "$status_dir" == /* && "$status_dir" != '/' && -d "$status_dir" ]] \
    || fail 'unsafe status directory'
minimum_free_kb="${MIN_BACKUP_FREE_KB:-5242880}"
[[ "$minimum_free_kb" =~ ^[0-9]+$ ]] || fail 'invalid disk threshold'
free_kb="$(df -Pk "$scratch_root" | awk 'NR == 2 {print $4}')"
[[ "$free_kb" =~ ^[0-9]+$ ]] || fail 'disk probe failed'
((free_kb >= minimum_free_kb)) || fail 'insufficient disk headroom'

scratch_dir="$(mktemp -d "$scratch_root/z1rr-backup.XXXXXX")"
remote_pending_data=''
remote_final_data=''
remote_pending_manifest=''
data_promoted=0
manifest_promoted=0
remote_complete=0

oci_delete() {
    oci os object delete --namespace "$OCI_NAMESPACE" --bucket-name "$OCI_BUCKET" \
        --auth instance_principal --force --name "$1"
}
cleanup() {
    set +e
    if ((remote_complete == 0)); then
        [[ -n "$remote_pending_data" ]] && oci_delete "$remote_pending_data" >/dev/null 2>&1
        [[ -n "$remote_pending_manifest" ]] && oci_delete "$remote_pending_manifest" >/dev/null 2>&1
        ((manifest_promoted == 1)) && oci_delete "$remote_final_manifest" >/dev/null 2>&1
        ((data_promoted == 1)) && oci_delete "$remote_final_data" >/dev/null 2>&1
    fi
    case "$scratch_dir" in
        "$scratch_root"/z1rr-backup.*) rm -rf -- "$scratch_dir" ;;
    esac
}
trap cleanup EXIT

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_id="$timestamp-${release_sha:0:12}-$RANDOM$RANDOM"
payload="$scratch_dir/source.payload"
migrations_file="$scratch_dir/migrations.txt"
source_volume=''
source_entries=0

compose=(docker compose -f "$RACETIME_COMPOSE_FILE")
if [[ "$backup_type" == 'database' ]]; then
    source_volume="${PRODUCTION_DB_VOLUME:-z1rr-racetime-production-db}"
    [[ "$source_volume" != *qualification* ]] || fail 'qualification database is ineligible'
    [[ "$DB_SCHEMA_NAME" =~ ^[A-Za-z0-9_]{1,64}$ ]] \
        || fail 'database schema name is unsafe'
    "${compose[@]}" exec -T db /bin/sh -ec \
        'MYSQL_PWD="$(cat "$MARIADB_ROOT_PASSWORD_FILE")"; export MYSQL_PWD; exec mariadb-dump --single-transaction --routines --events --triggers --hex-blob --databases "$1"' \
        backup-dump "$DB_SCHEMA_NAME" >"$payload" \
        || fail 'database export failed'
    # compose exec bypasses the image ENTRYPOINT, so production secrets are
    # never exported and Django dies on DJANGO_SECRET_KEY. Invoke the
    # entrypoint explicitly in maintenance mode to load them first.
    "${compose[@]}" exec -T web /srv/racetime/.docker/start-production maintenance python manage.py showmigrations --plan >"$migrations_file" || fail 'migration inventory failed'
    source_entries="$(awk '/^CREATE TABLE / {count++} END {print count+0}' "$payload")"
else
    if [[ "$backup_type" == 'media' ]]; then
        source_volume="$PRODUCTION_MEDIA_VOLUME"
    else
        source_volume="$PRODUCTION_CADDY_STATE_VOLUME"
    fi
    [[ "$source_volume" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] \
        || fail 'unsafe source volume'
    [[ "$source_volume" != *qualification* ]] \
        || fail 'qualification volume is ineligible'
    docker volume inspect "$source_volume" >/dev/null 2>&1 \
        || fail 'source volume unavailable'
    docker run --rm --network none --read-only \
        -v "$source_volume:/source:ro" "$ARCHIVE_HELPER_IMAGE" \
        tar --numeric-owner -C /source -cf - . >"$payload" \
        || fail 'volume snapshot failed'
    listing="$scratch_dir/source.list"
    tar -tf "$payload" >"$listing" || fail 'volume snapshot is not a valid archive'
    if awk 'BEGIN { bad=0 } /^\// { bad=1 } /(^|\/)\.\.($|\/)/ { bad=1 } END { exit bad ? 0 : 1 }' "$listing"; then
        fail 'volume snapshot contains unsafe paths'
    fi
    source_entries="$(wc -l <"$listing" | tr -d ' ')"
fi

source_bytes="$(wc -c <"$payload" | tr -d ' ')"
((source_bytes > 0 && source_entries > 0)) || fail 'source backup is empty'
plaintext_sha="$(sha256sum "$payload" | awk '{print $1}')"
compressed="$scratch_dir/source.zst"
encrypted="$scratch_dir/source.zst.age"
zstd --threads=1 --ultra -19 --stdout "$payload" >"$compressed" \
    || fail 'compression failed'
age --recipient "$AGE_RECIPIENT" --output "$encrypted" "$compressed" \
    || fail 'encryption failed'
encrypted_sha="$(sha256sum "$encrypted" | awk '{print $1}')"
encrypted_bytes="$(wc -c <"$encrypted" | tr -d ' ')"
((encrypted_bytes > 0)) || fail 'encrypted artifact is empty'

remote_final_data="$OCI_PREFIX/$backup_type/$run_id.age"
remote_final_manifest="$OCI_PREFIX/$backup_type/$run_id.manifest.json"
remote_pending_data="$remote_final_data.pending-$RANDOM"
remote_pending_manifest="$remote_final_manifest.pending-$RANDOM"
manifest="$scratch_dir/manifest.json"
completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

tool_version() {
    "$@" --version 2>&1 | head -n 1 | tr '\r\n' ' '
}
manifest_args=(
    create
    --type "$backup_type"
    --started-at "$started_at"
    --completed-at "$completed_at"
    --release-sha "$release_sha"
    --source-volume "$source_volume"
    --generation "$run_id"
    --source-bytes "$source_bytes"
    --source-entries "$source_entries"
    --plaintext-sha "$plaintext_sha"
    --plaintext-bytes "$source_bytes"
    --encrypted-sha "$encrypted_sha"
    --encrypted-bytes "$encrypted_bytes"
    --recipient "$AGE_RECIPIENT"
    --key-id "$AGE_KEY_ID"
    --namespace "$OCI_NAMESPACE"
    --bucket "$OCI_BUCKET"
    --object "$remote_final_data"
    --manifest-object "$remote_final_manifest"
    --reason "$reason"
    --tool "age=$(tool_version age)"
    --tool "zstd=$(tool_version zstd)"
    --tool "oci=$(tool_version oci)"
    --tool "docker=$(tool_version docker)"
    --output "$manifest"
)
if [[ "$backup_type" == 'database' ]]; then
    manifest_args+=(--db-schema "$DB_SCHEMA_NAME" --migrations-file "$migrations_file")
fi
[[ -n "$pinned_until" ]] && manifest_args+=(--pinned-until "$pinned_until")
"$python_bin" "$script_dir/manifest.py" "${manifest_args[@]}" \
    || fail 'manifest creation failed'

if ! verified_at="$("$script_dir/verify.sh" --manifest "$manifest" \
    --artifact "$encrypted" --allow-pending --emit-timestamp)"; then
    fail 'verification failed'
fi
"$python_bin" "$script_dir/manifest.py" mark-verified \
    --manifest "$manifest" --verified-at "$verified_at" \
    || fail 'verification record failed'
"$python_bin" "$script_dir/manifest.py" validate \
    --manifest "$manifest" --require-verified \
    || fail 'final manifest validation failed'
manifest_sha="$(sha256sum "$manifest" | awk '{print $1}')"
manifest_bytes="$(wc -c <"$manifest" | tr -d ' ')"

oci_put() {
    local object_name="$1" file_path="$2" sha="$3"
    oci os object put --namespace "$OCI_NAMESPACE" --bucket-name "$OCI_BUCKET" \
        --auth instance_principal --no-overwrite --name "$object_name" \
        --file "$file_path" --metadata "{\"z1rr-sha256\":\"$sha\"}"
}
oci_head_size() {
    oci os object head --namespace "$OCI_NAMESPACE" --bucket-name "$OCI_BUCKET" \
        --auth instance_principal --name "$1" --query '"content-length"' --raw-output
}
oci_head_sha() {
    oci os object head --namespace "$OCI_NAMESPACE" --bucket-name "$OCI_BUCKET" \
        --auth instance_principal --name "$1" --query '"opc-meta-z1rr-sha256"' --raw-output
}
oci_rename() {
    oci os object rename --namespace "$OCI_NAMESPACE" --bucket-name "$OCI_BUCKET" \
        --auth instance_principal --source-name "$1" --new-name "$2"
}
remote_check() {
    local object_name="$1" expected_size="$2" expected_sha="$3"
    [[ "$(oci_head_size "$object_name")" == "$expected_size" \
        && "$(oci_head_sha "$object_name")" == "$expected_sha" ]]
}

oci_put "$remote_pending_data" "$encrypted" "$encrypted_sha" \
    || fail 'Object Storage artifact upload failed'
remote_check "$remote_pending_data" "$encrypted_bytes" "$encrypted_sha" \
    || fail 'Object Storage artifact verification failed'
oci_rename "$remote_pending_data" "$remote_final_data" \
    || fail 'Object Storage artifact promotion failed'
remote_pending_data=''
data_promoted=1
remote_check "$remote_final_data" "$encrypted_bytes" "$encrypted_sha" \
    || fail 'Object Storage promoted artifact verification failed'

oci_put "$remote_pending_manifest" "$manifest" "$manifest_sha" \
    || fail 'Object Storage manifest upload failed'
remote_check "$remote_pending_manifest" "$manifest_bytes" "$manifest_sha" \
    || fail 'Object Storage manifest verification failed'
oci_rename "$remote_pending_manifest" "$remote_final_manifest" \
    || fail 'Object Storage completion marker promotion failed'
remote_pending_manifest=''
manifest_promoted=1
remote_check "$remote_final_manifest" "$manifest_bytes" "$manifest_sha" \
    || fail 'Object Storage completion marker verification failed'
remote_complete=1

status_target="$status_dir/last-$backup_type.json"
status_temporary="$status_target.tmp-$$"
cp "$manifest" "$status_temporary"
mv -f "$status_temporary" "$status_target"
printf 'BACKUP=PASS type=%s object=%s manifest=%s\n' \
    "$backup_type" "$remote_final_data" "$remote_final_manifest"
