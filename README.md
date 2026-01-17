# 🚀 DBot - Aggressive Scalping Trading Bot

<div align="center">

![DBot Logo](https://img.shields.io/badge/DBot-Aggressive-red?style=for-the-badge)
[![Python](https://img.shields.io/badge/Python-3.8+-green?style=for-the-badge&logo=python)](https://www.python.org/)
[![CCXT](https://img.shields.io/badge/CCXT-4.3.5-red?style=for-the-badge)](https://github.com/ccxt/ccxt)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

**⚡ Ein aggressiver High-Frequency Scalper für maximale Rendite auf Ultra-Short Timeframes (1m, 5m)**

⚠️ **HOCHRISIKO-STRATEGIE - NUR FÜR ERFAHRENE TRADER** ⚠️

[Features](#-features) • [Installation](#-installation) • [Konfiguration](#-konfiguration) • [Live-Trading](#-live-trading) • [Risiken](#️-wichtige-risiko-hinweise)

</div>

---

## 📊 Übersicht

**DBot** ist ein hochaggressiver Scalping-Bot basierend auf der bewährten **StBot-Architektur**, aber spezialisiert auf **Ultra-Short Timeframes** (1m, 5m) mit **moderatem bis hohem Leverage** (5-10x) für maximale Rendite in kürzester Zeit.

### ⚡ Kerncharakteristiken

- **Ultra-Short Timeframes**: 1m und 5m für viele Trades pro Stunde
- **Breakout-Basiert**: SMC-inspirierte Support/Resistance-Zonen + Volumen-Validierung  
- **Aggressive Parameter**: 
  - **Risk pro Trade**: 10-20% des Kontos
  - **Leverage**: 5-10x für maximale Rendite
  - **TP/SL Ratio**: 1:2 bis 1:3
- **24/7 Automation**: Läuft rund um die Uhr ohne manuelle Intervention
- **MTF-Bias**: Höhere Timeframes geben Trend-Richtung vor
- **Telegram-Alerts**: Live-Benachrichtigungen für jeden Trade

### 🎯 Trading-Logik (Kurzfassung)

1. **Signal-Engine**: Erkennt Breakouts an dynamischen S/R-Zonen (ähnlich StBot SMC)
2. **Volume-Filter**: Nur bei Volumen-Spikes traden (verhindert Fakeouts)
3. **Entry**: Auf Breakout-Close über Resistance / unter Support
4. **Stop-Loss**: Unter letztem Lower Low (für Longs) / ATR-basiert
5. **Take-Profit**: 2-5% schnelle Gewinne (maximaler Leverage-Profit)
6. **Trailing**: Nach +50% der SL-Distanz einen Trailing-Stop setzen

### 📈 Beispiel Trade (5m Timeframe)

```
Setup:
- ETH/USDT konsolidiert unter Resistance bei 2500 USDT
- Volumen nimmt zu
- Tagestren ist BULLISH (EMA20 > EMA50)

Entry:
- Kerze schließt über 2500 → BUY mit 10x Leverage
- Position Size: 10% Risk = ~$100 bei $1000 Konto

Stop-Loss & Take-Profit:
- SL: 20 USDT (unter Resistance) = -0.8% = -$8 Verlust
- TP: +60 USDT (3x SL) = +2.4% = +$24 Gewinn
- Risk:Reward = 1:3

Ausstieg:
- Trailing aktiviert bei +$12 Gewinn
- Bei neuem Lower Low ausgestopped

Dauer: 3-15 Minuten
```

---

## 🚀 Features

### Trading Features
- ✅ **Multi-Asset Aggressive Scalping** (BTC, ETH, SOL, DOGE, XRP, ADA, AAVE)
- ✅ **Ultra-Short Timeframes** (1m, 5m)
- ✅ **SMC-inspirierte Breakout-Strategie** mit Volumen-Validierung
- ✅ **Höchste Leverage** (5-10x möglich)
- ✅ **Aggressive Position-Sizing** (10-20% Risk pro Trade)
- ✅ **Quick TP/SL** (2-5% TP, 0.5-1% SL)
- ✅ **Trailing Stop Management**
- ✅ **MTF-Bias-Filter** (Trend von 4h/1d)
- ✅ **Automatische Trade-Verwaltung**
- ✅ **Telegram-Benachrichtigungen** in Echtzeit

### Technical Features
- ✅ **StBot-Architektur** (bewährte & stabile Basis)
- ✅ **CCXT Integration** (15+ Börsen supportiert)
- ✅ **Robustes Error-Handling** & Fallback-Mechanismen
- ✅ **Technische Indikatoren** (RSI, MACD, ATR, Bollinger Bands, SMC)
- ✅ **Walk-Forward-Testing** möglich
- ✅ **Docker-Ready** für 24/7 Deployment

---

## 📋 Systemanforderungen

### Hardware
- **CPU**: Dual-Core Prozessor
- **RAM**: Minimum 2GB, empfohlen 4GB+
- **Internet**: Stabile und schnelle Verbindung (für 1m Trades kritisch!)
- **Betriebssystem**: Linux (empfohlen), macOS oder Windows

### Software
- **Python**: 3.8 oder höher
- **Git**: Für Installation und Updates
- **Virtual Environment**: Empfohlen (venv)

### Börsen & Accounts
- **Börse**: Bitget (Standard), CCXT kompatible Börsen
- **Konto-Typ**: Futures/Perpetual (mit Margin/Leverage)
- **API Keys**: Read + Trade Permissions notwendig
- **2FA**: Dringend empfohlen für Sicherheit

---

## 💾 Installation

### 1️⃣ Repository klonen

```bash
cd ~/bots
git clone https://github.com/Youra82/dbot.git
cd dbot
```

### 2️⃣ Virtual Environment einrichten

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# oder
.venv\Scripts\activate  # Windows
```

### 3️⃣ Dependencies installieren

```bash
pip install -r requirements.txt
```

### 4️⃣ Geheimnisse & Einstellungen konfigurieren

#### **secret.json** erstellen
```json
{
  "dbot": [
    {
      "name": "Bitget Account",
      "exchange": "bitget",
      "apiKey": "YOUR_API_KEY",
      "secret": "YOUR_SECRET_KEY",
      "password": "YOUR_PASSPHRASE"
    }
  ],
  "telegram": {
    "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
    "chat_id": "YOUR_CHAT_ID"
  }
}
```

#### **settings.json** konfigurieren
```json
{
  "live_trading_settings": {
    "use_auto_optimizer_results": false,
    "active_strategies": [
      {
        "symbol": "BTC/USDT:USDT",
        "timeframe": "1m",
        "use_macd_filter": false,
        "active": true
      },
      {
        "symbol": "ETH/USDT:USDT",
        "timeframe": "5m",
        "use_macd_filter": false,
        "active": true
      }
    ]
  }
}
```

---

## ⚙️ Konfiguration

### Trading-Parameter (settings.json)

```json
{
  "trading_parameters": {
    "leverage": 8,                    // 5-10x empfohlen
    "risk_per_trade": 0.15,          // 10-20% Risk pro Trade
    "max_positions": 6,              // Max 6 offene Positionen
    "stop_loss_pct": 0.01,           // 1% SL für 1m/5m
    "take_profit_pct": 0.03,         // 3% TP
    "trailing_stop": true,           // Trailing aktivieren
    "volume_multiplier": 1.2         // 20% über Durchschnitt = Signal
  }
}
```

### MTF-Bias Konfiguration

DBot nutzt automatisch höhere Timeframes für Trend-Bestimmung:
- **1m Trades** → Bias von **5m** Chart
- **5m Trades** → Bias von **1h** oder **4h** Chart

Dies verhindert Trades gegen den Haupttrend.

---

## 🎮 Live-Trading

### Via Command Line

```bash
python src/dbot/strategy/run.py --symbol BTC/USDT:USDT --timeframe 1m --use_macd false
```

### Via Master Runner (mehrere Strategien)

```bash
./run_pipeline.sh
```

### Via Docker (Produktive Umgebung)

```bash
docker build -t dbot:latest .
docker run -d \
  -e DISCORD_WEBHOOK=... \
  -v $(pwd)/secret.json:/app/secret.json \
  -v $(pwd)/settings.json:/app/settings.json \
  dbot:latest
```

---

## 📊 Monitoring & Status

### Status-Check

```bash
./show_status.sh       # Aktive Positionen & P&L
```

### Ergebnisse & Charts

```bash
./show_results.sh      # Interaktive Backtest-Analyse
```

### Logs anschauen

```bash
tail -f logs/dbot_BTCUSDTUSDT_1m.log
```

### Telegram-Alerts aktiviert?

Jeder Trade/Order wird automatisch an Telegram gesendet (konfigurierbar in secret.json).

---

## ⚠️ Wichtige Risiko-Hinweise

### ‼️ KRITISCHE WARNUNGEN

1. **HOCHRISIKO-STRATEGIE**
   - Aggressive Parameter führen zu schnellen Gewinnen ABER auch schnellen Verlusten
   - Bankroll-Management ist KRITISCH
   - Niemals mehr als 1-2% Gesamtkapital pro Trade riskieren!

2. **Leverage-Risiko**
   - 5-10x Leverage = 5-10x Amplifikation von Gewinnen UND Verlusten
   - Liquidation möglich bei 50% Move gegen Position
   - Nur mit stabilen Internet- und API-Verbindungen nutzen

3. **Slippage & Gebühren**
   - Bei 1m Trades sind Slippage & Gebühren erheblich
   - Mindestens 0.2% Gebühren pro Trade
   - Echte Gewinne müssen Gebühren decken!

4. **Ultra-Short Timeframe Risiken**
   - **Whipsaws**: Schnelle Reversal können SL triggern
   - **Spreads**: Größere Bid/Ask Spreads bei volatilen Assets
   - **API-Probleme**: Zeitverzögerungen bei Börse = Slippage
   - **Reconnection**: Internet-Ausfälle = offene Positionen ohne Management

5. **NICHT für Anfänger**
   - Dieses System erfordert:
     - Tiefes Verständnis von Leverage & Margin
     - Psychologische Stabilität (viele Trades = emotionale Belastung)
     - Technisches Know-How (Server-Setup, API-Handling)
   - Empfehlung: Erst mit Paper-Trading / kleinem Geld starten!

### 💡 Best Practices

✅ **DO:**
- Mit **PAPIER-TRADING** starten
- Niemals **ganzes Kapital** riskieren
- **Stop-Loss** IMMER setzen
- **Telegram-Alerts** monitoring
- Logs regelmäßig **überprüfen**
- **Diversifizierung** über mehrere Paare
- **Backtesting** vor Live-Trading

❌ **DON'T:**
- Mit **Live-Geld** experimentieren
- **Alle Positionen** auf einem Asset
- **Hebel maximieren** (nutze 5-8x max)
- Bot **unbeaufsichtigt** laufen lassen
- **Secret Keys** in Code hardcoden
- In **illiquiden** Märkten traden

---

## 📈 Performance Erwartungen

### Realistische Szenarien

#### Conservative (5x Leverage, 10% TP, 1% SL, 50% Win-Rate)
- **Win pro Trade**: +0.5% Account
- **Loss pro Trade**: -0.5% Account
- **Expected Value**: 0% (zu konservativ für Scalping)

#### Moderate (8x Leverage, 5% TP, 1% SL, 55% Win-Rate)
- **Win pro Trade**: +0.4% Account
- **Loss pro Trade**: -0.5% Account
- **Expected Value**: +0.05% pro Trade
- **20 Trades/Tag**: +1% täglich = **260% jährlich** (vor Gebühren!)

#### Aggressive (10x Leverage, 3% TP, 0.5% SL, 60% Win-Rate)
- **Win pro Trade**: +0.3% Account
- **Loss pro Trade**: -0.5% Account
- **Expected Value**: -0.02% pro Trade (NEGATIV!)
- **Problem**: Win-Rate muss > 62.5% sein für Profit

### ⚡ Warum 1m/5m Scalping schwierig ist

- **Gebühren fressen Gewinne**: -0.2 bis -0.5% pro Transaktion
- **Slippage**: Zusätzliche -0.1% bis -0.5% pro Trade
- **Whipsaws**: Falsche Signale bei schnellen Reversals
- **Psyche**: Viele Trades = schnelle Emotionen

**Erwartung:** 5-20% monatlich NACH Gebühren (nicht 100%+!)

---

## 🔧 Troubleshooting

### Problem: "Virtual Environment nicht gefunden"
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Problem: "API Connection Fehler"
- Prüfe Internet-Verbindung
- Prüfe API Keys in secret.json
- Prüfe IP-Whitelist auf Börse
- Prüfe Rate Limits der API

### Problem: "Keine Signals generiert"
- Prüfe ob aktive_strategies in settings.json konfiguriert sind
- Prüfe ob Konfigurationsdateien in `src/dbot/strategy/configs/` existieren
- Schau Logs an: `tail -f logs/dbot_*.log`

### Problem: "Positive Trades aber negative P&L"
- **Wahrscheinliche Ursache**: Gebühren und Slippage
- Rechne: Gebühren = 0.05% Entry + 0.05% Exit = 0.1% pro Runde Trip
- Mit 5% TP und 0.1% Gebühren: Echte Gewinn = 4.9% (klein!)

---

## 📚 Weitere Ressourcen

- **StBot Dokumentation**: Siehe `../stbot/README.md`
- **CCXT Docs**: https://docs.ccxt.com/
- **Bitget API**: https://bitgetlimited.github.io/apidoc/
- **Trading Psychologie**: "Reminiscences of a Stock Operator" - Edwin Lefèvre

---

## 📄 Lizenz

MIT License - Siehe [LICENSE](LICENSE)

---

## ⚠️ Disclaimer

**DBot ist zu Bildungszwecken bestimmt. Kein Finanzberatung. Trading mit Leverage ist HOCHRISIKO. Autor übernimmt keine Haftung für Verluste.**

---

## 📞 Support

- **Issues**: GitHub Issues
- **Dokumentation**: README.md & inline Code-Kommentare
- **Community**: Telegram Bot Alerts

---

**Viel Erfolg beim Scalping! 🚀📈**
