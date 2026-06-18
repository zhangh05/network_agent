#!/usr/bin/env bash
# Start Network Agent on macOS/Linux.

set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
INSTALL_DEPS="${INSTALL_DEPS:-auto}"
LOG_DIR="$ROOT/workspace/logs"
BACKEND_PID_FILE="$ROOT/.backend.pid"
FRONTEND_PID_FILE="$ROOT/.frontend.pid"
BACKEND_STARTED=0
FRONTEND_STARTED=0

log() {
    printf '%s\n' "$*"
}

fail() {
    log "[ERROR] $*"
    exit 1
}

check_version() {
    command -v python3 >/dev/null 2>&1 || fail "Python 3.12+ is required."
    python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' \
        || fail "Python 3.12+ is required; found $(python3 --version 2>&1)."

    command -v node >/dev/null 2>&1 || fail "Node.js 18+ is required."
    node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 18 ? 0 : 1)' \
        || fail "Node.js 18+ is required; found $(node --version 2>&1)."
    command -v npm >/dev/null 2>&1 || fail "npm is required."
    command -v curl >/dev/null 2>&1 || fail "curl is required."
    command -v lsof >/dev/null 2>&1 || fail "lsof is required."
}

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

adopt_existing_service() {
    role="$1"
    port="$2"
    pid_file="$3"
    pid="$(port_pid "$port")"
    [ -n "$pid" ] || return 1

    if process_belongs_to_project "$pid" "$role"; then
        printf '%s\n' "$pid" > "$pid_file"
        log "[$role] Already running on port $port (PID $pid)."
        return 0
    fi
    fail "Port $port is occupied by another process (PID $pid)."
}

wait_for_url() {
    role="$1"
    pid="$2"
    url="$3"
    attempts="${4:-30}"
    i=1
    while [ "$i" -le "$attempts" ]; do
        kill -0 "$pid" 2>/dev/null || return 1
        if curl --fail --silent --show-error --max-time 2 "$url" >/dev/null 2>&1; then
            log "[$role] Ready."
            return 0
        fi
        sleep 1
        i=$((i + 1))
    done
    return 1
}

terminate_owned_pid() {
    pid="$1"
    role="$2"
    if process_belongs_to_project "$pid" "$role"; then
        kill "$pid" 2>/dev/null || true
    fi
}

stop_started_services() {
    if [ "$FRONTEND_STARTED" = "1" ] && [ -f "$FRONTEND_PID_FILE" ]; then
        terminate_owned_pid "$(cat "$FRONTEND_PID_FILE")" frontend
        rm -f "$FRONTEND_PID_FILE"
    fi
    if [ "$BACKEND_STARTED" = "1" ] && [ -f "$BACKEND_PID_FILE" ]; then
        terminate_owned_pid "$(cat "$BACKEND_PID_FILE")" backend
        rm -f "$BACKEND_PID_FILE"
    fi
}

install_dependencies() {
    if [ "$INSTALL_DEPS" = "0" ] || [ "$INSTALL_DEPS" = "false" ]; then
        log "[deps] Skipped (INSTALL_DEPS=$INSTALL_DEPS)."
        return
    fi

    log "[deps] Checking Python dependencies..."
    if ! python3 -c 'import flask, flask_sock, yaml, langgraph, bs4, lxml, pdfplumber, scapy' >/dev/null 2>&1; then
        python3 -m pip install -r "$ROOT/requirements.txt"
    fi
    python3 -m pip check >/dev/null || fail "Python dependency check failed."

    log "[deps] Checking frontend dependencies..."
    if [ ! -x "$ROOT/frontend/node_modules/.bin/vite" ]; then
        (cd "$ROOT/frontend" && npm install)
    fi
}

start_backend() {
    if adopt_existing_service backend "$BACKEND_PORT" "$BACKEND_PID_FILE"; then
        return
    fi

    log "[backend] Starting on port $BACKEND_PORT..."
    cd "$ROOT"
    nohup python3 backend/main.py --host 0.0.0.0 --port "$BACKEND_PORT" \
        >"$LOG_DIR/backend.log" 2>&1 </dev/null &
    pid=$!
    printf '%s\n' "$pid" > "$BACKEND_PID_FILE"
    BACKEND_STARTED=1
    if ! wait_for_url backend "$pid" "http://127.0.0.1:$BACKEND_PORT/api/health"; then
        stop_started_services
        fail "Backend failed to start. See $LOG_DIR/backend.log"
    fi
}

start_frontend() {
    if adopt_existing_service frontend "$FRONTEND_PORT" "$FRONTEND_PID_FILE"; then
        return
    fi

    log "[frontend] Starting on port $FRONTEND_PORT..."
    cd "$ROOT/frontend"
    nohup "$ROOT/frontend/node_modules/.bin/vite" --host 0.0.0.0 --port "$FRONTEND_PORT" \
        >"$LOG_DIR/frontend.log" 2>&1 </dev/null &
    pid=$!
    printf '%s\n' "$pid" > "$FRONTEND_PID_FILE"
    FRONTEND_STARTED=1
    if ! wait_for_url frontend "$pid" "http://127.0.0.1:$FRONTEND_PORT"; then
        stop_started_services
        fail "Frontend failed to start. See $LOG_DIR/frontend.log"
    fi
}

main() {
    log "Network Agent"
    log "Checking Python 3.12+ and Node.js 18+..."
    check_version
    install_dependencies
    mkdir -p "$LOG_DIR"
    start_backend
    start_frontend
    log ""
    log "Backend:  http://localhost:$BACKEND_PORT"
    log "Frontend: http://localhost:$FRONTEND_PORT"
    log "Stop with: ./stop.sh"
}

main "$@"
