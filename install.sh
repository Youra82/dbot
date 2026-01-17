#!/bin/bash

# --- Fehlerbehandlung: Script stoppt bei Fehler ---
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}======================================================="
echo "    DBot Aggressiver Scalper - Installations-Skript"
echo "=======================================================${NC}"

# --- System-Abhängigkeiten prüfen/installieren ---
echo -e "\n${YELLOW}1/5: Prüfe und installiere System-Abhängigkeiten...${NC}"

if command -v apt-get &> /dev/null; then
    # Debian/Ubuntu
    echo "Erkannt: Debian/Ubuntu"
    sudo apt-get update || true
    sudo apt-get install -y python3 python3-venv git || true
elif command -v brew &> /dev/null; then
    # macOS
    echo "Erkannt: macOS (Homebrew)"
    brew install python@3.11 git || true
else
    echo "⚠️  Paketmanager nicht erkannt. Stelle sicher, dass Python 3.8+ installiert ist."
fi

# --- Python-Version prüfen ---
if ! command -v python3 &> /dev/null; then
    echo -e "${NC}❌ Python 3 nicht gefunden!"
    echo "   Installiere Python 3.8+ manuell und versuche es erneut"
    exit 1
fi

echo -e "${GREEN}✅ Python gefunden: $(python3 --version)${NC}"

# --- Git prüfen ---
if ! command -v git &> /dev/null; then
    echo -e "${NC}❌ Git nicht gefunden!"
    echo "   Installiere Git und versuche es erneut"
    exit 1
fi

echo -e "${GREEN}✅ Git gefunden: $(git --version)${NC}\n"

# --- Python Virtuelle Umgebung einrichten ---
echo -e "${YELLOW}2/5: Erstelle eine isolierte Python-Umgebung (.venv)...${NC}"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "${GREEN}✔ Virtuelle Umgebung wurde erstellt.${NC}"
else
    echo -e "${GREEN}✔ Virtuelle Umgebung existiert bereits.${NC}"
fi

# --- Aktiviere venv und installiere Dependencies ---
echo -e "\n${YELLOW}3/5: Aktiviere virtuelle Umgebung und installiere Python-Bibliotheken...${NC}"

source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip --quiet

# Install requirements
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo -e "${GREEN}✔ Alle Python-Bibliotheken wurden erfolgreich installiert.${NC}"
else
    echo -e "${YELLOW}⚠️  requirements.txt nicht gefunden, überspringe pip install.${NC}"
fi

# --- Optional: Installiere zusätzliche Packages ---
echo -e "\n${YELLOW}4/5: Installiere optionale Trading-Packages...${NC}"

pip install plotly --quiet
pip install ta-lib --quiet 2>/dev/null || echo "⚠️  ta-lib konnte nicht installiert werden (optional)"

echo -e "${GREEN}✔ Optional packages installiert.${NC}"

# --- Deactivate venv ---
deactivate

# --- Setze Ausführungsrechte für Skripte ---
echo -e "\n${YELLOW}5/5: Setze Ausführungsrechte für alle .sh-Skripte...${NC}"

chmod +x *.sh 2>/dev/null || true

echo -e "${GREEN}✔ Ausführungsrechte gesetzt.${NC}"

# --- Abschluss ---
echo -e "\n${GREEN}======================================================="
echo "✅  Installation erfolgreich abgeschlossen!"
echo "=======================================================${NC}"
echo ""
echo -e "${YELLOW}Nächste Schritte:${NC}"
echo "  1. Erstelle die 'secret.json' Datei mit deinen API-Keys:"
echo "     nano secret.json"
echo ""
echo "  2. Passe 'settings.json' nach Bedarf an:"
echo "     nano settings.json"
echo ""
echo "  3. Führe ein Update durch (empfohlen):"
echo "     chmod +x update.sh"
echo "     bash ./update.sh"
echo ""
echo "  4. Starte den DBot:"
echo "     python src/dbot/strategy/run.py --symbol BTC/USDT:USDT --timeframe 1m --use_macd false"
echo ""
echo "  5. Oder starte mehrere Strategien mit dem Pipeline-Skript:"
echo "     chmod +x run_pipeline.sh"
echo "     bash ./run_pipeline.sh"
echo ""
echo -e "${YELLOW}Für weitere Infos siehe: README.md${NC}"
echo -e "=======================================================${NC}\n"
