#!/bin/bash
# stop.sh — network_agent stop (macOS / Linux)
#
# Stops the backend (port 8010) and frontend (port 5173) processes.
#
# Usage:
#   chmod +x stop.sh     (first time only)
#   ./stop.sh            Stop all network_agent services

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

echo ""
echo " ========================================"
echo "   Stopping network_agent ..."
echo " ========================================"
echo ""

STOPPED=0

# Try PID files first
if [ -f "$ROOT/.backend.pid" ]; then
    PID=$(cat "$ROOT/.backend.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        echo " [backend]  Stopped (PID $PID)"
        STOPPED=1
    fi
    rm -f "$ROOT/.backend.pid"
fi

if [ -f "$ROOT/.frontend.pid" ]; then
    PID=$(cat "$ROOT/.frontend.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        echo " [frontend] Stopped (PID $PID)"
        STOPPED=1
    fi
    rm -f "$ROOT/.frontend.pid"
fi

# Fallback: kill anything still listening on our ports
if command -v lsof &>/dev/null; then
    for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
        pids=$(lsof -ti ":$port" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "$pids" | xargs kill -9 2>/dev/null
            echo " [port $port] Force-stopped remaining processes"
            STOPPED=1
        fi
    done
fi

if [ "$STOPPED" = "0" ]; then
    echo " No running services found."
fi

echo ""
echo " ========================================"
echo "   Done."
echo " ========================================"
echo ""
