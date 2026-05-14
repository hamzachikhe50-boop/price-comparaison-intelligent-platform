#!/bin/bash
# ════════════════════════════════════════════════════════════════
#  start_local.sh — Lance les 3 microservices avec uvicorn
#  Compatible Windows (Git Bash / WSL) + Linux + Mac
#
#  Usage :
#    bash start_local.sh          -> demarrer
#    bash start_local.sh stop     -> arreter
# ════════════════════════════════════════════════════════════════

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/.pids"
mkdir -p "$ROOT_DIR/logs"

# ── Arrêt ──────────────────────────────────────────────────────
if [ "$1" == "stop" ]; then
    if [ -f "$PID_FILE" ]; then
        echo "Arret des services..."
        while read pid; do
            kill "$pid" 2>/dev/null && echo "   Arrete PID $pid"
        done < "$PID_FILE"
        rm "$PID_FILE"
        echo "Tous les services arretes"
    else
        echo "Aucun service en cours"
    fi
    exit 0
fi

echo "========================================================"
echo "  Tunisia Price Hunter — Demarrage des 3 services"
echo "========================================================"
echo ""

> "$PID_FILE"

# ── Service 1 – Scraping (8001) ────────────────────────────────
echo "[1/3] Service 1 - Scraping       -> http://localhost:8001"
cd "$ROOT_DIR/service1-scraping"
uvicorn app.main:app --host 0.0.0.0 --port 8001 --log-level info >> "$ROOT_DIR/logs/service1.log" 2>&1 &
echo $! >> "$PID_FILE"
sleep 2

# ── Service 2 – Price History (8002) ──────────────────────────
echo "[2/3] Service 2 - Price History  -> http://localhost:8002"
cd "$ROOT_DIR/service2-price"
uvicorn app.main:app --host 0.0.0.0 --port 8002 --log-level info >> "$ROOT_DIR/logs/service2.log" 2>&1 &
echo $! >> "$PID_FILE"
sleep 2

# ── Service 3 – Alertes (8003) ────────────────────────────────
echo "[3/3] Service 3 - Alertes        -> http://localhost:8003"
cd "$ROOT_DIR/service3-alerts"
uvicorn app.main:app --host 0.0.0.0 --port 8003 --log-level info >> "$ROOT_DIR/logs/service3.log" 2>&1 &
echo $! >> "$PID_FILE"

cd "$ROOT_DIR"
echo ""
echo "========================================================"
echo "Les 3 services tournent en arriere-plan"
echo ""
echo "  Swagger UI :"
echo "    http://localhost:8001/docs  (Scraping)"
echo "    http://localhost:8002/docs  (Price History)"
echo "    http://localhost:8003/docs  (Alertes)"
echo ""
echo "  Diagnostic DB :"
echo "    http://localhost:8002/      (verifie connexion DB)"
echo "    http://localhost:8003/      (verifie connexion DB)"
echo ""
echo "  Logs en direct :"
echo "    tail -f logs/service1.log"
echo "    tail -f logs/service2.log"
echo "    tail -f logs/service3.log"
echo ""
echo "  Pour arreter : bash start_local.sh stop"
echo "========================================================"
