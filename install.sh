#!/bin/bash
set -e
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
cd "$SCRIPT_DIR"

echo -e "${YELLOW}=== dbot LSTM Installation ===${NC}"

# 1. venv erstellen
echo -e "${YELLOW}1. Erstelle virtuelle Umgebung (.venv)...${NC}"
python3 -m venv .venv --upgrade-deps
echo -e "${GREEN}   Virtuelle Umgebung erstellt.${NC}"

# 2. pip upgrade
echo -e "${YELLOW}2. Upgrade pip...${NC}"
.venv/bin/pip install --upgrade pip setuptools wheel --quiet

# 3. Requirements installieren
echo -e "${YELLOW}3. Installiere Abhängigkeiten (requirements.txt)...${NC}"
echo -e "   Hinweis: torch kann groß sein (~200 MB) und einige Minuten dauern."
.venv/bin/pip install -r requirements.txt

echo -e "${GREEN}   Abhängigkeiten installiert.${NC}"

# 4. Verzeichnisse anlegen
echo -e "${YELLOW}4. Erstelle fehlende Verzeichnisse...${NC}"
mkdir -p artifacts/models artifacts/results artifacts/tracker logs data
mkdir -p src/dbot/strategy/configs
echo -e "${GREEN}   Verzeichnisse vorhanden.${NC}"

# 5. secret.json aus Template
if [ ! -f "secret.json" ]; then
    echo -e "${YELLOW}5. Erstelle secret.json aus Template...${NC}"
    cp secret.json.template secret.json
    echo -e "${GREEN}   secret.json erstellt — bitte API-Keys eintragen!${NC}"
else
    echo -e "${GREEN}5. secret.json bereits vorhanden.${NC}"
fi

# 6. Ausführungsrechte
echo -e "${YELLOW}6. Setze Ausführungsrechte...${NC}"
chmod +x *.sh

# 7. PyTorch-Test
echo -e "${YELLOW}7. Prüfe PyTorch-Installation...${NC}"
if .venv/bin/python3 -c "import torch; print(f'   PyTorch {torch.__version__} OK')" 2>/dev/null; then
    echo -e "${GREEN}   PyTorch verfügbar.${NC}"
else
    echo -e "${YELLOW}   PyTorch konnte nicht importiert werden. Manuell prüfen.${NC}"
fi

echo ""
echo -e "${GREEN}=== Installation abgeschlossen ===${NC}"
echo ""
echo "Nächste Schritte:"
echo "  1. secret.json bearbeiten: nano secret.json"
echo "  2. Pipeline starten:       ./run_pipeline.sh"
echo "  3. Ergebnisse anzeigen:    ./show_results.sh"
