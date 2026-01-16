#!/bin/bash
# Sofortiger Abbruch deaktiviert, Fehler werden pro Stufe abgefangen
set +e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}======================================================="
echo "   DBot Vollautomatische 3-Stufen-Pipeline"
echo -e "=======================================================${NC}"

# --- Prereq-Check: bc für Float-Vergleiche ---
BC_MISSING=false
if ! command -v bc >/dev/null 2>&1; then
    BC_MISSING=true
    echo -e "${YELLOW}Warnung:${NC} 'bc' nicht gefunden. Fallback auf Python für Vergleichs-Checks."
fi

# --- Pfade definieren ---
VENV_PATH=".venv/bin/activate"
TRAINER="src/dbot/analysis/trainer.py"
THRESHOLD_FINDER="src/dbot/analysis/find_best_threshold.py"
OPTIMIZER="src/dbot/analysis/optimizer.py"

# --- Umgebung aktivieren ---
source "$VENV_PATH"
echo -e "${GREEN}✔ Virtuelle Umgebung wurde erfolgreich aktiviert.${NC}"

# --- AUFRÄUM-ASSISTENT (SICHERE VERSION) ---
echo -e "\n${YELLOW}Möchtest du alle alten, generierten Ergebnisse (Modelle & Konfigs) vor dem Start löschen?${NC}"
read -p "Dies wird für einen kompletten Neustart empfohlen. (j/n) [Standard: n]: " CLEANUP_CHOICE
CLEANUP_CHOICE=${CLEANUP_CHOICE:-n}
CLEANUP_CHOICE=$(echo ${CLEANUP_CHOICE} | tr -d '[:space:]')

