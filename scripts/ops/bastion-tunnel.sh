#!/usr/bin/env bash
# Open (or reuse) an OCI Bastion port-forwarding tunnel to the Raceroom
# production host, so agents can reach it the same way they reach OCI itself.
#
#   bastion-tunnel.sh            open the tunnel, reusing a live session
#   bastion-tunnel.sh --status   report whether the tunnel is usable
#   bastion-tunnel.sh --close    close the local tunnel (leaves the session)
#
# Bastion sessions expire after their TTL (3h) and cannot be renewed, so this
# creates a fresh one whenever no ACTIVE session is reusable. Nothing here is
# secret: the bastion and instance are addressed by OCID and private IP, and
# authentication is the operator's own OCI profile and SSH keys.
set -Eeuo pipefail

BASTION_OCID="${Z1RR_BASTION_OCID:-ocid1.bastion.oc1.iad.amaaaaaakiliw2aak6oxx35itnt2cybmox3x4kf5ofypsk5umjt7onluho2a}"
TARGET_IP="${Z1RR_TARGET_IP:-10.1.1.92}"
TARGET_PORT="${Z1RR_TARGET_PORT:-22}"
LOCAL_PORT="${Z1RR_LOCAL_PORT:-50162}"
OCI_PROFILE="${Z1RR_OCI_PROFILE:-API_KEY}"
SESSION_KEY="${Z1RR_SESSION_KEY:-$HOME/.ssh/z1rr-ci-deploy}"
BASTION_REGION="${Z1RR_BASTION_REGION:-us-ashburn-1}"
SESSION_TTL="${Z1RR_SESSION_TTL:-10800}"
LOG_FILE="${Z1RR_TUNNEL_LOG:-${TMPDIR:-/tmp}/z1rr-bastion-tunnel-$LOCAL_PORT.log}"
PID_FILE="${TMPDIR:-/tmp}/z1rr-bastion-tunnel-$LOCAL_PORT.pid"

port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$LOCAL_PORT") >/dev/null 2>&1
}

case "${1:-}" in
    --status)
        if port_open; then echo "TUNNEL=open port=$LOCAL_PORT"; exit 0; fi
        echo "TUNNEL=closed port=$LOCAL_PORT"; exit 1
        ;;
    --close)
        set +e
        if [[ -r "$PID_FILE" ]]; then
            kill "$(cat "$PID_FILE")" 2>/dev/null
            rm -f "$PID_FILE"
        fi
        # Git Bash pgrep/pkill cannot see Windows process command lines, so the
        # reliable fallback is whichever PID actually holds the listening port.
        if port_open; then
            owner=$(powershell.exe -NoProfile -Command                 "(Get-NetTCPConnection -LocalPort $LOCAL_PORT -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"                 2>/dev/null | tr -d '
 ')
            if [[ "$owner" =~ ^[0-9]+$ ]]; then
                taskkill //PID "$owner" //F >/dev/null 2>&1
            fi
        fi
        for _ in $(seq 1 10); do
            if ! port_open; then echo "TUNNEL=closed port=$LOCAL_PORT"; exit 0; fi
            sleep 1
        done
        echo "TUNNEL=fail still open on $LOCAL_PORT" >&2
        exit 1
        ;;
esac

if port_open; then
    echo "TUNNEL=already-open port=$LOCAL_PORT"
    exit 0
fi

# Reuse an ACTIVE session for this target before minting another one.
session_id="$(oci --profile "$OCI_PROFILE" bastion session list \
    --bastion-id "$BASTION_OCID" --session-lifecycle-state ACTIVE --output json 2>/dev/null \
    | tr -d '\r' \
    | grep -oE '"id": "ocid1\.bastionsession[^"]+"' \
    | head -1 | cut -d'"' -f4 || true)"

if [[ -z "$session_id" ]]; then
    echo "creating bastion session..."
    oci --profile "$OCI_PROFILE" bastion session create-port-forwarding \
        --bastion-id "$BASTION_OCID" \
        --display-name "z1rr-agent-$(date -u +%Y%m%dT%H%M%SZ)" \
        --ssh-public-key-file "$SESSION_KEY.pub" \
        --target-private-ip "$TARGET_IP" \
        --target-port "$TARGET_PORT" \
        --session-ttl "$SESSION_TTL" \
        --wait-for-state SUCCEEDED >/dev/null 2>&1 || true
    session_id="$(oci --profile "$OCI_PROFILE" bastion session list \
        --bastion-id "$BASTION_OCID" --session-lifecycle-state ACTIVE --output json 2>/dev/null \
        | tr -d '\r' \
        | grep -oE '"id": "ocid1\.bastionsession[^"]+"' \
        | head -1 | cut -d'"' -f4 || true)"
fi

[[ -n "$session_id" ]] || { echo "TUNNEL=fail no ACTIVE bastion session" >&2; exit 1; }

nohup ssh -i "$SESSION_KEY" -N \
    -L "$LOCAL_PORT:$TARGET_IP:$TARGET_PORT" -p 22 \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
    -o StrictHostKeyChecking=accept-new \
    "$session_id@host.bastion.$BASTION_REGION.oci.oraclecloud.com" \
    >"$LOG_FILE" 2>&1 &
tunnel_pid=$!
printf '%s
' "$tunnel_pid" >"$PID_FILE"
disown || true

for _ in $(seq 1 30); do
    if port_open; then
        echo "TUNNEL=open port=$LOCAL_PORT session=${session_id:0:40}..."
        exit 0
    fi
    sleep 1
done

echo "TUNNEL=fail port $LOCAL_PORT never opened; see $LOG_FILE" >&2
exit 1
