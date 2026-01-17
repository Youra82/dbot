#!/bin/bash
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

VENV_PATH=".venv/bin/activate"
OPTIMIZER="src/dbot/analysis/scalper_optimizer.py"

if [ ! -f "$VENV_PATH" ]; then
    echo -e "${RED}Virtual environment not found. Run ./install.sh first.${NC}"
    exit 1
fi

source "$VENV_PATH"

echo -e "${BLUE}======================================================="
echo "   DBot Scalper Strategy Optimizer"
echo -e "=======================================================${NC}"

read -p "Symbol (e.g., BTC ETH SOL): " SYMBOLS_INPUT
read -p "Timeframes (e.g., 1m 5m): " TIMEFRAMES
read -p "Start capital [default: 1000]: " START_CAPITAL
START_CAPITAL=${START_CAPITAL:-1000}

echo -e "\n${YELLOW}Note: Date ranges are auto-selected based on timeframe:${NC}"
echo "  1m → 1 day (reduces backtest time)"
echo "  5m → 3 days"
echo "  15m+ → 7 days"
echo ""

for symbol_short in $SYMBOLS_INPUT; do
    # Auto-format symbol
    if [[ ! "$symbol_short" =~ "/" ]]; then
        SYMBOL="${symbol_short}/USDT:USDT"
    else
        SYMBOL="$symbol_short"
    fi
    
    for TF in $TIMEFRAMES; do
        echo -e "\n${GREEN}>>> Optimizing $SYMBOL ($TF)...${NC}"
        
        python3 "$OPTIMIZER" \
            --symbol "$SYMBOL" \
            --timeframe "$TF" \
            --start_capital "$START_CAPITAL"
        
        if [ $? -ne 0 ]; then
            echo -e "${YELLOW}Warning: Optimization failed for $SYMBOL ($TF)${NC}"
        fi
    done
done

echo -e "\n${GREEN}✅ Pipeline complete!${NC}"
echo -e "Optimized configs saved in: ${BLUE}artifacts/optimized_configs/${NC}"
