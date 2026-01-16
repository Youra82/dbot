#!/bin/bash
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}======================================================="
echo "   DBot Ergebnisse & Analyse"
echo -e "=======================================================${NC}"

# --- MODUS-MENÜ ---
echo -e "\n${YELLOW}Wähle einen Analyse-Modus:${NC}"
echo "  1) Letzte Log-Analyse (zeige letzte 50 Zeilen aller Logs)"
echo "  2) Trade-Historie (zeige alle Trades aus Logs)"
echo "  3) Performance-Übersicht (PnL, Win-Rate, etc.)"
echo "  4) Live-Monitoring (tail -f alle Logs)"
read -p "Auswahl (1-4) [Standard: 1]: " MODE
MODE=${MODE:-1}

case $MODE in
    1)
        echo -e "\n${BLUE}=======================================================${NC}"
        echo -e "${BLUE}  Letzte Log-Einträge (50 Zeilen pro Strategie)${NC}"
        echo -e "${BLUE}=======================================================${NC}\n"
        
        for log_file in logs/dbot_*.log; do
            if [ -f "$log_file" ]; then
                echo -e "${YELLOW}📝 $(basename "$log_file"):${NC}"
                tail -n 50 "$log_file" | sed 's/^/   /'
                echo ""
            fi
        done
        ;;
        
    2)
        echo -e "\n${BLUE}=======================================================${NC}"
        echo -e "${BLUE}  Trade-Historie (aus Logs extrahiert)${NC}"
        echo -e "${BLUE}=======================================================${NC}\n"
        
        echo -e "${YELLOW}Suche nach Trade-Signalen...${NC}\n"
        
        # Suche nach LONG/SHORT Eröffnungen
        for log_file in logs/dbot_*.log; do
            if [ -f "$log_file" ]; then
                echo -e "${CYAN}=== $(basename "$log_file") ===${NC}"
                grep -E "LONG Position eröffnet|SHORT Position eröffnet|Position geschlossen" "$log_file" | tail -n 20
                echo ""
            fi
        done
        
        echo -e "${GREEN}✔ Trade-Historie angezeigt${NC}"
        ;;
        
    3)
        echo -e "\n${BLUE}=======================================================${NC}"
        echo -e "${BLUE}  Performance-Übersicht${NC}"
        echo -e "${BLUE}=======================================================${NC}\n"
        
        echo -e "${YELLOW}⚠️  HINWEIS: Performance-Tracking noch nicht implementiert${NC}"
        echo ""
        echo "Geplante Features:"
        echo "  - Equity Curve Tracking"
        echo "  - Win-Rate & Profit Factor Berechnung"
        echo "  - Drawdown Analyse"
        echo "  - Trade-Statistiken (Anzahl, Größe, Duration)"
        echo "  - CSV Export für Excel-Analyse"
        echo ""
        echo "Aktuell verfügbar:"
        echo "  - Manuelle Log-Analyse (Option 1 & 2)"
        echo "  - Bitget Web UI für Position-Tracking"
        echo ""
        ;;
        
    4)
        echo -e "\n${BLUE}=======================================================${NC}"
        echo -e "${BLUE}  Live-Monitoring (STRG+C zum Beenden)${NC}"
        echo -e "${BLUE}=======================================================${NC}\n"
        
        # Erstelle tail -f Kommando für alle Log-Dateien
        LOG_FILES=$(find logs/ -name "dbot_*.log" 2>/dev/null | tr '\n' ' ')
        
        if [ -z "$LOG_FILES" ]; then
            echo -e "${RED}❌ Keine Log-Dateien gefunden in logs/${NC}"
            exit 1
        fi
        
        echo -e "${GREEN}Zeige Live-Logs für:${NC}"
        for log in $LOG_FILES; do
            echo "   - $(basename "$log")"
        done
        echo ""
        
        tail -f $LOG_FILES
        ;;
        
    *)
        echo -e "${RED}❌ Ungültige Auswahl${NC}"
        exit 1
        ;;
esac

echo -e "\n${BLUE}=======================================================${NC}"
echo -e "${BLUE}  Nützliche Befehle:${NC}"
echo -e "${BLUE}=======================================================${NC}"
echo "  ./show_status.sh               # Bot Status prüfen"
echo "  tail -f logs/dbot_*.log        # Alle Logs live"
echo "  grep 'Position' logs/*.log     # Alle Trade-Ereignisse"
echo "  python master_runner.py        # Bot starten"
echo -e "${BLUE}=======================================================${NC}"
