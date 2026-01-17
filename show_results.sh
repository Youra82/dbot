#!/bin/bash
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

VENV_PATH=".venv/bin/activate"
RESULTS_SCRIPT="src/dbot/analysis/show_results.py"
OPTIMAL_CONFIGS_FILE=".optimal_configs.tmp"
UPDATE_SCRIPT="update_settings_from_optimizer.py"

# Aktiviere venv und prüfe auf Fehler
if [ ! -f "$VENV_PATH" ]; then
	echo -e "${RED}❌ Virtual Environment nicht gefunden unter: $VENV_PATH${NC}"
	echo "Bitte zuerst 'python3 -m venv .venv' ausführen."
	exit 1
fi

source "$VENV_PATH"

echo -e "${BLUE}======================================================="
echo "   DBot Ergebnisse & Analyse"
echo -e "=======================================================${NC}"

# --- MODUS-MENÜ (JaegerBot kompatibel) ---
echo -e "\n${YELLOW}Wähle einen Analyse-Modus:${NC}"
echo "  1) Einzel-Analyse (jede Strategie wird isoliert getestet)"
echo "  2) Manuelle Portfolio-Simulation (du wählst das Team)"
echo "  3) Automatische Portfolio-Optimierung (der Bot wählt das beste Team)"
echo "  4) Interaktive Charts (Entry/Exit-Signale nur, keine Indikatoren)"
read -p "Auswahl (1-4) [Standard: 1]: " MODE
MODE=${MODE:-1}


python3 "$RESULTS_SCRIPT" --mode "$MODE"

# --- OPTION 4: INTERAKTIVE CHARTS ---
if [ "$MODE" == "4" ]; then
    echo -e "\n${YELLOW}========== INTERAKTIVE CHARTS ===========${NC}"
    echo ""
    echo "Wähle Konfigurationsdateien von der Liste oben"
    echo ""
    python3 src/dbot/analysis/interactive_status.py
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Charts wurden generiert!${NC}"
    else
        echo -e "${RED}❌ Fehler beim Generieren der Charts.${NC}"
    fi
    
    deactivate
    exit 0
fi

if [ "$MODE" == "3" ] && [ -f "$OPTIMAL_CONFIGS_FILE" ]; then
    echo ""
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}  SETTINGS AUTOMATISCH AKTUALISIEREN?${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    echo "Die optimierten Strategien können jetzt automatisch"
    echo "in die settings.json übernommen werden."
    echo ""
    echo -e "${RED}ACHTUNG:${NC} Dies ersetzt alle aktuellen Strategien!"
    echo "Es wird automatisch ein Backup erstellt (settings.json.backup)."
    echo ""
    read -p "Sollen die optimierten Strategien übernommen werden? (j/n): " APPLY_SETTINGS
    
    if [[ "$APPLY_SETTINGS" =~ ^[jJyY]$ ]]; then
        echo ""
        echo -e "${BLUE}Aktualisiere settings.json...${NC}"
        
        # Lese Config-Dateien aus Temp-Datei
        CONFIGS=$(cat "$OPTIMAL_CONFIGS_FILE")
        
        # Rufe Python-Script auf mit allen Config-Namen als Argumente
        python3 "$UPDATE_SCRIPT" $CONFIGS
        
        if [ $? -eq 0 ]; then
            echo ""
            echo -e "${GREEN}✅ Settings wurden erfolgreich aktualisiert!${NC}"
            echo -e "${GREEN}   Backup wurde erstellt: settings.json.backup${NC}"
        else
            echo ""
            echo -e "${RED}❌ Fehler beim Aktualisieren der Settings.${NC}"
        fi
        
        # Lösche Temp-Datei
        rm -f "$OPTIMAL_CONFIGS_FILE"
    else
        echo ""
        echo -e "${YELLOW}ℹ  Settings wurden NICHT aktualisiert.${NC}"
        echo "Du kannst die Strategien später manuell in settings.json eintragen."
        
        # Lösche Temp-Datei
        rm -f "$OPTIMAL_CONFIGS_FILE"
    fi
fi

deactivate


echo -e "\n${BLUE}=======================================================${NC}"
echo -e "${BLUE}  Nützliche Befehle:${NC}"
echo -e "${BLUE}=======================================================${NC}"
echo "  ./show_status.sh               # Bot Status prüfen"
echo "  tail -f logs/dbot_*.log        # Alle Logs live"
echo "  grep 'Position' logs/*.log     # Alle Trade-Ereignisse"
echo "  python master_runner.py        # Bot starten"
echo -e "${BLUE}=======================================================${NC}"
