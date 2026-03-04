#!/bin/bash
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
cd "$SCRIPT_DIR"

VENV_PATH=".venv"
VENV_ACTIVATE="$VENV_PATH/bin/activate"
VENV_PYTHON="$VENV_PATH/bin/python3"
VENV_PIP="$VENV_PATH/bin/pip"
RESULTS_SCRIPT="src/dbot/analysis/show_results.py"

# venv prüfen / neu erstellen
if ! test -x "$VENV_PYTHON" || ! test -x "$VENV_PIP"; then
    echo -e "${YELLOW}Virtuelle Umgebung nicht gefunden — wird erstellt...${NC}"
    rm -rf "$VENV_PATH" 2>/dev/null || true
    python3 -m venv "$VENV_PATH" --upgrade-deps
    echo -e "${GREEN}Neue virtuelle Umgebung erstellt.${NC}"
fi

if ! source "$VENV_ACTIVATE"; then
    echo -e "${RED}Fehler beim Aktivieren der venv!${NC}"
    exit 1
fi

# Abhängigkeiten prüfen
echo -e "${YELLOW}Überprüfe Python-Abhängigkeiten...${NC}"
"$VENV_PIP" install --upgrade pip setuptools wheel --quiet 2>/dev/null || true

if ! "$VENV_PYTHON" -c "import pandas, torch, optuna" 2>/dev/null; then
    echo -e "${YELLOW}Installiere fehlende Pakete...${NC}"
    "$VENV_PIP" install -r requirements.txt --quiet 2>/dev/null || \
    "$VENV_PIP" install --break-system-packages -r requirements.txt --quiet 2>/dev/null || true
    echo -e "${GREEN}Pakete installiert.${NC}"
fi

# Kapital abfragen
read -p "Startkapital USDT [1000]: " CAPITAL
CAPITAL=${CAPITAL:-1000}

# Modus-Menü
echo ""
echo -e "${YELLOW}Wähle einen Analyse-Modus für dbot (LSTM):${NC}"
echo "  1) Einzel-Analyse        — Backtest jeder trainierten Strategie"
echo "  2) Portfolio-Simulation  — Alle Strategien kombiniert (Kapital geteilt)"
echo "  3) Modell-Info           — Prediction-Verteilung & Modell-Metadaten"
echo "  4) Live-Status           — Aktuelle Tracker-Dateien & Performance-Stats"
read -p "Auswahl (1-4) [Standard: 1]: " MODE
MODE=${MODE:-1}

echo ""
export PYTHONPATH="$SCRIPT_DIR/src"
"$VENV_PYTHON" "$RESULTS_SCRIPT" --mode "$MODE" --capital "$CAPITAL"

if command -v deactivate &> /dev/null; then
    deactivate
fi
