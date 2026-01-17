#!/bin/bash
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

VENV_PATH=".venv/bin/activate"
BACKTESTER="src/dbot/analysis/backtester.py"
EXPORT_DIR="artifacts/backtests"

if [ ! -f "$VENV_PATH" ]; then
    echo -e "${RED}Virtuelle Umgebung nicht gefunden. Bitte ./install.sh ausführen.${NC}"
    exit 1
fi

source "$VENV_PATH"

mkdir -p "$EXPORT_DIR"

echo -e "${BLUE}======================================================="
echo "   DBot SMC Backtest (interaktiv)"
echo -e "=======================================================${NC}"

read -p "Symbole (z.B. BTC/USDT:USDT ETH/USDT:USDT): " SYMBOLS
read -p "Timeframes (z.B. 1m 5m): " TIMEFRAMES
read -p "Startdatum (YYYY-MM-DD): " START_DATE
read -p "Enddatum (heute) [Enter = heute]: " END_DATE; END_DATE=${END_DATE:-$(date +%F)}
read -p "Startkapital [1000]: " START_CAPITAL; START_CAPITAL=${START_CAPITAL:-1000}

# Fixe Werte (nicht mehr abgefragt)
LEV=8
RISK=0.12
FEE=0.0005

RESULT_FILES=()

for SYM in $SYMBOLS; do
    for TF in $TIMEFRAMES; do
        SAFE_NAME=$(echo "$SYM" | sed 's#[/:]#-#g')
        OUT_FILE="$EXPORT_DIR/${SAFE_NAME}_${TF}.csv"
        echo -e "\n${GREEN}>>> Backtest $SYM ($TF)...${NC}"
        python "$BACKTESTER" \
          --symbol "$SYM" \
          --timeframe "$TF" \
          --start_date "$START_DATE" \
          --end_date "$END_DATE" \
          --leverage "$LEV" \
          --risk_per_trade "$RISK" \
          --fee_pct "$FEE" \
          --start_capital "$START_CAPITAL" \
          --export "$OUT_FILE"
        RESULT_FILES+=("$OUT_FILE")
    done
done

COUNT=${#RESULT_FILES[@]}
if [ $COUNT -gt 1 ]; then
    AGG_FILES="${RESULT_FILES[@]}"
    echo -e "\n${BLUE}Aggregiere kombinierte Equity aller Backtests...${NC}"
    python - <<PY
import pandas as pd, sys
files = "${AGG_FILES}".split()
dfs = []
for p in files:
    try:
        df = pd.read_csv(p, parse_dates=['timestamp'])
        name = p.split('/')[-1].replace('.csv','')
        dfs.append(df.rename(columns={'equity': name}).set_index('timestamp'))
    except Exception as e:
        print(f"Warnung: konnte {p} nicht laden: {e}")

if not dfs:
    print("Keine Dateien für Aggregation gefunden.")
    sys.exit(0)

combo = pd.concat(dfs, axis=1).sort_index().ffill()
combo['equity_sum'] = combo.sum(axis=1)
out = 'artifacts/backtests/combined_equity.csv'
combo.to_csv(out)
print(f"Kombinierte Equity gespeichert: {out}")
print(combo.tail())
PY
fi

deactivate

echo -e "\n${BLUE}Fertig. Siehe artifacts/backtests/*.csv${NC}"