if [[ "${CLEANUP_CHOICE,,}" == "j" ]]; then
    echo -e "${YELLOW}Lösche alte Konfigurationen und Modelle...${NC}"
    rm -f src/dbot/strategy/configs/config_*.json;
    rm -f artifacts/models/*;
    echo -e "${GREEN}✔ Aufräumen abgeschlossen.${NC}"
else
    echo -e "${GREEN}✔ Alte Ergebnisse werden beibehalten.${NC}"
fi

# --- Interaktive Abfrage ---
read -p "Handelspaar(e) eingeben (ohne /USDT, z.B. BTC ETH SOL): " SYMBOLS
read -p "Zeitfenster eingeben (z.B. 1m 5m 15m): " TIMEFRAMES
echo -e "\n${BLUE}--- Empfehlung: Rückblick-Zeitraum für Scalping ---${NC}"
printf "+-------------+--------------------------------+\n"; printf "| Zeitfenster | Empfohlener Rückblick (Tage)   |\n"; printf "+-------------+--------------------------------+\n"; printf "| 1m          | 7 - 30 Tage                    |\n"; printf "| 5m          | 30 - 90 Tage                   |\n"; printf "| 15m         | 90 - 180 Tage                  |\n"; printf "| 1h          | 180 - 365 Tage                 |\n"; printf "+-------------+--------------------------------+\n"
read -p "Startdatum (JJJJ-MM-TT) oder 'a' für Automatik [Standard: a]: " START_DATE_INPUT; START_DATE_INPUT=${START_DATE_INPUT:-a}
read -p "Enddatum (JJJJ-MM-TT) [Standard: Heute]: " END_DATE; END_DATE=${END_DATE:-$(date +%F)}
read -p "Startkapital in USDT [Standard: 20]: " START_CAPITAL; START_CAPITAL=${START_CAPITAL:-20}
read -p "CPU-Kerne [Standard: -1 für alle]: " N_CORES; N_CORES=${N_CORES:--1}
read -p "Anzahl Trials [Standard: 100]: " N_TRIALS; N_TRIALS=${N_TRIALS:-100}
read -p "Mindest-Genauigkeit in % eingeben [Standard: 50]: " MIN_ACCURACY; MIN_ACCURACY=${MIN_ACCURACY:-50}

echo -e "\n${YELLOW}Wähle einen Optimierungs-Modus:${NC}"; echo "  1) Strenger Modus"; echo "  2) 'Finde das Beste'-Modus"
read -p "Auswahl (1-2) [Standard: 1]: " OPTIM_MODE; OPTIM_MODE=${OPTIM_MODE:-1}
if [ "$OPTIM_MODE" == "1" ]; then
    OPTIM_MODE_ARG="strict"; read -p "Max Drawdown % [Standard: 30]: " MAX_DD; MAX_DD=${MAX_DD:-30}; read -p "Min Win-Rate % [Standard: 55]: " MIN_WR; MIN_WR=${MIN_WR:-55}; read -p "Min PnL % [Standard: 0]: " MIN_PNL; MIN_PNL=${MIN_PNL:-0}
else
    OPTIM_MODE_ARG="best_profit"; read -p "Max Drawdown % [Standard: 30]: " MAX_DD; MAX_DD=${MAX_DD:-30}; MIN_WR=0; MIN_PNL=-99999
fi

# --- run_optimization ---
run_optimization() {
    local symbol=$1; local timeframe=$2;
    echo -e "\n${GREEN}>>> STUFE 3/3: Starte Optimierung für $symbol ($timeframe)...${NC}"
    python3 "$OPTIMIZER" --symbols "$symbol" --timeframes "$timeframe" --start_date "$CURRENT_START_DATE" --end_date "$CURRENT_END_DATE" --jobs "$N_CORES" --max_drawdown "$MAX_DD" --start_capital "$START_CAPITAL" --min_win_rate "$MIN_WR" --trials "$N_TRIALS" --min_pnl "$MIN_PNL" --mode "$OPTIM_MODE_ARG" --threshold "$BEST_THRESHOLD"
    if [ $? -ne 0 ]; then echo -e "${RED}Fehler im Optimierer für $symbol ($timeframe). Überspringe...${NC}"; fi
}

for symbol in $SYMBOLS; do
    for timeframe in $TIMEFRAMES; do
        pipeline_success=false
        for i in {1..3}; do
            if [ "$START_DATE_INPUT" == "a" ]; then
                lookback_days=90; case "$timeframe" in 1m) lookback_days=30 ;; 5m|15m) lookback_days=90 ;; 30m|1h) lookback_days=180 ;; 2h|4h) lookback_days=365 ;; 6h|1d) lookback_days=730 ;; esac
                start_year_offset=$(( (i - 1) * 365 )); total_offset=$(( lookback_days + start_year_offset ))
                CURRENT_START_DATE=$(date -d "$total_offset days ago" +%F); CURRENT_END_DATE=$(date -d "$start_year_offset days ago" +%F)
            else
                year_offset=$(( i - 1 )); CURRENT_START_DATE=$(date -d "$START_DATE_INPUT -$year_offset year" +%F); CURRENT_END_DATE=$(date -d "$END_DATE -$year_offset year" +%F)
            fi
            echo -e "\n${BLUE}=======================================================${NC}"; echo -e "${BLUE}  Bearbeite Pipeline für: $symbol ($timeframe) - VERSUCH $i/3${NC}"; echo -e "${BLUE}  Datenzeitraum: $CURRENT_START_DATE bis $CURRENT_END_DATE${NC}"; echo -e "${BLUE}=======================================================${NC}"

            echo -e "\n${GREEN}>>> STUFE 1/3: Starte Modelltraining...${NC}"; TRAINER_OUTPUT=$(python3 "$TRAINER" --symbols "$symbol" --timeframes "$timeframe" --start_date "$CURRENT_START_DATE" --end_date "$END_DATE" 2>&1); TRAINER_STATUS=$?; echo "$TRAINER_OUTPUT"
            if [ $TRAINER_STATUS -ne 0 ]; then echo -e "${YELLOW}Versuch $i nicht erfolgreich (Trainer Fehlercode $TRAINER_STATUS).${NC}"; continue; fi
            MODEL_ACCURACY=$(echo "$TRAINER_OUTPUT" | awk '/Modell-Genauigkeit auf Testdaten:/ {gsub(/%/, ""); print $NF}');
            if [[ -z "$MODEL_ACCURACY" ]]; then echo -e "${YELLOW}Versuch $i nicht erfolgreich (Keine Modell-Genauigkeit gefunden).${NC}"; continue; fi
            IS_OK=0
            if [ "$BC_MISSING" = true ]; then
                python3 - "$MODEL_ACCURACY" "$MIN_ACCURACY" <<'PY'
import sys
acc=float(sys.argv[1]); minacc=float(sys.argv[2]);
sys.exit(0 if acc>=minacc else 1)
PY
                IS_OK=$?
            else
                echo "$MODEL_ACCURACY >= $MIN_ACCURACY" | bc -l >/dev/null 2>&1; IS_OK=$?
            fi
            if [ $IS_OK -ne 0 ]; then echo -e "${YELLOW}Versuch $i nicht erfolgreich (Modell-Qualität ${MODEL_ACCURACY}% < ${MIN_ACCURACY}%).${NC}"; continue; fi
            echo -e "${GREEN}✔ Qualitätscheck bestanden (${MODEL_ACCURACY}%).${NC}"

            echo -e "\n${GREEN}>>> STUFE 2/3: Suche besten Threshold...${NC}"; THRESHOLD_OUTPUT=$(python3 "$THRESHOLD_FINDER" --symbol "$symbol" --timeframe "$timeframe" --start_date "$CURRENT_START_DATE" --end_date "$END_DATE" 2>&1); THRESHOLD_STATUS=$?; echo "$THRESHOLD_OUTPUT"; BEST_THRESHOLD=$(echo "$THRESHOLD_OUTPUT" | tail -n 1)
            if [ $THRESHOLD_STATUS -ne 0 ]; then echo -e "${YELLOW}Versuch $i nicht erfolgreich (Threshold Finder Fehlercode $THRESHOLD_STATUS).${NC}"; continue; fi
            if ! [[ "$BEST_THRESHOLD" =~ ^[0-9]+\.[0-9]+$ ]]; then echo -e "${YELLOW}Versuch $i nicht erfolgreich (Kein Threshold gefunden).${NC}"; continue; fi
            echo -e "${GREEN}✔ Bester Threshold auf ${BEST_THRESHOLD} gesetzt.${NC}"

            run_optimization "$symbol" "$timeframe"

            pipeline_success=true; break
        done
        if [ "$pipeline_success" = false ]; then echo -e "\n${RED}=======================================================${NC}"; echo -e "${RED}  FINALER FEHLER: Konnte nach 3 Versuchen keine Strategie für $symbol ($timeframe) finden.${NC}"; echo -e "${RED}=======================================================${NC}"; fi
    done
done

deactivate

echo -e "\n${GREEN}=======================================================${NC}"
echo -e "${GREEN}  ✔ Pipeline vollständig abgeschlossen!${NC}"
echo -e "${GREEN}=======================================================${NC}"
echo -e "Ergebnisse finden sich in:"
echo -e "  - ${BLUE}src/dbot/strategy/configs/${NC} (Strategiekonfigurationen)"
echo -e "  - ${BLUE}artifacts/models/${NC} (ML-Modelle)"
echo ""
echo -e "Nächste Schritte:"
echo -e "  1. ${YELLOW}./show_results.sh${NC} - Siehe Backtesting-Ergebnisse"
echo -e "  2. Prüfe ${YELLOW}settings.json${NC} - Aktiviere Strategien für Live-Trading"
echo -e "  3. ${YELLOW}python master_runner.py${NC} - Starte Live-Trading"
