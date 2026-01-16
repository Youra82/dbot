#!/bin/bash
# DBot Pipeline für Parameter-Optimierung
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}======================================================="
echo "   DBot Parameter-Optimierungs-Pipeline"
echo -e "=======================================================${NC}"

# --- Pfade definieren ---
VENV_PATH=".venv/bin/activate"

# --- Umgebung aktivieren ---
if [ -f "$VENV_PATH" ]; then
    source "$VENV_PATH"
    echo -e "${GREEN}✔ Virtuelle Umgebung wurde erfolgreich aktiviert.${NC}"
else
    echo -e "${RED}❌ Virtuelle Umgebung nicht gefunden!${NC}"
    echo "   Führe erst ./install.sh aus"
    exit 1
fi

# --- Interaktive Abfrage ---
echo -e "\n${YELLOW}Parameter-Optimierung für DBot Scalper${NC}"
echo ""
read -p "Handelspaar(e) eingeben (mit /USDT:USDT, z.B. BTC/USDT:USDT): " SYMBOLS
read -p "Zeitfenster eingeben (z.B. 1m 5m 15m): " TIMEFRAMES

echo -e "\n${BLUE}--- Empfehlung: Rückblick-Zeitraum für Scalping ---${NC}"
printf "+-------------+--------------------------------+\n"
printf "| Zeitfenster | Empfohlener Rückblick (Tage)   |\n"
printf "+-------------+--------------------------------+\n"
printf "| 1m          | 7 - 30 Tage                    |\n"
printf "| 5m          | 30 - 90 Tage                   |\n"
printf "| 15m         | 90 - 180 Tage                  |\n"
printf "| 1h          | 180 - 365 Tage                 |\n"
printf "+-------------+--------------------------------+\n"

read -p "Rückblick in Tagen [Standard: 60]: " LOOKBACK_DAYS
LOOKBACK_DAYS=${LOOKBACK_DAYS:-60}

read -p "Startkapital in USDT [Standard: 20]: " START_CAPITAL
START_CAPITAL=${START_CAPITAL:-20}

read -p "Anzahl Trials [Standard: 100]: " N_TRIALS
N_TRIALS=${N_TRIALS:-100}

echo -e "\n${YELLOW}Leverage-Bereich für Optimierung:${NC}"
read -p "Min Leverage [Standard: 5]: " MIN_LEVERAGE
MIN_LEVERAGE=${MIN_LEVERAGE:-5}

read -p "Max Leverage [Standard: 10]: " MAX_LEVERAGE
MAX_LEVERAGE=${MAX_LEVERAGE:-10}

echo -e "\n${YELLOW}Risk-Parameter:${NC}"
read -p "Risk per Trade % [Standard: 10]: " RISK_PERCENT
RISK_PERCENT=${RISK_PERCENT:-10}

read -p "Stop Loss % [Standard: 1.0]: " STOP_LOSS
STOP_LOSS=${STOP_LOSS:-1.0}

read -p "Take Profit % [Standard: 3.0]: " TAKE_PROFIT
TAKE_PROFIT=${TAKE_PROFIT:-3.0}

# --- Berechne Datums-Range ---
END_DATE=$(date +%F)
START_DATE=$(date -d "$LOOKBACK_DAYS days ago" +%F)

echo -e "\n${BLUE}=======================================================${NC}"
echo -e "${BLUE}  Konfiguration:${NC}"
echo -e "${BLUE}  Symbole: $SYMBOLS${NC}"
echo -e "${BLUE}  Timeframes: $TIMEFRAMES${NC}"
echo -e "${BLUE}  Zeitraum: $START_DATE bis $END_DATE${NC}"
echo -e "${BLUE}  Startkapital: $START_CAPITAL USDT${NC}"
echo -e "${BLUE}  Trials: $N_TRIALS${NC}"
echo -e "${BLUE}  Leverage: $MIN_LEVERAGE-$MAX_LEVERAGE${NC}"
echo -e "${BLUE}=======================================================${NC}"

echo -e "\n${YELLOW}⚠️  HINWEIS: Parameter-Optimierung für DBot ist work in progress${NC}"
echo "Die Backtest-Engine muss noch implementiert werden."
echo "Aktuell läuft DBot nur im Live-Trading Modus."
echo ""
echo -e "${GREEN}Geplante Features:${NC}"
echo "  - Optuna-basierte Parameter-Optimierung"
echo "  - Backtest mit historischen Daten"
echo "  - Multi-Strategy Portfolio-Optimierung"
echo "  - Automatische settings.json Updates"
echo ""

read -p "Drücke Enter um fortzufahren..."

deactivate

echo -e "\n${BLUE}✔ Pipeline-Script beendet${NC}"
echo "Verwende vorerst die Standard-Parameter in settings.json"
