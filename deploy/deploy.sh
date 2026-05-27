#!/usr/bin/env bash
# ─── OrchestrAI Deployment Script ─────────────────────────────────────────
#
# Pulls the latest code from Git, installs dependencies, optionally runs
# tests, and restarts all 6 services via the systemd target.
#
# Usage:
#   ./deploy/deploy.sh              # Deploy from 'main' branch, run tests
#   ./deploy/deploy.sh develop      # Deploy from 'develop' branch
#   ./deploy/deploy.sh main --no-test  # Skip tests for speed
#
# Run as the orchestrai user (or via sudo -u orchestrai).
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────
APP_DIR="/var/www/orchestrai"
VENV_DIR="${APP_DIR}/venv"
BRANCH="${1:-main}"
SERVICE_TARGET="orchestrai.target"
SKIP_TEST="${2:-}"

# ─── Colors ──────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo -e "${CYAN}  OrchestrAI Deployment${NC}"
echo -e "${CYAN}  $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo -e "${CYAN}  Branch: ${YELLOW}${BRANCH}${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo ""

cd "${APP_DIR}"

# ── Step 1: Pull latest code ─────────────────────────────────────────────
echo -e "${CYAN}→ Step 1/5: Pulling latest code...${NC}"
git fetch origin
git checkout "${BRANCH}"
git reset --hard "origin/${BRANCH}"
COMMIT=$(git log -1 --format='%h %s')
echo -e "  ${GREEN}✓${NC} Updated to: ${COMMIT}"

# ── Step 2: Install/update Python dependencies ──────────────────────────
echo -e "${CYAN}→ Step 2/5: Installing dependencies...${NC}"
source "${VENV_DIR}/bin/activate"
pip install --upgrade pip --quiet
pip install -e ".[dev]" --quiet
echo -e "  ${GREEN}✓${NC} Dependencies installed"

# ── Step 3: Run tests (unless --no-test) ─────────────────────────────────
if [[ "${SKIP_TEST}" == "--no-test" ]]; then
    echo -e "${YELLOW}→ Step 3/5: Tests SKIPPED (--no-test flag)${NC}"
else
    echo -e "${CYAN}→ Step 3/5: Running test suite...${NC}"
    if python -m pytest tests/ -x -q --tb=short; then
        echo -e "  ${GREEN}✓${NC} All tests passed"
    else
        echo -e "  ${RED}✗ Tests failed! Aborting deployment.${NC}"
        echo -e "  ${RED}  Code has been pulled but services are NOT restarted.${NC}"
        echo -e "  ${RED}  Fix the issue and re-run deploy.sh, or rollback with:${NC}"
        echo -e "  ${RED}  git reset --hard HEAD~1${NC}"
        exit 1
    fi
fi

# ── Step 4: Restart all services ─────────────────────────────────────────
echo -e "${CYAN}→ Step 4/5: Restarting services...${NC}"
sudo systemctl daemon-reload
sudo systemctl restart "${SERVICE_TARGET}"
echo -e "  ${GREEN}✓${NC} Restart signal sent"

# ── Step 5: Verify service health ────────────────────────────────────────
echo -e "${CYAN}→ Step 5/5: Verifying service health (waiting 8s)...${NC}"
sleep 8

SERVICES=(
    "orchestrai-validator:8000"
    "orchestrai-title-lookup:8001"
    "orchestrai-calendar:8002"
    "orchestrai-imdb:8003"
    "orchestrai-instagram-filter:8004"
    "orchestrai-instagram-analyzer:8010"
)

FAILED=0
echo ""
echo -e "${CYAN}── Service Status ──${NC}"

for entry in "${SERVICES[@]}"; do
    NAME="${entry%%:*}"
    PORT="${entry##*:}"
    if curl -sf --max-time 5 "http://127.0.0.1:${PORT}/" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} ${NAME} (port ${PORT})"
    else
        echo -e "  ${RED}✗${NC} ${NAME} (port ${PORT}) — ${RED}FAILED${NC}"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
if [ "${FAILED}" -eq 0 ]; then
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✓ Deployment complete — all services healthy${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
else
    echo -e "${RED}═══════════════════════════════════════════════${NC}"
    echo -e "${RED}  ✗ ${FAILED} service(s) failed to start${NC}"
    echo -e "${RED}  Check logs: journalctl -u <service-name> --since '5 min ago'${NC}"
    echo -e "${RED}═══════════════════════════════════════════════${NC}"
    exit 1
fi
