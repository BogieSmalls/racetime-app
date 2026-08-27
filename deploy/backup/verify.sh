#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

fail() {
    printf 'VERIFY=FAIL %s\n' "$1" >&2
    exit 1
}

manifest=''
artifact=''
allow_pending=0
emit_timestamp=0
while (($#)); do
    case "$1" in
        --manifest) manifest="$2"; shift 2 ;;
        --artifact) artifact="$2"; shift 2 ;;
        --allow-pending) allow_pending=1; shift ;;
        --emit-timestamp) emit_timestamp=1; shift ;;
        *) fail 'invalid argument' ;;
    esac
done
[[ -r "$manifest" && -s "$artifact" ]] || fail 'manifest and artifact are required'

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON_BIN:-python3}"
config="${Z1RR_BACKUP_CONFIG:-/etc/z1rr-racetime/backup.env}"
[[ -r "$config" ]] || fail 'root-owned backup configuration is required'
[[ "$(stat -c '%u' "$config")" == '0' ]] \
    || fail 'root-owned backup configuration is required'
# shellcheck disable=SC1090
source "$config"
: "${AGE_IDENTITY_FILE:?missing AGE_IDENTITY_FILE}"
: "${BACKUP_SCRATCH_ROOT:?missing BACKUP_SCRATCH_ROOT}"
: "${MARIADB_VERIFY_IMAGE:?missing MARIADB_VERIFY_IMAGE}"

for command_name in "$python_bin" age zstd sha256sum docker tar mktemp stat; do
    command -v "$command_name" >/dev/null 2>&1 \
        || fail "required command unavailable: $command_name"
done

validation=(validate --manifest "$manifest")
((allow_pending == 1)) || validation+=(--require-verified)
"$python_bin" "$script_dir/manifest.py" "${validation[@]}" \
    || fail 'manifest validation failed'
field() {
    "$python_bin" "$script_dir/manifest.py" get --manifest "$manifest" --field "$1"
}
backup_type="$(field type)"
expected_encrypted_sha="$(field encrypted.sha256)"
expected_plaintext_sha="$(field plaintext.sha256)"
actual_encrypted_sha="$(sha256sum "$artifact" | awk '{print $1}')"
[[ "$actual_encrypted_sha" == "$expected_encrypted_sha" ]] \
    || fail 'encrypted hash mismatch'

scratch_root="${BACKUP_SCRATCH_ROOT%/}"
[[ "$scratch_root" == /* && "$scratch_root" != '/' && -d "$scratch_root" ]] \
    || fail 'unsafe scratch root'
scratch_dir="$(mktemp -d "$scratch_root/z1rr-verify.XXXXXX")"
verifier_name=''
cleanup() {
    set +e
    if [[ -n "$verifier_name" ]]; then
        docker rm -f "$verifier_name" >/dev/null 2>&1
    fi
    case "$scratch_dir" in
        "$scratch_root"/z1rr-verify.*) rm -rf -- "$scratch_dir" ;;
    esac
}
trap cleanup EXIT
restored="$scratch_dir/restored.payload"
if ! age --decrypt --identity "$AGE_IDENTITY_FILE" "$artifact" \
    | zstd --decompress --stdout >"$restored"; then
    fail 'decrypt or decompress failed'
fi
actual_plaintext_sha="$(sha256sum "$restored" | awk '{print $1}')"
[[ "$actual_plaintext_sha" == "$expected_plaintext_sha" ]] \
    || fail 'plaintext hash mismatch'

if [[ "$backup_type" == 'database' ]]; then
    [[ "$MARIADB_VERIFY_IMAGE" == *@sha256:* ]] \
        || fail 'MariaDB verifier image must be immutable'
    verifier_name="z1rr-backup-verify-$$-$RANDOM"
    docker run --detach --rm --name "$verifier_name" --network none \
        --tmpfs /var/lib/mysql:rw,noexec,nosuid,size=1024m \
        -e MARIADB_ALLOW_EMPTY_ROOT_PASSWORD=1 "$MARIADB_VERIFY_IMAGE" >/dev/null \
        || fail 'disposable MariaDB failed to start'
    ready=0
    for _attempt in $(seq 1 90); do
        # The MariaDB entrypoint runs a TEMPORARY server on the same socket
        # during initialisation; it answers ping, then shuts down and takes
        # the socket with it. Gate on the init-complete marker so the restore
        # cannot race that shutdown.
        if docker logs "$verifier_name" 2>&1 | grep -q 'init process done' && docker exec "$verifier_name" healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1; then
            ready=1
            break
        fi
        sleep 1
    done
    ((ready == 1)) || fail 'disposable MariaDB did not become ready'
    docker exec -i "$verifier_name" mariadb <"$restored" \
        || fail 'database dump integrity restore failed'
    docker exec "$verifier_name" mariadb --batch --skip-column-names \
        -e 'SELECT 1' >/dev/null \
        || fail 'database integrity query failed'
else
    listing="$scratch_dir/archive.list"
    tar -tf "$restored" >"$listing" || fail 'archive listing failed'
    [[ -s "$listing" ]] || fail 'archive is empty'
    if awk 'BEGIN { bad=0 } /^\// { bad=1 } /(^|\/)\.\.($|\/)/ { bad=1 } END { exit bad ? 0 : 1 }' "$listing"; then
        fail 'archive contains unsafe paths'
    fi
fi

verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if ((emit_timestamp == 1)); then
    printf '%s\n' "$verified_at"
else
    printf 'VERIFY=PASS type=%s verified_at=%s\n' "$backup_type" "$verified_at"
fi
