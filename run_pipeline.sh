#!/bin/bash
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
cd "$SCRIPT_DIR"

echo -e "${BLUE}======================================================="
echo "      dbot Vollautomatische LSTM-Pipeline"
echo -e "=======================================================${NC}"

VENV_PATH=".venv/bin/activate"
PYTHON=".venv/bin/python3"
OPTIMIZER="src/dbot/analysis/optimizer.py"

if [ ! -f "$VENV_PATH" ]; then
    echo -e "${RED}Fehler: Virtuelle Umgebung nicht gefunden. Bitte install.sh ausführen.${NC}"
    exit 1
fi

source "$VENV_PATH"
echo -e "${GREEN}✔ Virtuelle Umgebung aktiviert.${NC}"

# --- Aufräum-Assistent ---
echo -e "\n${YELLOW}Möchtest du alle alten Konfigurationen vor dem Start löschen?${NC}"
read -p "Dies wird für einen kompletten Neustart empfohlen. (j/n) [Standard: n]: " CLEANUP_CHOICE; CLEANUP_CHOICE=${CLEANUP_CHOICE:-n}
if [[ "$CLEANUP_CHOICE" == "j" || "$CLEANUP_CHOICE" == "J" ]]; then
    echo -e "${YELLOW}Lösche alte Konfigurationen (config_*_lstm.json) und Modelle...${NC}"
    rm -f src/dbot/strategy/configs/config_*_lstm.json
    rm -f artifacts/models/*.pt artifacts/models/*.pkl
    echo -e "${GREEN}✔ Aufräumen abgeschlossen.${NC}"
else
    echo -e "${GREEN}✔ Alte Konfigurationen werden beibehalten.${NC}"
fi

# --- Interaktive Abfrage ---
read -p "Handelspaar(e) eingeben (ohne /USDT:USDT, z.B. BTC ETH): " SYMBOLS
read -p "Zeitfenster eingeben (z.B. 1h 4h): " TIMEFRAMES

echo -e "\n${BLUE}--- Empfehlung: Optimaler Rückblick-Zeitraum ---${NC}"
printf "+-------------+--------------------------------+\n"
printf "| Zeitfenster | Empfohlener Rückblick (Tage)   |\n"
printf "+-------------+--------------------------------+\n"
printf "| 5m, 15m     | 60 - 90 Tage                   |\n"
printf "| 30m, 1h     | 180 - 365 Tage                 |\n"
printf "| 2h, 4h      | 550 - 730 Tage                 |\n"
printf "| 6h, 1d      | 1095 - 1825 Tage               |\n"
printf "+-------------+--------------------------------+\n"
read -p "Startdatum (JJJJ-MM-TT) oder 'a' für Automatik [Standard: a]: " START_DATE_INPUT; START_DATE_INPUT=${START_DATE_INPUT:-a}
read -p "Enddatum (JJJJ-MM-TT) [Standard: Heute]: " END_DATE; END_DATE=${END_DATE:-$(date +%F)}

read -p "Startkapital in USDT [Standard: 1000]: " START_CAPITAL; START_CAPITAL=${START_CAPITAL:-1000}
read -p "Anzahl Optuna-Trials [Standard: 200]: " N_TRIALS; N_TRIALS=${N_TRIALS:-200}

echo -e "\n${YELLOW}Wähle einen Optimierungs-Modus:${NC}"
echo "  1) Strenger Modus   (PnL mit Constraints: DD, Win-Rate, Min-PnL)"
echo "  2) 'Finde das Beste' (Max PnL, nur DD-Constraint)"
read -p "Auswahl (1-2) [Standard: 1]: " OPTIM_MODE_CHOICE; OPTIM_MODE_CHOICE=${OPTIM_MODE_CHOICE:-1}

if [ "$OPTIM_MODE_CHOICE" == "1" ]; then
    OPTIM_MODE_ARG="strict"
    read -p "Max Drawdown % [Standard: 30]: " MAX_DD; MAX_DD=${MAX_DD:-30}
    read -p "Min Win-Rate % [Standard: 0 (Ignorieren)]: " MIN_WR; MIN_WR=${MIN_WR:-0}
    read -p "Min PnL % [Standard: 0]: " MIN_PNL; MIN_PNL=${MIN_PNL:-0}
else
    OPTIM_MODE_ARG="best_profit"
    read -p "Max Drawdown % [Standard: 30]: " MAX_DD; MAX_DD=${MAX_DD:-30}
    MIN_WR=0
    MIN_PNL=-99999
fi

# --- Grid: Horizon × Neutral-Zone (automatisch durchsucht) ---
HORIZONS=(3 5 10)
NEUTRAL_ZONES=(0.2 0.3 0.5)
TOTAL_COMBOS=$((${#HORIZONS[@]} * ${#NEUTRAL_ZONES[@]}))

# --- Schleife über Symbole und Zeitrahmen ---
for symbol in $SYMBOLS; do
    FULL_SYMBOL="${symbol}/USDT:USDT"
    for timeframe in $TIMEFRAMES; do

        # --- Datumsberechnung ---
        if [ "$START_DATE_INPUT" == "a" ]; then
            lookback_days=365
            case "$timeframe" in
                5m|15m)          lookback_days=60 ;;
                30m|1h)          lookback_days=365 ;;
                2h|4h)           lookback_days=730 ;;
                6h|12h|1d|3d|1w) lookback_days=1095 ;;
            esac
            FINAL_START_DATE=$(date -d "$lookback_days days ago" +%F)
            echo -e "${YELLOW}INFO: Automatisches Startdatum für $timeframe (${lookback_days} Tage Rückblick): $FINAL_START_DATE${NC}"
        else
            FINAL_START_DATE=$START_DATE_INPUT
        fi

        SAFE_NAME="${symbol}USDTUSDT_${timeframe}"
        CONFIG_FILE="src/dbot/strategy/configs/config_${SAFE_NAME}_lstm.json"
        BEST_PNL="-9999"
        COMBO_IDX=0

        echo -e "\n${BLUE}=======================================================${NC}"
        echo -e "${BLUE}  Pipeline für: $FULL_SYMBOL ($timeframe)${NC}"
        echo -e "${BLUE}  Datenzeitraum: $FINAL_START_DATE bis $END_DATE${NC}"
        echo -e "${BLUE}  Grid-Suche: ${#HORIZONS[@]} Horizonte × ${#NEUTRAL_ZONES[@]} Zonen = $TOTAL_COMBOS Kombinationen${NC}"
        echo -e "${BLUE}=======================================================${NC}"

        for H in "${HORIZONS[@]}"; do
            for N in "${NEUTRAL_ZONES[@]}"; do
                COMBO_IDX=$((COMBO_IDX + 1))
                echo -e "\n${YELLOW}[$COMBO_IDX/$TOTAL_COMBOS] Testing horizon=$H | neutral_zone=${N}%${NC}"

                PYTHONPATH="$SCRIPT_DIR/src" "$PYTHON" "$OPTIMIZER" \
                    --symbols "$FULL_SYMBOL" \
                    --timeframes "$timeframe" \
                    --start-date "$FINAL_START_DATE" \
                    --end-date "$END_DATE" \
                    --start-capital "$START_CAPITAL" \
                    --epochs 50 \
                    --trials "$N_TRIALS" \
                    --horizon "$H" \
                    --neutral-zone "$N" \
                    --mode "$OPTIM_MODE_ARG" \
                    --max-drawdown "$MAX_DD" \
                    --min-win-rate "$MIN_WR" \
                    --min-pnl "$MIN_PNL" \
                    --force-retrain

                if [ $? -ne 0 ]; then
                    echo -e "${RED}❌ Fehler bei horizon=$H neutral_zone=$N. Überspringe...${NC}"
                    continue
                fi

                # PnL aus gespeicherter Config lesen und mit bisherigem Besten vergleichen
                if [ -f "$CONFIG_FILE" ]; then
                    NEW_PNL=$("$PYTHON" -c "import json; c=json.load(open('$CONFIG_FILE')); print(c.get('_backtest_metrics',{}).get('pnl_pct',-9999))")
                    IS_BETTER=$("$PYTHON" -c "print(1 if float('${NEW_PNL}') > float('${BEST_PNL}') else 0)")
                    if [ "$IS_BETTER" == "1" ]; then
                        BEST_PNL=$NEW_PNL
                        cp "$CONFIG_FILE" "${CONFIG_FILE}.best"
                        echo -e "${GREEN}  ✔ Neue beste Kombination! horizon=$H | neutral_zone=${N}% | PnL=$BEST_PNL%${NC}"
                    else
                        echo -e "  → PnL=$NEW_PNL% (kein Fortschritt, Bestes bisher: $BEST_PNL%)"
                    fi
                fi
            done
        done

        # Beste Config als finale Config setzen
        if [ -f "${CONFIG_FILE}.best" ]; then
            mv "${CONFIG_FILE}.best" "$CONFIG_FILE"
            echo -e "\n${GREEN}✔ Beste Config gespeichert: $FULL_SYMBOL ($timeframe) | PnL=$BEST_PNL%${NC}"
        else
            echo -e "${RED}❌ Keine valide Config gefunden für $FULL_SYMBOL ($timeframe)${NC}"
        fi
    done
done

echo -e "\n${BLUE}=======================================================${NC}"
echo -e "${BLUE}✔ Alle Pipelines abgeschlossen!${NC}"
echo -e "${BLUE}=======================================================${NC}"

# --- Automatisch settings.json aktualisieren (kein Prompt) ---
echo -e "\n${GREEN}>>> Aktualisiere settings.json mit optimierten Strategien...${NC}"

PYTHONPATH="$SCRIPT_DIR/src" "$PYTHON" - << PYTHON_SCRIPT
import json, os, glob, sys

PROJECT_ROOT = "$SCRIPT_DIR"
SETTINGS_FILE = os.path.join(PROJECT_ROOT, 'settings.json')
CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')

try:
    with open(SETTINGS_FILE) as f:
        settings = json.load(f)
except Exception as e:
    print(f"Fehler beim Laden von settings.json: {e}")
    sys.exit(1)

config_files = glob.glob(os.path.join(CONFIGS_DIR, 'config_*_lstm.json'))
if not config_files:
    print("Keine optimierten Config-Dateien gefunden.")
    sys.exit(0)

print(f"Gefundene Configs: {len(config_files)}")
new_strategies = []
for config_file in sorted(config_files):
    try:
        with open(config_file) as f:
            config = json.load(f)
        symbol = config.get('market', {}).get('symbol')
        timeframe = config.get('market', {}).get('timeframe')
        pnl = config.get('_backtest_metrics', {}).get('pnl_pct', 0)
        if symbol and timeframe:
            exists = any(s.get('symbol') == symbol and s.get('timeframe') == timeframe for s in new_strategies)
            if not exists:
                new_strategies.append({"symbol": symbol, "timeframe": timeframe, "active": True})
                print(f"  + {symbol} ({timeframe}) | PnL={pnl:.2f}%")
    except Exception as e:
        print(f"  Fehler bei {os.path.basename(config_file)}: {e}")

if new_strategies:
    settings['live_trading_settings']['active_strategies'] = new_strategies
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)
    print(f"\nsettings.json aktualisiert: {len(new_strategies)} Strategie(n) AKTIVIERT.")
else:
    print("Keine Strategien zum Übernehmen gefunden.")
PYTHON_SCRIPT

deactivate

echo -e "\n${BLUE}=======================================================${NC}"
echo -e "${BLUE}✔ Pipeline abgeschlossen!${NC}"
echo -e "${BLUE}=======================================================${NC}"
