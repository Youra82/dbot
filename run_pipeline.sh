#!/bin/bash
# run_pipeline.sh — Interaktive LSTM-Pipeline: Train → Optimize → Backtest
set -e

PYTHON=".venv/bin/python3"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   dbot LSTM Pipeline                 ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Symbol eingeben
read -p "Symbol (z.B. BTC/USDT:USDT): " SYMBOL
read -p "Timeframe (z.B. 4h): " TIMEFRAME
read -p "Startkapital USDT [1000]: " CAPITAL
CAPITAL=${CAPITAL:-1000}
read -p "Training-Epochen [50]: " EPOCHS
EPOCHS=${EPOCHS:-50}
read -p "Optuna-Trials [100]: " TRIALS
TRIALS=${TRIALS:-100}
read -p "Horizont (Kerzen in die Zukunft) [5]: " HORIZON
HORIZON=${HORIZON:-5}
read -p "Neutrale Zone % [0.3]: " NEUTRAL_ZONE
NEUTRAL_ZONE=${NEUTRAL_ZONE:-0.3}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Symbol:      $SYMBOL"
echo "  Timeframe:   $TIMEFRAME"
echo "  Kapital:     $CAPITAL USDT"
echo "  Epochen:     $EPOCHS"
echo "  Trials:      $TRIALS"
echo "  Horizont:    $HORIZON Kerzen"
echo "  Neutral:     $NEUTRAL_ZONE %"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
read -p "Starten? [j/N]: " CONFIRM
if [[ "$CONFIRM" != "j" && "$CONFIRM" != "J" ]]; then
    echo "Abgebrochen."
    exit 0
fi

echo ""
echo "=== Schritt 1/3: LSTM Training ==="
$PYTHON train_model.py \
    --symbol "$SYMBOL" \
    --timeframe "$TIMEFRAME" \
    --epochs "$EPOCHS" \
    --horizon "$HORIZON" \
    --neutral-zone "$NEUTRAL_ZONE"

echo ""
echo "=== Schritt 2/3: Signal-Threshold Optimierung (Optuna) ==="
PYTHONPATH=src $PYTHON -m dbot.analysis.optimizer \
    --symbol "$SYMBOL" \
    --timeframe "$TIMEFRAME" \
    --trials "$TRIALS" \
    --start-capital "$CAPITAL"

echo ""
echo "=== Schritt 3/3: Finaler Backtest ==="
PYTHONPATH=src $PYTHON -m dbot.analysis.backtester \
    --symbol "$SYMBOL" \
    --timeframe "$TIMEFRAME" \
    --start-capital "$CAPITAL"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Pipeline abgeschlossen!"
echo ""
SAFE_SYMBOL=$(echo "$SYMBOL" | tr '/:' '-')
CONFIG_PATH="src/dbot/strategy/configs/config_${SAFE_SYMBOL}_${TIMEFRAME}_lstm.json"
echo "  Config: $CONFIG_PATH"
echo ""
echo "  Live Trading aktivieren:"
echo "  1. Config prüfen: cat $CONFIG_PATH"
echo "  2. settings.json: active=true setzen für $SYMBOL $TIMEFRAME"
echo "  3. secret.json: dbot API-Keys eintragen"
echo "  4. Cronjob: */15 * * * * .venv/bin/python3 master_runner.py"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
