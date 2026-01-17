# DBot – Physics-Inspired Crypto Trading

Physik-inspirierter Crypto-Bot (15m–1d) mit VWAP-Mean-Reversion, Impuls-Pullback-Fortsetzung und Volatilitäts-Expansion. Multi-Coin, Multi-TF, Regime-Filter, MTF-Bias (Supertrend auf HTF).

## Quickstart (Windows)
- `cd dbot`
- `python -m venv .venv`
- `.venv\Scripts\activate`
- `pip install -r requirements.txt`
- `copy secret.json.template secret.json` und Keys eintragen

## Run
- Einzel-Instance: `python src/dbot/strategy/run.py --symbol BTC/USDT:USDT --timeframe 15m --use_macd false`
- Master Runner: `python master_runner.py` (startet alle aktiven Strategien aus [settings.json](settings.json))

## Strategie-Kerne
- **Signal vs. Rauschen**: VWAP, MAs als Low-Pass, Volumen-Filter (Energie)
- **Momentum & Ableitung**: Geschwindigkeit (Momentum) + Beschleunigung
- **Trägheit**: Impuls → Pullback → Fortsetzung
- **Energie & Phasenwechsel**: Volumen-Spikes, Volatilitäts-Expansion aus enger Range
- **Regime**: Trend/Range/Volatile via ATR% + EMA-Alignment
- **MTF**: HTF-Supertrend als Bias, LTF für Entry

## Setups
1) **VWAP + Energie (MR)**: Weit weg vom VWAP, Momentum flacht, Volumen-Spike → Revert zum VWAP
2) **Impuls → Pullback → Fortsetzung**: Starker Move, 38-50% Pullback, Momentum dreht → Trend-Continuation
3) **Volatilitäts-Expansion**: Enge Range mit niedrigem ATR, Breakout mit Volumen → 2-3x Range-Ziel

## Dateien (wichtig)
- [src/dbot/strategy/physics_engine.py](src/dbot/strategy/physics_engine.py): Indikatoren, Regime, Impuls/Range-Checks
- [src/dbot/strategy/trade_logic.py](src/dbot/strategy/trade_logic.py): Signal-Logik + SL/TP/Exit
- [src/dbot/utils/trade_manager.py](src/dbot/utils/trade_manager.py): Order-Flow, Risk/Reward, Trailing
- [src/dbot/strategy/run.py](src/dbot/strategy/run.py): Instanz-Loop
- [master_runner.py](master_runner.py): Multi-Instance Starter
- [settings.json](settings.json): Aktive Strategien + MACD-Dummy-Flag
- [src/dbot/strategy/configs/](src/dbot/strategy/configs/): Pro Symbol/TF Parameter

## Konfiguration
1) `secret.json`: Binance USDT-M Futures Keys unter `dbot` eintragen; Telegram optional
2) [settings.json](settings.json): Strategien aktivieren/deaktivieren (Symbol, TF, use_macd ignoriert das MACD-Feature)
3) Config pro Symbol/TF anpassen (Volumen-Threshold, VWAP-Distanz, ATR-Multiplikatoren, R/R, Leverage)

## Defaults (pro Config)
- SL = 1.2x ATR, TP = 1.8x ATR (2.5x bei Expansion)
- Leverage 3x, Risk fixed in USDT, Trailing bei 1.5R, Callback 0.5%
- Volume-Filter: Ratio >= 1.2; VWAP-Distanz MR: 2.0%

## Hinweise
- Trade-Lock verhindert Overtrading; Housekeeper räumt Orders/Positions auf
- HTF-Bias muss mit Entry-Richtung alignen (keine Trades gegen 1D-Supertrend)
- Erst auf Testnet prüfen, dann live

## Lizenz
Siehe [LICENSE](LICENSE).
