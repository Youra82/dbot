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

echo -e "\n${BLUE}--- Empfehlung: Anzahl Kerzen ---${NC}"
printf "+-------------+--------------------------------+\n"
printf "| Zeitfenster | Empfohlene Kerzen-Anzahl       |\n"
printf "+-------------+--------------------------------+\n"
printf "| 5m, 15m     | 2000 - 3000                    |\n"
printf "| 30m, 1h     | 2000 - 3000                    |\n"
printf "| 2h, 4h      | 1500 - 2000                    |\n"
printf "| 6h, 1d      | 1000 - 1500                    |\n"
printf "+-------------+--------------------------------+\n"
read -p "Anzahl Kerzen (limit) [Standard: 2000]: " LIMIT; LIMIT=${LIMIT:-2000}

read -p "Startkapital in USDT [Standard: 1000]: " START_CAPITAL; START_CAPITAL=${START_CAPITAL:-1000}
read -p "LSTM Training-Epochen [Standard: 50]: " EPOCHS; EPOCHS=${EPOCHS:-50}
read -p "Anzahl Optuna-Trials [Standard: 100]: " N_TRIALS; N_TRIALS=${N_TRIALS:-100}
read -p "Vorhersage-Horizont (Kerzen) [Standard: 5]: " HORIZON; HORIZON=${HORIZON:-5}
read -p "Neutrale Zone % [Standard: 0.3]: " NEUTRAL_ZONE; NEUTRAL_ZONE=${NEUTRAL_ZONE:-0.3}

echo -e "\n${YELLOW}Modell neu trainieren?${NC}"
read -p "Vorhandene Modelle überschreiben? (j/n) [Standard: n]: " RETRAIN_CHOICE; RETRAIN_CHOICE=${RETRAIN_CHOICE:-n}
RETRAIN_FLAG=""
if [[ "$RETRAIN_CHOICE" == "j" || "$RETRAIN_CHOICE" == "J" ]]; then
    RETRAIN_FLAG="--force-retrain"
fi

echo -e "\n${YELLOW}Wähle einen Optimierungs-Modus:${NC}"
echo "  1) Strenger Modus   (Calmar mit Constraints: DD, Win-Rate, PnL)"
echo "  2) 'Finde das Beste' (Max Calmar, nur DD-Constraint)"
read -p "Auswahl (1-2) [Standard: 1]: " OPTIM_MODE_CHOICE; OPTIM_MODE_CHOICE=${OPTIM_MODE_CHOICE:-1}

if [ "$OPTIM_MODE_CHOICE" == "1" ]; then
    OPTIM_MODE_ARG="strict"
    read -p "Max Drawdown % [Standard: 30]: " MAX_DD; MAX_DD=${MAX_DD:-30}
    read -p "Min Win-Rate % [Standard: 0 (Ignorieren)]: " MIN_WR; MIN_WR=${MIN_WR:-0}
    read -p "Min PnL % [Standard: 0]: " MIN_PNL; MIN_PNL=${MIN_PNL:-0}
else
    OPTIM_MODE_ARG="best_profit"
    read -p "Max Drawdown % [Standard: 50]: " MAX_DD; MAX_DD=${MAX_DD:-50}
    MIN_WR=0
    MIN_PNL=-99999
fi

# --- Schleife über Symbole und Zeitrahmen ---
for symbol in $SYMBOLS; do
    FULL_SYMBOL="${symbol}/USDT:USDT"
    for timeframe in $TIMEFRAMES; do
        echo -e "\n${BLUE}=======================================================${NC}"
        echo -e "${BLUE}  Pipeline für: $FULL_SYMBOL ($timeframe)${NC}"
        echo -e "${BLUE}=======================================================${NC}"

        echo -e "\n${GREEN}>>> Starte LSTM-Training + Optuna-Optimierung...${NC}"
        PYTHONPATH="$SCRIPT_DIR/src" "$PYTHON" "$OPTIMIZER" \
            --symbols "$FULL_SYMBOL" \
            --timeframes "$timeframe" \
            --limit "$LIMIT" \
            --start-capital "$START_CAPITAL" \
            --epochs "$EPOCHS" \
            --trials "$N_TRIALS" \
            --horizon "$HORIZON" \
            --neutral-zone "$NEUTRAL_ZONE" \
            --mode "$OPTIM_MODE_ARG" \
            --max-drawdown "$MAX_DD" \
            --min-win-rate "$MIN_WR" \
            --min-pnl "$MIN_PNL" \
            $RETRAIN_FLAG

        if [ $? -ne 0 ]; then
            echo -e "${RED}❌ Fehler für $FULL_SYMBOL ($timeframe). Überspringe...${NC}"
        else
            echo -e "${GREEN}✔ Pipeline für $FULL_SYMBOL ($timeframe) abgeschlossen.${NC}"
        fi
    done
done

echo -e "\n${BLUE}=======================================================${NC}"
echo -e "${BLUE}✔ Alle Pipelines abgeschlossen!${NC}"
echo -e "${BLUE}=======================================================${NC}"

# --- Interaktive Abfrage: Settings aktualisieren ---
echo -e "\n${YELLOW}Möchtest du die optimierten Strategien automatisch in settings.json übernehmen?${NC}"
echo -e "${YELLOW}(Dies ersetzt die aktuellen active_strategies mit den neu optimierten)${NC}"
read -p "Settings aktualisieren? (j/n) [Standard: n]: " UPDATE_SETTINGS_CHOICE
UPDATE_SETTINGS_CHOICE=${UPDATE_SETTINGS_CHOICE:-n}

if [[ "$UPDATE_SETTINGS_CHOICE" == "j" || "$UPDATE_SETTINGS_CHOICE" == "J" ]]; then
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
        if symbol and timeframe:
            exists = any(s.get('symbol') == symbol and s.get('timeframe') == timeframe for s in new_strategies)
            if not exists:
                new_strategies.append({"symbol": symbol, "timeframe": timeframe, "active": True})
                print(f"  + {symbol} ({timeframe})")
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

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✔ settings.json wurde erfolgreich aktualisiert!${NC}"
        echo -e "\n${YELLOW}Nächste Schritte:${NC}"
        echo -e "   1. settings.json prüfen: cat settings.json"
        echo -e "   2. secret.json: dbot API-Keys eintragen"
        echo -e "   3. Bot starten: .venv/bin/python3 master_runner.py"
    else
        echo -e "${RED}❌ Fehler beim Aktualisieren von settings.json${NC}"
    fi
else
    echo -e "${GREEN}✔ settings.json wurde NICHT verändert.${NC}"
    echo -e "${YELLOW}Tipp: Configs manuell prüfen in src/dbot/strategy/configs/config_*_lstm.json${NC}"
fi

deactivate

echo -e "\n${BLUE}=======================================================${NC}"
echo -e "${BLUE}✔ Pipeline abgeschlossen!${NC}"
echo -e "${BLUE}=======================================================${NC}"
