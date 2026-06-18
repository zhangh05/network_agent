#!/usr/bin/env bash
# Stop Network Agent processes on macOS/Linux.

set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PID_FILE="$ROOT/.backend.pid"
FRONTEND_PID_FILE="$ROOT/.frontend.pid"

process_cwd() {
    lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
}

process_belongs_to_project() {
    pid="$1"
    role="$2"
    kill -0 "$pid" 2>/dev/null || return 1
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    cwd="$(process_cwd "$pid")"

    case "$role" in
        backend)
            printf '%s' "$command_line" | grep -q 'backend/main.py' || return 1
            [ "$cwd" = "$ROOT" ]
            ;;
        frontend)
            printf '%s' "$command_line" | grep -Eq 'vite|npm run dev' || return 1
            [ "$cwd" = "$ROOT/frontend" ]
            ;;
        *)
            return 1
            ;;
    esac
}

port_pid() {
    lsof -nP -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -n 1
}

wait_until_stopped() {
    pid="$1"
    i=1
    while [ "$i" -le 10 ]; do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 1
        i=$((i + 1))
    done
    return 1
}

stop_service() {
    role="$1"
    port="$2"
    pid_file="$3"
    pid=""

    if [ -f "$pid_file" ]; then
        pid="$(cat "$pid_file" 2>/dev/null || true)"
    fi
    if [ -z "$pid" ] || ! process_belongs_to_project "$pid" "$role"; then
        pid="$(port_pid "$port")"
    fi

    if [ -z "$pid" ]; then
        printf '[%s] Not running.\n' "$role"
        rm -f "$pid_file"
        return
    fi
    if ! process_belongs_to_project "$pid" "$role"; then
        printf '[%s] Refusing to stop unverified process on port %s (PID %s).\n' "$role" "$port" "$pid" >&2
        rm -f "$pid_file"
        return 1
    fi

    kill "$pid"
    if ! wait_until_stopped "$pid"; then
        if process_belongs_to_project "$pid" "$role"; then
            kill -KILL "$pid"
        fi
    fi
    rm -f "$pid_file"
    printf '[%s] Stopped (PID %s).\n' "$role" "$pid"
}

status=0
stop_service frontend "$FRONTEND_PORT" "$FRONTEND_PID_FILE" || status=1
stop_service backend "$BACKEND_PORT" "$BACKEND_PID_FILE" || status=1
exit "$status"
