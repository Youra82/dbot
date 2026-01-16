# src/dbot/utils/trade_manager.py
"""
Trade Manager für DBot - Hochfrequenz Scalping
Angepasst für 1m/5m Timeframes mit aggressiverem Risk Management
"""
import logging
import time
import ccxt
import os
import json
import pandas as pd
import ta
import math

from dbot.utils.telegram import send_message
from dbot.utils.ann_model import create_ann_features
from dbot.utils.exchange import Exchange
from dbot.utils.supertrend_indicator import SuperTrendLocal
from dbot.utils.circuit_breaker import is_trading_allowed, update_circuit_breaker, get_circuit_breaker_status

# Pfade für die Lock-Datei definieren
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
LOCK_FILE_PATH = os.path.join(PROJECT_ROOT, 'artifacts', 'db', 'trade_lock.json')

# --------------------------------------------------------------------------- #
# Trade-Lock-Hilfsfunktionen
# --------------------------------------------------------------------------- #
def get_trade_lock(strategy_id):
    """Liest den Zeitstempel des letzten Trades für eine Strategie aus der Lock-Datei."""
    if not os.path.exists(LOCK_FILE_PATH):
        return None
    try:
        with open(LOCK_FILE_PATH, 'r') as f:
            locks = json.load(f)
        return locks.get(strategy_id)
    except (json.JSONDecodeError, FileNotFoundError):
        return None

def set_trade_lock(strategy_id, candle_timestamp):
    """Setzt eine Sperre für eine Strategie, um erneutes Handeln auf derselben Kerze zu verhindern."""
    os.makedirs(os.path.dirname(LOCK_FILE_PATH), exist_ok=True)
    locks = {}
    if os.path.exists(LOCK_FILE_PATH):
        try:
            with open(LOCK_FILE_PATH, 'r') as f:
                locks = json.load(f)
        except json.JSONDecodeError:
            locks = {}
    locks[strategy_id] = candle_timestamp.strftime('%Y-%m-%d %H:%M:%S')
    with open(LOCK_FILE_PATH, 'w') as f:
        json.dump(locks, f, indent=4)


# --------------------------------------------------------------------------- #
# Housekeeper & Helper
# --------------------------------------------------------------------------- #
def housekeeper_routine(exchange, symbol, logger):
    """Storniert alle offenen Orders und versucht, die Position zu schließen."""
    logger.info(f"Starte Aufräum-Routine für {symbol}...")

    # 1. Alle ORDERS stornieren
    try:
        cancelled_count = exchange.cleanup_all_open_orders(symbol)
        if cancelled_count > 0:
            logger.info(f"{cancelled_count} verwaiste Order(s) gefunden und storniert.")
    except Exception as e:
        logger.error(f"Fehler während der Order-Aufräumung: {e}")

    # 2. Position prüfen und schließen
    try:
        position = exchange.fetch_open_positions(symbol)
        if position:
            pos_info = position[0]
            close_side = 'sell' if pos_info['side'] == 'long' else 'buy'
            contracts = float(pos_info['contracts'])

            logger.warning(f"Housekeeper: Schließe verwaiste Position ({pos_info['side']} {contracts:.6f})...")
            exchange.create_market_order(symbol, close_side, contracts, {'reduceOnly': True})
            time.sleep(2)

            if exchange.fetch_open_positions(symbol):
                logger.error("Housekeeper: Position konnte nicht geschlossen werden!")
                return False
            else:
                logger.info(f"Housekeeper: {symbol} ist jetzt sauber.")
                return True
        else:
            logger.info(f"Housekeeper: {symbol} ist jetzt sauber.")
            return True
    except Exception as e:
        logger.error(f"Housekeeper-Fehler beim Positions-Management: {e}", exc_info=True)
        return False


