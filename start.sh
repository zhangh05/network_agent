#!/bin/bash
# start.sh — network_agent auto setup & start (macOS / Linux)
#
# What this script does:
#   1. Check if Python 3.10+ is installed
#   2. Check if Node.js 18+ is installed
#   3. Install Python dependencies (pip install -r requirements.txt)
#   4. Install frontend dependencies (npm install)
#   5. Start backend on port 8010
#   6. Start frontend on port 5173
#
# Usage:
#   chmod +x start.sh    (first time only)
#   ./start.sh           Start everything (first run will install deps)
#   ./stop.sh            Stop everything
#
# Environment variables:
#   BACKEND_PORT         Override backend port (default 8010)
#   FRONTEND_PORT        Override frontend port (default 5173)

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

echo ""
echo " ========================================"
echo "   network_agent v2.3.1"
echo "   Auto Setup & Start"
echo " ========================================"
echo ""

# ── 1. Python ──
echo " [1/4] Checking Python 3.10+ ..."
if ! command -v python3 &>/dev/null; then
    echo ""
    echo " [ERROR] Python is not installed or not in PATH."
    echo "         Please install Python 3.10+ from:"
    echo "         https://www.python.org/downloads/"
    echo ""
    exit 1
fi
echo "        OK — $(python3 --version)"

# ── 2. Node.js ──
echo " [2/4] Checking Node.js 18+ ..."
if ! command -v node &>/dev/null; then
    echo ""
    echo " [ERROR] Node.js is not installed or not in PATH."
    echo "         Please install Node.js 18+ from:"
    echo "         https://nodejs.org/"
    echo ""
    exit 1
fi
echo "        OK — $(node --version)"

# ── 3. Python deps ──
echo " [3/4] Installing Python dependencies (Tsinghua mirror) ..."
cd "$ROOT"

# Skip if already installed
if python3 -c "import flask" 2>/dev/null; then
    echo "        Already installed — skipping."
else
    echo "        Downloading packages (may take 1-3 minutes) ..."
    python3 -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple || {
        echo ""
        echo " [ERROR] Failed to install Python packages."
        echo "         Please check your network and try again."
        echo "         If the mirror is unreachable, run manually:"
        echo "           pip install -r requirements.txt"
        echo ""
        exit 1
    }
    echo "        OK"
fi

# ── 4. Frontend deps ──
echo " [4/4] Installing frontend dependencies (taobao mirror) ..."
cd "$ROOT/frontend"
if [ ! -d "node_modules" ]; then
    echo "        First run — downloading packages (may take 2-5 minutes) ..."
    npm install --registry=https://registry.npmmirror.com || {
        echo ""
        echo " [ERROR] npm install failed."
        echo "         Please check your network and try again."
        echo "         If the mirror is unreachable, run manually:"
        echo "           cd frontend && npm install"
        echo ""
        exit 1
    }
else
    echo "        Already installed — skipping."
fi
echo "        OK"

# ── Start services ──
echo ""
echo " ========================================"
echo "   Starting services ..."
echo " ========================================"
echo ""

# Backend
cd "$ROOT"
mkdir -p workspace/logs
python3 backend/main.py --host 0.0.0.0 --port "$BACKEND_PORT" &>"$ROOT/workspace/logs/backend.log" &
BACKEND_PID=$!
echo " [backend]  Starting on port $BACKEND_PORT (PID $BACKEND_PID) ..."

echo -n " [backend]  Waiting for health check "
for i in $(seq 1 30); do
    sleep 1
    if curl -s "http://localhost:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
        echo ""
        echo " [backend]  Ready"
        break
    fi
    echo -n "."
done
[ "$i" = "30" ] && echo "" && echo " [backend]  Started (health check timed out — may still be loading)"

# Frontend
cd "$ROOT/frontend"
npx vite --host 0.0.0.0 --port "$FRONTEND_PORT" &>"$ROOT/workspace/logs/frontend.log" &
FRONTEND_PID=$!
echo " [frontend] Starting on port $FRONTEND_PORT (PID $FRONTEND_PID) ..."

echo -n " [frontend] Waiting for server "
for i in $(seq 1 30); do
    sleep 1
    if curl -s "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1; then
        echo ""
        echo " [frontend] Ready"
        break
    fi
    echo -n "."
done
[ "$i" = "30" ] && echo "" && echo " [frontend] Started (server check timed out — may still be building)"

# ── Write PID file ──
echo "$BACKEND_PID" > "$ROOT/.backend.pid"
echo "$FRONTEND_PID" > "$ROOT/.frontend.pid"

echo ""
echo " ========================================"
echo "   All services are running!"
echo ""
echo "   Backend   http://localhost:$BACKEND_PORT"
echo "   Frontend  http://localhost:$FRONTEND_PORT"
echo ""
echo "   To stop:  ./stop.sh"
echo "   Logs:     workspace/logs/"
echo " ========================================"
echo ""
