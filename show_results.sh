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
RESULTS_SCRIPT="src/dbot/analysis/show_results.py"

if ! test -x "$VENV_PYTHON"; then
    echo -e "${RED}Fehler: Virtuelle Umgebung nicht gefunden. Bitte install.sh ausführen.${NC}"
    exit 1
fi

if ! source "$VENV_ACTIVATE"; then
    echo -e "${RED}Fehler beim Aktivieren der venv!${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Wähle einen Analyse-Modus für dbot (LSTM):${NC}"
echo "  1) Einzel-Analyse                — Backtest jeder trainierten Strategie"
echo "  2) Manuelle Portfolio-Simulation — Du wählst das Team"
echo "  3) Auto Portfolio-Optimierung    — Der Bot wählt das beste Team"
echo "  4) Live-Status                   — Aktuelle Tracker-Dateien & Performance-Stats"
read -p "Auswahl (1-4) [Standard: 1]: " MODE
MODE=${MODE:-1}

if [[ ! "$MODE" =~ ^[1-4]$ ]]; then
    echo -e "${RED}❌ Ungültige Eingabe! Verwende Standard (1).${NC}"
    MODE=1
fi

echo ""
export PYTHONPATH="$SCRIPT_DIR/src"
"$VENV_PYTHON" "$RESULTS_SCRIPT" --mode "$MODE"

if command -v deactivate &> /dev/null; then
    deactivate
fi