# --------------------------------------------------------------------------- #
# Hauptfunktion: Trade öffnen (HOCHFREQUENZ-OPTIMIERT)
# --------------------------------------------------------------------------- #
def check_and_open_new_position(exchange: Exchange, model, scaler, params, telegram_config, logger):
    """
    Prüft auf neue Trade-Signale und öffnet Position.
    ANGEPASST für Hochfrequenz-Trading: Schärfere Filter, schnellere Exits.
    """
    symbol = params['market']['symbol']
    timeframe = params['market']['timeframe']
    strategy_id = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    account_name = exchange.account.get('name', 'Standard-Account')
    
    # *** CIRCUIT BREAKER CHECK (schärfer für DBot) ***
    current_balance = exchange.fetch_balance_usdt()
    circuit_status = update_circuit_breaker(current_balance)

    if circuit_status == 'STOP_ALL_TRADING':
        logger.critical("🚨 CIRCUIT BREAKER AKTIV - Trading gestoppt!")
        send_message(f"🚨 CIRCUIT BREAKER AUSGELÖST\n\nTrading wurde automatisch gestoppt!\nDrawdown: >7%\nBalance: {current_balance:.2f} USDT", telegram_config)
        return
    
    cb_status = get_circuit_breaker_status()
    reduced_flag = cb_status.get('reduced', False)
    reduction_factor = cb_status.get('reduction_factor', 1.0)

    if reduced_flag:
        logger.warning(f"⚠️  Drawdown Warning: Position Size wird reduziert (Factor={reduction_factor})")
    # *** ENDE CIRCUIT BREAKER CHECK ***

    logger.info("Suche nach neuen Signalen...")
    data = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=500)

    if len(data) < 2:
        logger.warning("Nicht genug Daten geladen. Überspringe.")
        return

    last_candle_timestamp = data.index[-2]
    last_trade_timestamp_str = get_trade_lock(strategy_id)
    if last_trade_timestamp_str and last_trade_timestamp_str == last_candle_timestamp.strftime('%Y-%m-%d %H:%M:%S'):
        logger.info(f"Signal für Kerze {last_candle_timestamp} wurde bereits gehandelt. Überspringe.")
        return

    data_with_features = create_ann_features(data.copy())

    # SuperTrend Richtung hinzufügen
    st_indicator = SuperTrendLocal(
        data_with_features['high'], 
        data_with_features['low'], 
        data_with_features['close'], 
        window=10, 
        multiplier=2.5  # Aggressiver für Hochfrequenz
    )
    st_direction = st_indicator.get_supertrend_direction().iloc[-2]

    # Feature-Liste (konsistent mit ann_model.py)
    feature_cols = [
        'bb_width', 'bb_pband', 'obv', 'rsi', 'macd_diff', 'macd', 
        'atr_normalized', 'adx', 'adx_pos', 'adx_neg',
        'volume_ratio', 'mfi', 'cmf',
        'price_to_ema20', 'price_to_ema50',
        'stoch_k', 'stoch_d', 'williams_r', 'roc', 'cci',
        'price_to_resistance', 'price_to_support',
        'high_low_range', 'close_to_high', 'close_to_low',
        'day_of_week', 'hour_of_day',
        'returns_lag1', 'returns_lag2', 'returns_lag3', 'hist_volatility'
    ]

    latest_features = data_with_features.iloc[-2:-1][feature_cols]

    if latest_features.isnull().values.any():
        logger.warning("Neueste Feature-Daten sind unvollständig, überspringe diesen Zyklus.")
        return

    scaled_features = scaler.transform(latest_features)
    prediction = model.predict(scaled_features, verbose=0)[0][0]
    pred_threshold = params['strategy']['prediction_threshold']
    side = None
    signal_reason = None

    # ANN-Signal prüfen
    if prediction >= pred_threshold and params.get('behavior', {}).get('use_longs', True):
        side = 'buy'
        signal_reason = f"Modell-Vorhersage {prediction:.3f} >= Schwelle {pred_threshold:.3f} (LONG)"
    elif prediction <= (1 - pred_threshold) and params.get('behavior', {}).get('use_shorts', True):
        side = 'sell'
        signal_reason = f"Modell-Vorhersage {prediction:.3f} <= Schwelle {1 - pred_threshold:.3f} (SHORT)"
    else:
        signal_reason = f"Modell-Vorhersage {prediction:.3f} -> Kein gültiges Signal"

    logger.info(f"Signal-Entscheidung für {symbol} @ {last_candle_timestamp}: {side if side else 'NEUTRAL'} | Grund: {signal_reason}")

    # SUPER TREND FILTER
    trade_allowed = True
    if side == 'buy':
        if st_direction != 1.0:
            trade_allowed = False
            logger.info(f"Signal (LONG) deaktiviert durch SuperTrend-Filter: Kein Long-Trend (st_direction={st_direction})")
    elif side == 'sell':
        if st_direction != -1.0:
            trade_allowed = False
            logger.info(f"Signal (SHORT) deaktiviert durch SuperTrend-Filter: Kein Short-Trend (st_direction={st_direction})")

    # HOCHFREQUENZ-FILTER: Schärfere Limits für 1m/5m
    if side and trade_allowed:
        last_candle = data_with_features.iloc[-2]
        
        # ADX-Filter: Höheres Minimum für Hochfrequenz
        current_adx = last_candle.get('adx', 0)
        adx_threshold = 25 if timeframe == '1m' else 20  # Schärfer für 1m
        if current_adx < adx_threshold:
            trade_allowed = False
            logger.info(f"Signal ({side.upper()}) deaktiviert durch ADX-Filter: ADX zu niedrig ({current_adx:.1f} < {adx_threshold})")
        
        # Volume-Filter: Mindestens 100% des Average Volume für Hochfrequenz
        if 'volume' in data_with_features.columns:
            current_volume = last_candle['volume']
            avg_volume = data_with_features['volume'].rolling(20).mean().iloc[-2]
            volume_threshold = 1.0 if timeframe == '1m' else 0.8
            if current_volume < avg_volume * volume_threshold:
                trade_allowed = False
                logger.info(f"Signal ({side.upper()}) deaktiviert durch Volumen-Filter: Volume zu niedrig")
        
        # RSI-Filter: Vermeide Überkauf/Überverkauf
        current_rsi = last_candle.get('rsi', 50)
        if side == 'buy' and current_rsi > 70:
            trade_allowed = False
            logger.info(f"Signal (LONG) deaktiviert: RSI überkauft ({current_rsi:.1f} > 70)")
        elif side == 'sell' and current_rsi < 30:
            trade_allowed = False
            logger.info(f"Signal (SHORT) deaktiviert: RSI überverkauft ({current_rsi:.1f} < 30)")
        
        # Momentum-Filter für use_momentum_filter
        if params.get('strategy', {}).get('use_momentum_filter', False):
            momentum = last_candle.get('roc', 0)  # Rate of Change
            if side == 'buy' and momentum < 0:
                trade_allowed = False
                logger.info(f"Signal (LONG) deaktiviert durch Momentum-Filter: Negativer Momentum")
            elif side == 'sell' and momentum > 0:
                trade_allowed = False
                logger.info(f"Signal (SHORT) deaktiviert durch Momentum-Filter: Positiver Momentum")

    # TRADE EXECUTION
    if side and trade_allowed:
        logger.info(f"✅ Gültiges Signal '{side.upper()}' für {symbol} @ {last_candle_timestamp} erkannt. Trade-Eröffnung wird gestartet.")
        p = params['risk']
        
        # Risk Management mit Circuit Breaker
        base_risk_pct = p['risk_per_trade_pct']
        if reduced_flag:
            applied_risk_pct = base_risk_pct * reduction_factor
        else:
            applied_risk_pct = base_risk_pct

        risk_per_trade_pct = applied_risk_pct / 100.0
        risk_reward_ratio = p['risk_reward_ratio']
        min_sl_pct = p.get('min_sl_pct', 0.3) / 100.0  # Enger für Hochfrequenz
        atr_multiplier_sl = p.get('atr_multiplier_sl', 1.5)  # Enger für Hochfrequenz
        leverage = p['leverage']
        activation_rr = p.get('trailing_stop_activation_rr', 1.5)  # Schneller aktivieren
        callback_rate_pct = p.get('trailing_stop_callback_rate_pct', 0.5) / 100.0  # Engerer Callback

        current_balance = exchange.fetch_balance_usdt()
        if current_balance <= 0:
            logger.error("Kein Guthaben zum Eröffnen.")
            return

        risk_amount_usd = current_balance * risk_per_trade_pct
        ticker = exchange.fetch_ticker(symbol)
        entry_price = ticker['last']
        
        # DYNAMISCHE SL-DISTANZ-BERECHNUNG (enger für Hochfrequenz)
        last_candle = data_with_features.iloc[-2]
        current_atr = last_candle.get('atr', 0.0)
        
        if current_atr <= 0:
            logger.error("ATR ist Null oder ungültig. Kann dynamischen SL nicht setzen.")
            return

        sl_distance_atr = current_atr * atr_multiplier_sl
        sl_distance_min = entry_price * min_sl_pct
        sl_distance = max(sl_distance_atr, sl_distance_min)

        if sl_distance == 0:
            logger.error("SL-Distanz Null.")
            return

        # Positionsgröße berechnen
        notional_value = risk_amount_usd / (sl_distance / entry_price)
        amount = notional_value / entry_price

        # Trigger-Preise berechnen
        stop_loss_price = entry_price - sl_distance if side == 'buy' else entry_price + sl_distance
        activation_price = entry_price + sl_distance * activation_rr if side == 'buy' else entry_price - sl_distance * activation_rr

        tsl_side = 'sell' if side == 'buy' else 'buy'
        take_profit_price = entry_price + sl_distance * risk_reward_ratio if side == 'buy' else entry_price - sl_distance * risk_reward_ratio

        # Trade-Eröffnung
        try:
            if not exchange.set_leverage(symbol, leverage):
                return
            if not exchange.set_margin_mode(symbol, p.get('margin_mode', 'isolated')):
                return

            order_params = {'marginMode': p['margin_mode']}
            exchange.create_market_order(symbol, side, amount, params=order_params)

            time.sleep(1)  # Kürzere Wartezeit für Hochfrequenz

            final_position = exchange.fetch_open_positions(symbol)
            if not final_position:
                raise Exception("Position konnte nicht bestätigt werden.")
            final_amount = float(final_position[0]['contracts'])

            sl_rounded = float(exchange.exchange.price_to_precision(symbol, stop_loss_price))
            activation_price_rounded = float(exchange.exchange.price_to_precision(symbol, activation_price))

            # 1. Fixen SL setzen (PRIORITÄT)
            logger.info(f"Platziere FIXEN SL @ {sl_rounded}")
            exchange.place_trigger_market_order(
                symbol, tsl_side, final_amount, sl_rounded, {'reduceOnly': True}
            )

            # 2. TSL als dynamischen TP setzen
            tsl_placed = False
            try:
                logger.info(f"Platziere TSL: Aktivierung @ {activation_price_rounded}, Callback @ {callback_rate_pct*100:.2f}%")
                tsl_order = exchange.place_trailing_stop_order(
                    symbol,
                    tsl_side,
                    final_amount,
                    activation_price_rounded,
                    callback_rate_pct,
                    {'reduceOnly': True}
                )
                if tsl_order:
                    tsl_placed = True
            except Exception as inner_e:
                logger.warning(f"WARNUNG: TSL-Platzierung fehlgeschlagen. Fixer SL aktiv. Fehler: {inner_e}")

            # Erfolgsnachricht
            set_trade_lock(strategy_id, last_candle_timestamp)

            tsl_status = f", TSL aktiv @ ${activation_price_rounded:.4f}" if tsl_placed else " (nur fixer SL)"

            message = (f"⚡ DBot HF Signal für *{account_name}* ({symbol}, {side.upper()})\n"
                      f"- Entry @ ${entry_price:.4f}\n"
                      f"- SL: ${sl_rounded:.4f}\n"
                      f"- TP: {tsl_status}")
            send_message(telegram_config.get('bot_token'), telegram_config.get('chat_id'), message)
            logger.info(f"Trade-Eröffnungsprozess abgeschlossen (SL gesetzt{tsl_status}).")

        except Exception as e:
            logger.error(f"FEHLER beim Eröffnen/SL-Platzierung: {e}")

            final_position_after_error = exchange.fetch_open_positions(symbol)
            if final_position_after_error:
                logger.critical("Position konnte nicht geschützt werden! Starte Notfallschließung.")
                housekeeper_routine(exchange, symbol, logger)

                fallback_msg = (f"❌ *Kritisch: Position geschlossen*\n"
                               f"SL-Platzierung fehlgeschlagen für *{symbol}*. "
                               f"Position wurde ZUR SICHERHEIT geschlossen.")
                send_message(telegram_config.get('bot_token'), telegram_config.get('chat_id'), fallback_msg)
            else:
                logger.info("Keine Position nach Fehler gefunden.")


def full_trade_cycle(exchange, model, scaler, params, telegram_config, logger):
    """Der Haupt-Handelszyklus für eine einzelne Strategie."""
    symbol = params['market']['symbol']
    try:
        position = exchange.fetch_open_positions(symbol)
        position = position[0] if position else None

        if not position:
            if not housekeeper_routine(exchange, symbol, logger):
                logger.error("Housekeeper konnte die Umgebung nicht säubern. Breche ab.")
                return
            check_and_open_new_position(exchange, model, scaler, params, telegram_config, logger)
        else:
            logger.info(f"Offene Position für {symbol} gefunden. Warte auf SL/TSL/TP-Trigger.")

    except ccxt.InsufficientFunds as e:
        logger.error(f"Fehler: Nicht genügend Guthaben. {e}")
    except Exception as e:
        logger.error(f"Unerwarteter Fehler im Handelszyklus: {e}", exc_info=True)
