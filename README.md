# 🧠 DBot - LSTM Deep Learning Trading Bot

<div align="center">

![DBot Logo](https://img.shields.io/badge/DBot-v1.0-blue?style=for-the-badge)
[![Python](https://img.shields.io/badge/Python-3.8+-green?style=for-the-badge&logo=python)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.1+-red?style=for-the-badge&logo=pytorch)](https://pytorch.org/)
[![CCXT](https://img.shields.io/badge/CCXT-4.3.5-orange?style=for-the-badge)](https://github.com/ccxt/ccxt)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

**Ein LSTM-basierter Deep-Learning Trading-Bot mit automatischer Modelloptimierung – erkennt Trends und zeitliche Muster direkt aus Marktdaten**

[Features](#-features) • [Installation](#-installation) • [Konfiguration](#-konfiguration) • [Pipeline](#-interaktive-pipeline) • [Live-Trading](#-live-trading) • [Analyse](#-analyse--show_resultssh) • [Wartung](#-wartung)

</div>

---

## 📊 Übersicht

DBot ist ein Deep-Learning Trading-Bot, der ein LSTM-Netzwerk (Long Short-Term Memory) verwendet, um aus historischen Kerzendaten direkt Long-, Short- oder Neutral-Signale zu erlernen. Das Modell verarbeitet 12 technische Features über ein rollierendes Zeitfenster und lernt zeitliche Abhängigkeiten, die klassische Indikatoren nicht erfassen.

### 🧭 Trading-Logik (Kurzfassung)
- **LSTM-Klassifikation**: Das Netzwerk gibt drei Wahrscheinlichkeiten aus (Long / Neutral / Short) — gehandelt wird, wenn eine Richtung den konfigurierten Threshold überschreitet
- **Feature Engineering**: 12 normalisierte Features (RSI, MACD, Bollinger, ATR, ADX, EMA-Abstände, Volume-Ratio, etc.) als Sliding-Window-Sequenz
- **Vollautomatische Pipeline**: `run_pipeline.sh` erledigt alles — Daten laden, LSTM trainieren, Grid-Suche über Horizon × Neutral-Zone (9 Kombinationen), beste Thresholds + Risikoparameter via Optuna optimieren, settings.json aktualisieren
- **Risk Engine**: Risiko-basierte Positionsgröße (% vom Startkapital / SL-Distanz), dynamisches R:R basierend auf LSTM-Konfidenz (rr_min bis rr_max, Optuna-optimiert), Stop-Loss + Take-Profit als Trigger-Market-Orders
- **Cooldown**: Nach einem Stop-Loss bleibt der Bot im Cooldown bis das LSTM die Gegenrichtung signalisiert
- **Execution**: CCXT für Bitget Futures (USDT-Margin, Isolated)

### 🔍 Architektur-Visualisierung
```mermaid
flowchart LR
    A["OHLCV Marktdaten\n(Bitget via CCXT)"]
    B["Feature Engineering\n12 Indikatoren\nRobustScaler"]
    C["LSTM Netzwerk\n60 Kerzen → hidden(128)\n→ Dense(64)"]
    D["Softmax Output\nlong_prob\nneutral_prob\nshort_prob"]
    E["Signal-Check\nProb > Threshold?"]
    F["Risk Engine\nPositionsgröße\nSL / TP Berechnung"]
    G["Order Router\nBitget API (CCXT)"]

    A --> B --> C --> D --> E --> F --> G
```

### 📐 Modell-Architektur
```
Input:  (batch, seq_len=60, n_features=12)
  → LSTM(hidden=128, layers=2, dropout=0.2, batch_first=True)
  → letzter Hidden-State
  → Dense(64, ReLU)
  → Dropout(0.3)
  → Dense(3, Softmax)
Output: [long_prob, neutral_prob, short_prob]
```

### 🏷️ Label-Generierung (Training)
```
return_pct = (close[t+horizon] - close[t]) / close[t] × 100

Label 0 = LONG    → return_pct > +neutral_zone%
Label 1 = NEUTRAL → |return_pct| ≤ neutral_zone%
Label 2 = SHORT   → return_pct < -neutral_zone%
```

---

## 🚀 Features

### Deep Learning Features
- ✅ PyTorch LSTM — erkennt zeitliche Muster in Preisreihen
- ✅ 12 technische Features: RSI, MACD, Bollinger Band Breite, ATR, ADX, EMA20/50 Abstand, Volume-Ratio, Log-Return, High-Low Range, Kerzenposition
- ✅ RobustScaler-Normalisierung (robust gegen Ausreißer)
- ✅ Klassen-gewichtete Loss-Funktion (ausgeglichen bei ungleicher Label-Verteilung)
- ✅ Early Stopping + Learning-Rate-Scheduler
- ✅ Walk-Forward Split (Train / Val / Test — kein Lookahead-Bias)
- ✅ Automatische Grid-Suche: Horizon × Neutral-Zone (9 Kombinationen, beste gewinnt)
- ✅ Predictor-Caching: Modell wird nur einmal pro Session geladen

### Trading Features
- ✅ 3-Klassen-Signal: Long / Neutral / Short mit konfigurierbaren Thresholds
- ✅ 1 Entry pro Signal (kein Layer-Stacking)
- ✅ Trigger-Limit Entry (0.05% Delta für quasi-sofortige Ausführung)
- ✅ Dynamisches Risk:Reward — R:R skaliert linear mit LSTM-Konfidenz (niedriges Signal → rr_min, hohes Signal → rr_max)
- ✅ rr_min und rr_max werden von Optuna optimiert und in der Config gespeichert
- ✅ Cooldown-Mechanismus nach Stop-Loss
- ✅ Risiko-Reduktion bei schlechter Performance (5+ Verluste in Folge → Hebel halbieren)
- ✅ Telegram-Benachrichtigungen (neue Position, Fehler)
- ✅ Performance-Tracking (Win-Rate, consecutive Losses)

### Technical Features
- ✅ CCXT Integration für Bitget Futures
- ✅ Optuna Optimierung (100+ Trials in Minuten, kein Re-Training): long_threshold, short_threshold, stop_loss_pct, leverage, risk_per_entry_pct, rr_min, rr_max
- ✅ Backtesting mit realistischer Slippage-Simulation (0.05%) + Fees (0.06%)
- ✅ Automatisches OHLCV-Caching (kein erneuter Download)
- ✅ Guardian-Decorator für kritische Fehlerbehandlung
- ✅ Rotating File Logger (5 MB, 3 Backups)
- ✅ Wöchentliches Auto-Re-Training via `auto_optimizer_scheduler.py`

---

## 📋 Systemanforderungen

### Hardware
- **CPU**: Multi-Core (Training auf CPU möglich, ~1–5 Min für 50 Epochen mit Early Stopping)
- **RAM**: Minimum 2 GB, empfohlen 4 GB+
- **Speicher**: 6–8 GB mit CUDA / ~600 MB CPU-only (PyTorch + Dependencies)
- **GPU**: Optional — automatisch genutzt wenn CUDA verfügbar (10–50x schneller)

### Software
- **OS**: Linux (Ubuntu 20.04+), macOS, Windows 10/11
- **Python**: 3.8 oder höher
- **Git**: Für Repository-Verwaltung

---

## 💻 Installation

### 1. Repository klonen

```bash
git clone https://github.com/Youra82/dbot.git
cd dbot
```

> **Einmalig nach dem Klonen** — Ausführungsrechte für alle Scripts setzen:
> ```bash
> chmod +x *.sh
> ```
> Danach sind `./update.sh`, `./install.sh`, `./run_pipeline.sh`, `./show_results.sh`, `./push_configs.sh` und `./run_tests.sh` direkt ausführbar.

### 2. Automatische Installation (empfohlen)

```bash
./install.sh
```

Das Install-Script:
- ✅ Erstellt `.venv` mit allen Dependencies
- ✅ Installiert PyTorch, CCXT, Optuna, scikit-learn, ta, pandas
- ✅ Legt `secret.json` aus Template an
- ✅ Erstellt alle Verzeichnisse (`artifacts/models/`, `logs/`, `data/`, etc.)
- ✅ Prüft PyTorch-Installation

> **Hinweis**: Auf GPU-Systemen lädt PyTorch alle CUDA-Libraries (~4 GB Download). Auf reinen CPU-VPS empfiehlt sich die CPU-only Variante: `pip install torch --index-url https://download.pytorch.org/whl/cpu`

### 3. API-Credentials konfigurieren

```bash
cp secret.json.example secret.json
nano secret.json
```

```json
{
    "dbot": [
        {
            "name": "Bitget-Main",
            "apiKey": "DEIN_API_KEY",
            "secret": "DEIN_API_SECRET",
            "password": "DEIN_API_PASSPHRASE"
        }
    ],
    "telegram": {
        "bot_token": "DEIN_BOT_TOKEN",
        "chat_id": "DEINE_CHAT_ID"
    }
}
```

⚠️ **Wichtig**:
- `secret.json` niemals committen (steht in `.gitignore`)
- Nur API-Keys mit Trading-Rechten — keine Withdrawal-Rechte!
- IP-Whitelist auf Bitget aktivieren

### 4. Trading-Strategien konfigurieren

```json
{
    "live_trading_settings": {
        "active_strategies": [
            {
                "symbol": "BTC/USDT:USDT",
                "timeframe": "4h",
                "active": false,
                "note": "Erst aktivieren nach: run_pipeline.sh"
            }
        ]
    }
}
```

**Parameter-Erklärung**:
- `symbol`: Handelspaar im Format `BASE/QUOTE:QUOTE`
- `timeframe`: Zeitrahmen (`15m`, `30m`, `1h`, `2h`, `4h`, `1d`)
- `active`: `false` lassen bis Modell trainiert und Backtest OK ist

---

## 🔁 Interaktive Pipeline

Die komplette Workflow wird durch `run_pipeline.sh` abgebildet — von Datenabruf bis zur fertigen Config und automatischer `settings.json`-Aktualisierung:

```bash
chmod +x run_pipeline.sh && ./run_pipeline.sh
```

### Was die Pipeline macht

`run_pipeline.sh` führt für jedes Symbol/Zeitfenster eine **automatische Grid-Suche** durch:

```
run_pipeline.sh
  ─────────────────────────────────────────────────────────────
  Für jedes Symbol × Zeitfenster:

  Grid-Suche: 3 Horizonte (3, 5, 10 Kerzen)
            × 3 Neutral-Zonen (0.2%, 0.3%, 0.5%)
            = 9 Kombinationen (automatisch)

  Pro Kombination → optimizer.py:

    1. Daten laden
       → OHLCV von Bitget (oder aus Cache wenn < 24h alt)
       → Kerzen-Limit automatisch: 5m/15m=2500 | 1h=2000 | 4h=1500 | 1d=1000
       → Chronologischer Split: 80% Training | 20% Optuna-Validierung

    2. LSTM Training (50 Epochen, Early Stopping)
       → 12 Features berechnen, Labels erstellen, RobustScaler fitten
       → Modell speichern: artifacts/models/BTCUSDTUSDT_4h.pt

    3. Optuna Optimierung (kein Re-Training pro Trial!)
       → long_threshold, short_threshold, stop_loss_pct,
         leverage, risk_per_entry_pct, rr_min, rr_max
       → Beste Config speichern: configs/config_BTCUSDTUSDT_4h_lstm.json

  → Kombination mit bestem Calmar-Ratio gewinnt
  → settings.json wird automatisch aktualisiert
  ─────────────────────────────────────────────────────────────
```

### Interaktive Eingaben

```
Alte Konfigurationen löschen? (j/n): n

Handelspaar(e) (ohne /USDT:USDT, z.B. BTC ETH): BTC ETH
Zeitfenster (z.B. 1h 4h): 4h

Startkapital USDT [1000]: 1000
Anzahl Optuna-Trials [100]: 100

Optimierungs-Modus:
  1) Strenger Modus   (Calmar + Constraints: DD, Win-Rate, PnL)
  2) Finde das Beste  (Max Calmar, nur DD-Constraint)
Auswahl: 1
Max Drawdown % [30]: 30
Min Win-Rate % [0]: 0
Min PnL % [0]: 0
```

> **Automatisch (kein Prompt):** Kerzen-Limit, Epochen (fest: 50), Horizon, Neutral-Zone, Neutraining, settings.json-Update

### Beispiel-Ausgabe (Grid-Suche)

```
Pipeline für: BTC/USDT:USDT (4h) | Limit: 1500 Kerzen
Grid-Suche: 3 Horizonte × 3 Zonen = 9 Kombinationen

[1/9] Testing horizon=3 | neutral_zone=0.2%
[2/9] Testing horizon=3 | neutral_zone=0.3%
  ✔ Neue beste Kombination! horizon=3 | neutral_zone=0.3% | Calmar=2.84
[3/9] Testing horizon=3 | neutral_zone=0.5%
...
[7/9] Testing horizon=10 | neutral_zone=0.2%
  ✔ Neue beste Kombination! horizon=10 | neutral_zone=0.2% | Calmar=3.41
...
✔ Beste Config gespeichert: BTC/USDT:USDT (4h) | Calmar=3.41
```

### Generierte Konfiguration

Nach der Pipeline liegt in `src/dbot/strategy/configs/`:

```json
{
    "market": {"symbol": "BTC/USDT:USDT", "timeframe": "4h"},
    "model": {
        "sequence_length": 60,
        "horizon_candles": 10,
        "neutral_zone_pct": 0.2,
        "long_threshold": 0.58,
        "short_threshold": 0.61,
        "rr_min": 1.4,
        "rr_max": 2.9
    },
    "risk": {
        "stop_loss_pct": 1.8,
        "leverage": 5,
        "risk_per_entry_pct": 1.0,
        "margin_mode": "isolated"
    },
    "behavior": {"use_longs": true, "use_shorts": true},
    "_backtest_metrics": {
        "trades": 87,
        "win_rate": 54.0,
        "pnl_pct": 42.3,
        "max_drawdown_pct": 14.1,
        "calmar_ratio": 3.41
    }
}
```

---

## 🔴 Live Trading

### Voraussetzungen

Bevor der Live-Bot gestartet wird:

1. ✅ `./run_pipeline.sh` erfolgreich abgeschlossen (Modell + Config vorhanden)
2. ✅ `./show_results.sh` → Modus 1 → Backtest-Ergebnisse geprüft
3. ✅ `settings.json` → `active: true` gesetzt (oder am Pipeline-Ende automatisch übernommen)
4. ✅ `secret.json` mit echten API-Keys ausgefüllt

### Manueller Start (Test)

```bash
cd /root/dbot && .venv/bin/python3 master_runner.py
```

### Automatischer Start (Cronjob)

```bash
crontab -e
```

```
# DBot Master-Runner alle 15 Minuten
*/15 * * * * /usr/bin/flock -n /root/dbot/dbot.lock /bin/sh -c "cd /root/dbot && .venv/bin/python3 master_runner.py >> /root/dbot/logs/cron.log 2>&1"
```

```bash
mkdir -p /root/dbot/logs
```

### Was der Master Runner macht

- ✅ Liest aktive Strategien aus `settings.json`
- ✅ Startet für jede Strategie einen separaten `run.py`-Prozess
- ✅ Holt OHLCV-Daten → berechnet Features → lädt LSTM-Modell → generiert Signal
- ✅ Prüft ob TP/SL ausgelöst wurde (Tracker-Dateien)
- ✅ Platziert Entry-Order (Trigger-Limit) + SL/TP (Trigger-Market, reduceOnly)
- ✅ Sendet Telegram-Benachrichtigung bei neuer Position
- ✅ Startet `auto_optimizer_scheduler.py` im Hintergrund (wöchentliches Re-Training)

### Einzelne Strategie manuell ausführen

```bash
cd /root/dbot
PYTHONPATH=src .venv/bin/python3 src/dbot/strategy/run.py --symbol BTC/USDT:USDT --timeframe 4h
```

---

## 📊 Analyse & `./show_results.sh`

```bash
chmod +x show_results.sh && ./show_results.sh
```

Alle 4 Modi fragen zuerst **Startdatum, Enddatum und Startkapital** ab (wie jaegerbot/stbot):

```
--- Konfiguration ---
Startdatum (JJJJ-MM-TT) [Standard: 2022-01-01]: 2024-01-01
Enddatum   (JJJJ-MM-TT) [Standard: Heute]:
Startkapital USDT         [Standard: 1000]: 15
Zeitraum: 2024-01-01 → 2026-03-04 | Kapital: 15 USDT
```

### 4 Analyse-Modi

| Modus | Beschreibung |
|-------|-------------|
| **1** | **Einzel-Analyse** — Backtest jeder trainierten Strategie isoliert im gewählten Zeitraum |
| **2** | **Portfolio-Simulation** — Manuelle Strategie-Auswahl, Kapital aufteilen, Gesamt-Performance |
| **3** | **Auto Portfolio-Optimierung** — Greedy-Algorithmus wählt automatisch das beste Strategien-Team (max. Profit bei gewünschtem Max-Drawdown) und schreibt es in `settings.json` |
| **4** | **Interaktive Charts** — OHLCV-Candlestick + LSTM Entry/Exit-Signale + Equity Curve als interaktive HTML-Datei, optional via Telegram versenden |

### Modus 1 — Einzel-Analyse

```
Strategie           Zeitraum                  Trades  Win-Rate  PnL %  Max DD %  Calmar  Endkapital
BTC/USDT:USDT (4h)  2024-01-01 → 2026-03-04      87     54.0%  +42.3%    14.1%    3.41  1423 USDT
ETH/USDT:USDT (4h)  2024-01-01 → 2026-03-04      63     51.6%  +18.7%    11.2%    1.67  1187 USDT
```

### Modus 2 — Portfolio-Simulation

Manuelle Strategie-Auswahl (wie stbot):

```
Verfügbare Strategien:
  1) BTC/USDT:USDT (4h) ✓
  2) ETH/USDT:USDT (4h) ✓
  3) XRP/USDT:USDT (4h) ✓

Welche Strategien simulieren? (Zahlen mit Komma, z.B. 1,2 oder 'alle'): 1,2

--- Portfolio-Gesamt ---
Zeitraum:          2024-01-01 bis 2026-03-04
Startkapital:      1000.00 USDT
Endkapital:        1305.00 USDT
Gesamt PnL:        +305.00 USDT (+30.5%)
Anzahl Trades:     150
Win-Rate:          52.7%
Portfolio Max DD:  14.1%
Liquidiert:        NEIN
```

### Modus 3 — Auto Portfolio-Optimierung

```
Gewünschter maximaler Drawdown in % [Standard: 30]: 20

1/3: Analysiere Einzel-Performance & filtere nach Max DD...
2/3: Beste Einzelstrategie: config_BTCUSDTUSDT_4h_lstm.json (Endkapital: 1423.00 USDT, Max DD: 14.1%)
3/3: Suche optimales Team...
  -> Füge hinzu: config_XRPUSDTUSDT_6h_lstm.json (Neues Kapital: 1389.00 USDT, Max DD: 17.3%)

Optimales Portfolio (2 Strategie(n)):
  - config_BTCUSDTUSDT_4h_lstm.json
  - config_XRPUSDTUSDT_6h_lstm.json

Endkapital: 1389.00 USDT | PnL: +38.9% | Portfolio Max DD: 17.3%

Sollen die optimalen Ergebnisse automatisch in settings.json eingetragen werden? (j/n): j
✅ 2 Strategie(n) wurden in settings.json eingetragen
```

### Modus 4 — Interaktive Charts

```
Verfuegbare Konfigurationen:
  1) BTCUSDTUSDT_1d
  2) BTCUSDTUSDT_4h
  3) XRPUSDTUSDT_6h
  ...
Auswahl: 2

Letzten N Tage anzeigen [leer=alle]: 90
Telegram versenden? (j/n): j

INFO: 87 Trades gefunden
INFO: Chart gespeichert: artifacts/charts/dbot_BTCUSDTUSDT_4h.html
INFO: Chart via Telegram versendet
```

Erzeugte HTML-Datei enthält:
- OHLCV-Candlesticks (interaktiv, zoombar)
- Entry Long (grünes Dreieck ▲), Exit Long (Cyan Kreis ●)
- Entry Short (oranges Dreieck ▼), Exit Short (rotes Diamant ◆)
- Kontostand-Kurve (blaue Linie, rechte Y-Achse)

---

## 📂 Projekt-Struktur

```
dbot/
├── src/
│   └── dbot/
│       ├── model/                     # Deep Learning Komponenten
│       │   ├── lstm_model.py          # PyTorch LSTM Architektur
│       │   ├── feature_engineering.py # 12 Features + Labels + Scaler
│       │   ├── trainer.py             # Training-Loop, Early Stopping
│       │   └── predictor.py           # Live-Inference mit Caching
│       ├── strategy/                  # Trading-Logik
│       │   ├── run.py                 # Entry Point je Strategie
│       │   ├── lstm_logic.py          # Signal aus LSTM-Probs + dyn. R:R
│       │   └── configs/               # Generierte JSON-Configs
│       ├── analysis/                  # Analyse & Optimierung
│       │   ├── backtester.py          # Backtest-Engine
│       │   ├── optimizer.py           # LSTM Training + Optuna (intern)
│       │   └── show_results.py        # 4-Modi Analyse-Tool
│       └── utils/                     # Infrastruktur
│           ├── exchange.py            # Bitget CCXT-Wrapper
│           ├── trade_manager.py       # Trade-Zyklus, TP/SL, Tracker
│           ├── telegram.py            # Benachrichtigungen
│           └── guardian.py            # Fehler-Decorator
├── artifacts/
│   ├── models/                        # Trainierte Modelle (.pt + _scaler.pkl)
│   ├── results/                       # Optimizer-Zeitplan
│   └── tracker/                       # Per-Strategie Status-Dateien
├── data/                              # OHLCV-Cache (CSV)
├── logs/                              # Rotating Log-Files
├── master_runner.py                   # Cronjob-Orchestrator
├── auto_optimizer_scheduler.py        # Wöchentliches Re-Training
├── run_pipeline.sh                    # Vollautomatische Pipeline (empfohlen)
├── show_results.sh                    # 4-Modi Analyse
├── push_configs.sh                    # Optimierte Configs ins Repo pushen (vom VPS)
├── run_tests.sh                       # Pytest Sicherheitsnetz
├── install.sh                         # Ersteinrichtung
├── update.sh                          # Git-Update mit secret.json Backup
├── settings.json                      # Strategie-Konfiguration
├── secret.json                        # API-Keys (nicht committen!)
├── secret.json.example                # Template für secret.json
└── requirements.txt                   # Python-Abhängigkeiten
```

---

## 🛠️ Wartung & Pflege

### Logs ansehen

```bash
# Master Runner live
tail -f logs/cron.log

# Spezifische Strategie
tail -f logs/dbot_BTCUSDTUSDT_4h.log

# Nach Fehlern suchen
grep -i "ERROR\|CRITICAL" logs/dbot_*.log
```

### Modell neu trainieren

```bash
# Pipeline neu starten (empfohlen) — findet automatisch beste Konfiguration
chmod +x run_pipeline.sh && ./run_pipeline.sh

# Oder direkt via optimizer.py:
PYTHONPATH=src .venv/bin/python3 src/dbot/analysis/optimizer.py \
    --symbols BTC/USDT:USDT --timeframes 4h \
    --epochs 50 --trials 200 --force-retrain
```

### Configs nach Pipeline ins Repo pushen

Nach `./run_pipeline.sh` liegen neue optimierte Config-Dateien in `src/dbot/strategy/configs/` — nur auf dem VPS, noch nicht im Repo. Mit `push_configs.sh` werden sie commited und gepusht:

```bash
chmod +x push_configs.sh && ./push_configs.sh
```

Typischer Ablauf:

```
Prüfe auf geänderte Konfigurationsdateien...
  Geändert: src/dbot/strategy/configs/config_BTCUSDTUSDT_4h_lstm.json
  Neu:      src/dbot/strategy/configs/config_XRPUSDTUSDT_6h_lstm.json
Committe und pushe Konfigurationen...
✅ Konfigurationen erfolgreich gepusht.
```

> **Hinweis**: Falls der Push abgelehnt wird (Remote hat neuere Commits), zuerst `git pull --rebase` ausführen.

### Caches leeren

```bash
# Gespeichertes Modell löschen (erzwingt Re-Training)
rm -f artifacts/models/BTCUSDTUSDT_4h.pt artifacts/models/BTCUSDTUSDT_4h_scaler.pkl

# OHLCV-Cache leeren (neuer Download von Bitget)
rm -f data/BTCUSDTUSDT_4h.csv

# Optimizer-Zeitplan zurücksetzen
rm -f artifacts/results/optimizer_schedule.json
```

### Cooldown zurücksetzen

Wenn der Bot nach einem SL im Cooldown hängt:

```bash
python3 -c "
import json
with open('artifacts/tracker/BTC-USDT-USDT_4h.json') as f:
    t = json.load(f)
t['status'] = 'ok_to_trade'
with open('artifacts/tracker/BTC-USDT-USDT_4h.json', 'w') as f:
    json.dump(t, f, indent=4)
print('OK')
"
```

### Bot aktualisieren

```bash
chmod +x update.sh && ./update.sh
```

Das Update-Script:
- Sichert `secret.json`
- `git reset --hard origin/master`
- Stellt `secret.json` wieder her
- Bereinigt Python-Cache
- Setzt Ausführungsrechte

⚠️ **Hinweis**: Trainierte Modelle (`.pt`, `.pkl`) und Configs (`configs/*.json`) bleiben erhalten — sie stehen in `.gitignore`.

### Tests ausführen

```bash
chmod +x run_tests.sh && ./run_tests.sh

# Spezifisch
PYTHONPATH=src .venv/bin/python3 -m pytest tests/ -v
```

---

## 🔄 Auto-Optimizer (wöchentliches Re-Training)

Der `auto_optimizer_scheduler.py` läuft automatisch im Hintergrund wenn der Master Runner startet. Er prüft, ob für jede aktive Strategie ein Re-Training fällig ist.

### Verhalten

- **Intervall**: 7 Tage (konfigurierbar in `settings.json`)
- **Ablauf**: `optimizer.py --force-retrain` → LSTM neu trainieren + neue Config speichern
- **Zeitplan**: wird in `artifacts/results/optimizer_schedule.json` gespeichert

### Manuell triggern

```bash
# Zeitplan zurücksetzen → Re-Training beim nächsten Master-Runner-Start
rm artifacts/results/optimizer_schedule.json

# Oder direkt ausführen
PYTHONPATH=src .venv/bin/python3 auto_optimizer_scheduler.py
```

### In `settings.json` konfigurieren

```json
"optimization_settings": {
    "enabled": true,
    "interval_days": 7,
    "start_capital": 1000,
    "num_trials": 100,
    "val_split": 0.2
}
```

---

## ⚠️ Wichtige Hinweise

### Risiko-Disclaimer

⚠️ **Trading mit Kryptowährungen birgt erhebliche Risiken!**

- Nur Kapital einsetzen, dessen Verlust Sie verkraften können
- LSTM-Modelle können in ungesehenen Marktregimes versagen
- Vergangene Backtest-Performance ≠ zukünftige Live-Performance
- Testen Sie ausgiebig im Paper-Trading / mit kleinen Beträgen
- `initial_capital_live` in der Config realistisch setzen

### Security Best Practices

- 🔐 Niemals API-Keys mit Withdrawal-Rechten verwenden
- 🔐 IP-Whitelist auf Bitget aktivieren
- 🔐 `secret.json` niemals committen (steht in `.gitignore`)
- 🔐 Trainierte Modelle (`.pt`) niemals committen (stehen in `.gitignore`)
- 🔐 2FA für Bitget-Account aktivieren

### Performance-Tipps

- 💡 Mit 1 Strategie starten und Logs beobachten
- 💡 `show_results.sh` → Modus 3 für aktuelles Signal prüfen bevor Strategie aktiviert wird
- 💡 Val Accuracy > 52% ist ein gutes Zeichen — darunter → mehr Daten oder anderen Timeframe
- 💡 Calmar Ratio > 1.5 anstreben — darunter lohnt sich Live-Trading kaum
- 💡 Regelmäßig `show_results.sh` → Modus 4 aufrufen um Tracker zu prüfen

---

## 🤝 Support

### Probleme melden

1. Logs prüfen: `grep -i "ERROR" logs/dbot_*.log`
2. Tests ausführen: `./run_tests.sh`
3. Modell-Info prüfen: `./show_results.sh` → Modus 3
4. Issue öffnen mit Log-Auszügen

### Updates

```bash
git fetch origin
git status
./update.sh
```

---

## 📜 Lizenz

Dieses Projekt ist lizenziert unter der MIT License.

---

## 🙏 Credits

Entwickelt mit:
- [PyTorch](https://pytorch.org/)
- [CCXT](https://github.com/ccxt/ccxt)
- [Optuna](https://optuna.org/)
- [Pandas](https://pandas.pydata.org/)
- [TA-Lib (ta)](https://github.com/bukosabino/ta)
- [scikit-learn](https://scikit-learn.org/)

---

<div align="center">

**Made with ❤️ by the DBot Team**

⭐ Star uns auf GitHub wenn dir dieses Projekt gefällt!

[🔝 Nach oben](#-dbot---lstm-deep-learning-trading-bot)

</div>
