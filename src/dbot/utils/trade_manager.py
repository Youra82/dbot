# src/dbot/utils/trade_manager.py
# Adaptiert aus ltbbot für dbot (LSTM-Signale statt Envelope band_prices)
import logging
import time
import ccxt
import os
import json
from datetime import datetime
import sys
import pandas as pd
import ta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
TRACKER_DIR = os.path.join(PROJECT_ROOT, 'artifacts', 'tracker')
ARTIFACTS_DIR = os.path.join(PROJECT_ROOT, 'artifacts')

sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.utils.telegram import send_message
from dbot.utils.exchange import Exchange
from dbot.strategy.lstm_logic import get_lstm_signal

# --- Performance Tracking ---

def update_performance_stats(tracker_file_path, trade_result, logger):
    tracker_info = read_tracker_file(tracker_file_path)
    if 'performance' not in tracker_info:
        tracker_info['performance'] = {
            'total_trades': 0, 'winning_trades': 0, 'losing_trades': 0,
            'consecutive_losses': 0, 'consecutive_wins': 0, 'max_consecutive_losses': 0
        }
    perf = tracker_info['performance']
    perf['total_trades'] += 1
    if trade_result == 'win':
        perf['winning_trades'] += 1
        perf['consecutive_wins'] += 1
        perf['consecutive_losses'] = 0
    else:
        perf['losing_trades'] += 1
        perf['consecutive_losses'] += 1
        perf['consecutive_wins'] = 0
        perf['max_consecutive_losses'] = max(perf['max_consecutive_losses'], perf['consecutive_losses'])
    if perf['total_trades'] > 0:
        win_rate = (perf['winning_trades'] / perf['total_trades']) * 100
        perf['win_rate'] = win_rate
        if perf['total_trades'] >= 30 and win_rate < 30:
            logger.warning(f"SCHLECHTE PERFORMANCE: Win-Rate {win_rate:.1f}% nach {perf['total_trades']} Trades")
    update_tracker_file(tracker_file_path, tracker_info)


def should_reduce_risk(tracker_file_path):
    tracker_info = read_tracker_file(tracker_file_path)
    if 'performance' not in tracker_info:
        return False, "Keine Performance-Daten"
    perf = tracker_info['performance']
    if perf.get('consecutive_losses', 0) >= 5:
        return True, f"5+ aufeinanderfolgende Verluste ({perf['consecutive_losses']})"
    if perf.get('total_trades', 0) >= 30:
        win_rate = perf.get('win_rate', 50)
        if win_rate < 25:
            return True, f"Win-Rate zu niedrig: {win_rate:.1f}%"
    return False, "Performance OK"


# --- Tracker File Handling ---

def get_tracker_file_path(symbol, timeframe):
    os.makedirs(TRACKER_DIR, exist_ok=True)
    safe_filename = f"{symbol.replace('/', '-').replace(':', '-')}_{timeframe}.json"
    return os.path.join(TRACKER_DIR, safe_filename)


def read_tracker_file(file_path):
    default_data = {"status": "ok_to_trade", "last_side": None, "stop_loss_ids": []}
    if not os.path.exists(file_path):
        try:
            with open(file_path, 'w') as f:
                json.dump(default_data, f, indent=4)
        except Exception as write_err:
            logging.error(f"Konnte initiale Tracker-Datei nicht schreiben {file_path}: {write_err}")
        return default_data
    try:
        with open(file_path, 'r') as f:
            content = f.read()
            if not content:
                return default_data
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError):
        logging.error(f"Fehler beim Lesen der Tracker-Datei {file_path}. Setze auf Standard zurück.")
        try:
            with open(file_path, 'w') as f:
                json.dump(default_data, f, indent=4)
        except Exception:
            pass
        return default_data
    except Exception as e:
        logging.error(f"Unerwarteter Fehler beim Lesen von {file_path}: {e}")
        return default_data


def update_tracker_file(file_path, data):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4)
        logging.debug(f"Tracker-Datei aktualisiert: {file_path}")
    except Exception as e:
        logging.error(f"Fehler beim Schreiben der Tracker-Datei {file_path}: {e}")


# --- Order Management ---

def check_and_notify_new_position(exchange: Exchange, position: dict, params: dict,
                                   tracker_file_path: str, telegram_config: dict,
                                   logger: logging.Logger):
    """Prüft ob eine Position NEU eröffnet wurde und sendet Telegram-Benachrichtigung."""
    try:
        tracker_info = read_tracker_file(tracker_file_path)
        symbol = params['market']['symbol']
        timeframe = params['market']['timeframe']
        account_name = exchange.account.get('name', 'Standard-Account')

        current_entry_price = float(position.get('entryPrice', 0))
        current_side = position.get('side', '')
        current_contracts = float(position.get('contracts', 0))

        last_notified_entry = tracker_info.get('last_notified_entry_price')
        last_notified_side = tracker_info.get('last_notified_side')

        is_new_position = (
            last_notified_entry is None or
            last_notified_side is None or
            abs(current_entry_price - last_notified_entry) > (current_entry_price * 0.001) or
            current_side != last_notified_side
        )

        if is_new_position:
            unrealized_pnl = position.get('unrealizedPnl', 0)
            liquidation_price = position.get('liquidationPrice', 0)
            leverage = position.get('leverage', params['risk'].get('leverage', 1))
            margin_used = position.get('initialMargin', 0)

            tp_price = None
            sl_price = None
            try:
                open_triggers = exchange.fetch_open_trigger_orders(symbol)
                for order in open_triggers:
                    if order.get('reduceOnly'):
                        trigger_price = order.get('triggerPrice') or order.get('stopPrice')
                        order_side = order.get('side', '')
                        if trigger_price:
                            trigger_price = float(trigger_price)
                            if current_side == 'long' and order_side == 'sell':
                                if trigger_price > current_entry_price:
                                    tp_price = trigger_price
                                elif trigger_price < current_entry_price:
                                    sl_price = trigger_price
                            elif current_side == 'short' and order_side == 'buy':
                                if trigger_price < current_entry_price:
                                    tp_price = trigger_price
                                elif trigger_price > current_entry_price:
                                    sl_price = trigger_price
            except Exception as e:
                logger.warning(f"Konnte TP/SL-Preise nicht abrufen: {e}")

            side_emoji = "LONG" if current_side == 'long' else "SHORT"
            message = f"NEUE POSITION: {side_emoji}\n\n"
            message += f"Account: {account_name}\n"
            message += f"Symbol: {symbol} | TF: {timeframe}\n"
            message += f"Menge: {current_contracts:.4f} | Entry: {current_entry_price:.4f} USDT\n"
            message += f"Hebel: {leverage}x | Margin: {margin_used:.2f} USDT\n"
            if tp_price:
                tp_pct = abs((tp_price - current_entry_price) / current_entry_price * 100)
                message += f"TP: {tp_price:.4f} USDT (+{tp_pct:.2f}%)\n"
            if sl_price:
                sl_pct = abs((sl_price - current_entry_price) / current_entry_price * 100)
                message += f"SL: {sl_price:.4f} USDT (-{sl_pct:.2f}%)\n"
            if tp_price and sl_price:
                rr = abs(tp_price - current_entry_price) / abs(current_entry_price - sl_price)
                message += f"R:R 1:{rr:.2f}\n"
            message += f"P&L: {unrealized_pnl:.2f} USDT\n"
            if liquidation_price and liquidation_price > 0:
                message += f"Liquidation: {liquidation_price:.4f} USDT\n"
            message += f"Zeit: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            send_message(telegram_config.get('bot_token'), telegram_config.get('chat_id'), message)
            logger.info(f"Telegram-Benachrichtigung für NEUE Position gesendet: {current_side}")

            tracker_info['last_notified_entry_price'] = current_entry_price
            tracker_info['last_notified_side'] = current_side
            tracker_info['last_notified_timestamp'] = datetime.now().isoformat()
            update_tracker_file(tracker_file_path, tracker_info)
        else:
            logger.debug("Position bereits gemeldet. Keine neue Benachrichtigung.")
    except Exception as e:
        logger.error(f"Fehler beim Prüfen/Benachrichtigen neuer Position: {e}", exc_info=True)


def cancel_strategy_orders(exchange: Exchange, symbol: str, logger: logging.Logger,
                            tracker_file_path: str = None):
    """Storniert alle offenen Limit- und nicht-reduceOnly Trigger-Orders."""
    cancelled_count = 0
    try:
        orders = exchange.fetch_open_orders(symbol)
        for order in orders:
            try:
                exchange.cancel_order(order['id'], symbol)
                cancelled_count += 1
                time.sleep(0.1)
            except ccxt.OrderNotFound:
                pass
            except Exception as e:
                logger.warning(f"Konnte Order {order['id']} nicht stornieren: {e}")

        trigger_orders = exchange.fetch_open_trigger_orders(symbol)
        for order in trigger_orders:
            if order.get('reduceOnly'):
                continue
            try:
                exchange.cancel_trigger_order(order['id'], symbol)
                cancelled_count += 1
                time.sleep(0.1)
            except ccxt.OrderNotFound:
                pass
            except Exception as e:
                logger.warning(f"Konnte Trigger Order {order['id']} nicht stornieren: {e}")

        if cancelled_count > 0 and tracker_file_path:
            tracker_info = read_tracker_file(tracker_file_path)
            tracker_info["stop_loss_ids"] = []
            tracker_info["take_profit_ids"] = []
            update_tracker_file(tracker_file_path, tracker_info)

        return cancelled_count
    except Exception as e:
        logger.error(f"Fehler beim Stornieren der Orders für {symbol}: {e}", exc_info=True)
        return cancelled_count


def check_stop_loss_trigger(exchange: Exchange, symbol: str, tracker_file_path: str,
                             logger: logging.Logger) -> bool:
    """Prüft ob ein gesetzter SL ausgelöst wurde."""
    tracker_info = read_tracker_file(tracker_file_path)
    current_sl_ids = tracker_info.get("stop_loss_ids", [])
    if not current_sl_ids:
        return False

    try:
        closed_triggers = []
        if exchange.exchange.has.get('fetchClosedOrders'):
            params = {'stop': True} if 'bitget' in exchange.exchange.id else {}
            closed_triggers = exchange.exchange.fetchClosedOrders(symbol, limit=10, params=params)
            closed_triggers = [o for o in closed_triggers if o.get('stopPrice') is not None]
        elif exchange.exchange.has.get('fetchOrders'):
            params = {'stop': True} if 'bitget' in exchange.exchange.id else {}
            all_orders = exchange.exchange.fetchOrders(symbol, limit=20, params=params)
            closed_triggers = [o for o in all_orders if o.get('stopPrice') is not None and o['status'] in ['closed', 'canceled']]

        for closed_order in closed_triggers:
            if closed_order['id'] in current_sl_ids and closed_order.get('status') == 'closed':
                logger.warning(f"STOP LOSS ausgelöst für {symbol}! Order ID: {closed_order['id']}")
                pos_side = 'long' if closed_order['side'] == 'sell' else 'short'
                tracker_info = read_tracker_file(tracker_file_path)
                tracker_info.update({
                    "status": "stop_loss_triggered",
                    "last_side": pos_side,
                    "stop_loss_ids": [],
                })
                tracker_info.pop('last_notified_entry_price', None)
                tracker_info.pop('last_notified_side', None)
                update_tracker_file(tracker_file_path, tracker_info)
                return True

        return False
    except Exception as e:
        logger.error(f"Fehler beim Prüfen geschlossener SL-Orders für {symbol}: {e}", exc_info=True)
        return False


def check_take_profit_trigger(exchange: Exchange, symbol: str, tracker_file_path: str,
                               logger: logging.Logger) -> bool:
    """Prüft ob ein gesetzter TP ausgelöst wurde."""
    tracker_info = read_tracker_file(tracker_file_path)
    current_tp_ids = tracker_info.get("take_profit_ids", [])
    if not current_tp_ids:
        return False

    try:
        closed_triggers = []
        if exchange.exchange.has.get('fetchClosedOrders'):
            params = {'stop': True} if 'bitget' in exchange.exchange.id else {}
            closed_triggers = exchange.exchange.fetchClosedOrders(symbol, limit=10, params=params)
            closed_triggers = [o for o in closed_triggers if o.get('stopPrice') is not None]
        elif exchange.exchange.has.get('fetchOrders'):
            params = {'stop': True} if 'bitget' in exchange.exchange.id else {}
            all_orders = exchange.exchange.fetchOrders(symbol, limit=20, params=params)
            closed_triggers = [o for o in all_orders if o.get('stopPrice') is not None and o['status'] in ['closed', 'canceled']]

        for closed_order in closed_triggers:
            if closed_order['id'] in current_tp_ids and closed_order.get('status') == 'closed':
                logger.warning(f"TAKE PROFIT ausgelöst für {symbol}! Order ID: {closed_order['id']}")
                tracker_info.update({"status": "take_profit_triggered", "take_profit_ids": []})
                tracker_info.pop('last_notified_entry_price', None)
                tracker_info.pop('last_notified_side', None)
                update_tracker_file(tracker_file_path, tracker_info)
                return True

        return False
    except Exception as e:
        logger.error(f"Fehler beim Prüfen geschlossener TP-Orders für {symbol}: {e}", exc_info=True)
        return False


# --- Positions-Management ---

def manage_existing_position(exchange: Exchange, position: dict, lstm_signal: dict,
                              params: dict, tracker_file_path: str, logger: logging.Logger):
    """Verwaltet eine bestehende Position: Prüft und setzt TP/SL falls fehlend."""
    symbol = params['market']['symbol']
    risk_params = params['risk']
    pos_side = position['side']
    logger.info(f"Verwalte bestehende {pos_side}-Position für {symbol}.")

    open_triggers = exchange.fetch_open_trigger_orders(symbol)
    tp_exists = any(
        o.get('reduceOnly') and
        ((pos_side == 'long' and o.get('side') == 'sell' and float(o.get('triggerPrice', 0)) > float(position.get('entryPrice', 0))) or
         (pos_side == 'short' and o.get('side') == 'buy' and float(o.get('triggerPrice', 0)) < float(position.get('entryPrice', 0))))
        for o in open_triggers
    )
    sl_exists = any(
        o.get('reduceOnly') and
        ((pos_side == 'long' and o.get('side') == 'sell' and float(o.get('triggerPrice', 0)) < float(position.get('entryPrice', 0))) or
         (pos_side == 'short' and o.get('side') == 'buy' and float(o.get('triggerPrice', 0)) > float(position.get('entryPrice', 0))))
        for o in open_triggers
    )

    if tp_exists and sl_exists:
        logger.debug("TP und SL sind bereits gesetzt. Nichts zu tun.")
        return

    logger.warning(f"Sicherheits-Check: TP={tp_exists}, SL={sl_exists}. Fehlende Orders werden nachgetragen.")

    amount_contracts = float(position.get('contracts', 0))
    if amount_contracts == 0:
        logger.warning("Positionsgröße ist 0. Kann TP/SL nicht setzen.")
        return

    avg_entry_str = position.get('entryPrice', position.get('info', {}).get('avgOpenPrice'))
    if avg_entry_str is None:
        logger.error("Konnte Entry-Preis nicht ermitteln.")
        return
    avg_entry_price = float(avg_entry_str)

    sl_pct = risk_params['stop_loss_pct'] / 100.0
    new_sl_ids = []
    new_tp_ids = []

    try:
        if pos_side == 'long':
            sl_price = avg_entry_price * (1 - sl_pct)
            sl_side = 'sell'
            sl_distance = avg_entry_price - sl_price
            tp_price = avg_entry_price + (2 * sl_distance)
            tp_side = 'sell'
        else:
            sl_price = avg_entry_price * (1 + sl_pct)
            sl_side = 'buy'
            sl_distance = sl_price - avg_entry_price
            tp_price = avg_entry_price - (2 * sl_distance)
            tp_side = 'buy'

        if not tp_exists and sl_price > 0:
            tp_order = exchange.place_trigger_market_order(symbol, tp_side, amount_contracts, tp_price, reduce=True)
            if tp_order and 'id' in tp_order:
                new_tp_ids.append(tp_order['id'])
            logger.info(f"TP nachgetragen @ {tp_price:.4f}")
            time.sleep(0.1)

        if not sl_exists and sl_price > 0:
            sl_order = exchange.place_trigger_market_order(symbol, sl_side, amount_contracts, sl_price, reduce=True)
            if sl_order and 'id' in sl_order:
                new_sl_ids.append(sl_order['id'])
            logger.info(f"SL nachgetragen @ {sl_price:.4f}")

    except Exception as e:
        logger.error(f"Fehler beim Setzen von TP/SL: {e}", exc_info=True)

    tracker_info = read_tracker_file(tracker_file_path)
    if new_sl_ids:
        tracker_info["stop_loss_ids"] = new_sl_ids
    if new_tp_ids:
        tracker_info["take_profit_ids"] = new_tp_ids
    update_tracker_file(tracker_file_path, tracker_info)


# --- Entry Order Platzierung ---

def place_entry_orders(exchange: Exchange, lstm_signal: dict, params: dict, balance: float,
                        tracker_file_path: str, telegram_config: dict, logger: logging.Logger):
    """
    Platziert einen Entry-Order basierend auf dem LSTM-Signal.

    Im Gegensatz zu ltbbot (3 gestaffelte Layers) platziert dbot NUR 1 Entry
    (LSTM gibt genau ein Signal pro Zeitpunkt).
    """
    symbol = params['market']['symbol']
    risk_params = params['risk']
    behavior_params = params.get('behavior', {})

    side = lstm_signal.get('side')  # 'long', 'short', oder None

    if side is None:
        logger.info("LSTM: Kein Signal → keine Entry-Orders.")
        return

    if side == 'long' and not behavior_params.get('use_longs', True):
        logger.info("Longs deaktiviert. Überspringe.")
        return
    if side == 'short' and not behavior_params.get('use_shorts', True):
        logger.info("Shorts deaktiviert. Überspringe.")
        return

    leverage = risk_params['leverage']
    risk_per_entry_pct = risk_params.get('risk_per_entry_pct', 1.0)
    sl_pct = risk_params['stop_loss_pct'] / 100.0

    # Risiko-Reduktion bei schlechter Performance
    reduce_risk, risk_reason = should_reduce_risk(tracker_file_path)
    if reduce_risk:
        logger.warning(f"RISIKO-REDUKTION aktiv: {risk_reason}")
        leverage = max(1, leverage // 2)
        risk_per_entry_pct *= 0.5

    # Startkapital als Risikobasis
    initial_capital = params.get('initial_capital_live', balance if balance > 1 else 1000)
    risk_base_capital = initial_capital

    current_price = lstm_signal['entry_price']
    confidence = lstm_signal.get('confidence', 0.5)

    logger.info(
        f"LSTM Entry: {side.upper()} @ {current_price:.4f} | "
        f"Confidence: {confidence:.3f} | Leverage: {leverage}x | Capital: {risk_base_capital:.2f} USDT"
    )

    # Positionsgröße berechnen
    risk_amount_usd = risk_base_capital * (risk_per_entry_pct / 100.0)
    sl_distance_price = current_price * sl_pct
    if sl_distance_price <= 0:
        logger.warning("SL-Distanz <= 0. Überspringe Entry.")
        return

    amount_coins = risk_amount_usd / sl_distance_price

    # Mindest-Checks
    min_amount = exchange.fetch_min_amount_tradable(symbol)
    if amount_coins < min_amount:
        logger.warning(f"Menge {amount_coins:.6f} unter Minimum {min_amount:.6f}. Überspringe.")
        return

    MIN_NOTIONAL_USDT = 5.0
    notional = amount_coins * current_price
    if notional < MIN_NOTIONAL_USDT:
        logger.warning(f"Notional {notional:.2f} USDT unter Minimum {MIN_NOTIONAL_USDT} USDT. Überspringe.")
        return

    # Margin und Leverage setzen
    try:
        exchange.set_margin_mode(symbol, risk_params.get('margin_mode', 'isolated'))
        time.sleep(0.3)
        exchange.set_leverage(symbol, leverage, risk_params.get('margin_mode', 'isolated'))
        time.sleep(0.3)
    except Exception as e:
        logger.warning(f"Konnte Margin/Leverage nicht setzen: {e}")

    # Entry-Trigger-Preis (0.05% Delta für sofortige Ausführung)
    trigger_delta = 0.0005
    if side == 'long':
        order_side = 'buy'
        entry_trigger = current_price * (1 - trigger_delta)  # knapp unter aktuellem Preis
        entry_limit = current_price * (1 - trigger_delta * 2)
    else:
        order_side = 'sell'
        entry_trigger = current_price * (1 + trigger_delta)
        entry_limit = current_price * (1 + trigger_delta * 2)

    # SL und TP aus Signal
    sl_price = lstm_signal.get('sl_price') or (
        current_price * (1 - sl_pct) if side == 'long' else current_price * (1 + sl_pct)
    )
    tp_price = lstm_signal.get('tp_price') or (
        current_price + 2 * sl_distance_price if side == 'long' else current_price - 2 * sl_distance_price
    )

    new_sl_ids = []
    new_tp_ids = []

    try:
        # ZUERST TP platzieren (reduceOnly)
        tp_side = 'sell' if side == 'long' else 'buy'
        tp_order = exchange.place_trigger_market_order(symbol, tp_side, amount_coins, tp_price, reduce=True)
        if tp_order and 'id' in tp_order:
            new_tp_ids.append(tp_order['id'])
        logger.info(f"TP platziert @ {tp_price:.4f}")
        time.sleep(0.2)

        # SL platzieren (reduceOnly)
        sl_side = 'sell' if side == 'long' else 'buy'
        sl_order = exchange.place_trigger_market_order(symbol, sl_side, amount_coins, sl_price, reduce=True)
        if sl_order and 'id' in sl_order:
            new_sl_ids.append(sl_order['id'])
        logger.info(f"SL platziert @ {sl_price:.4f}")
        time.sleep(0.2)

        # Entry-Trigger-Limit Order
        entry_order = exchange.place_trigger_limit_order(
            symbol, order_side, amount_coins, entry_trigger, entry_limit, reduce=False
        )
        logger.info(f"Entry-Order platziert: {order_side.upper()} {amount_coins:.6f} @ Trigger {entry_trigger:.4f}")
        time.sleep(0.1)

    except ccxt.InsufficientFunds as e:
        logger.error(f"Nicht genügend Guthaben: {e}")
        cancel_strategy_orders(exchange, symbol, logger)
        return
    except Exception as e:
        logger.error(f"Fehler beim Platzieren der Entry-Orders: {e}", exc_info=True)
        cancel_strategy_orders(exchange, symbol, logger)
        return

    # Tracker aktualisieren
    tracker_info = read_tracker_file(tracker_file_path)
    tracker_info["stop_loss_ids"] = new_sl_ids
    tracker_info["take_profit_ids"] = new_tp_ids
    tracker_info["last_side"] = side
    update_tracker_file(tracker_file_path, tracker_info)

    logger.info(f"Entry-Orders erfolgreich platziert für {symbol} ({side.upper()}).")


# --- Haupt-Trading-Zyklus ---

def full_trade_cycle(exchange: Exchange, params: dict, telegram_config: dict,
                     logger: logging.Logger):
    """
    Vollständiger Handelszyklus für dbot (LSTM-Version).

    Ablauf:
    1. OHLCV-Daten holen
    2. LSTM-Signal berechnen
    3. TP/SL-Trigger prüfen
    4. Alte Entry-Orders stornieren
    5. Bestehende Position verwalten ODER neue Entries platzieren
    """
    symbol = params['market']['symbol']
    timeframe = params['market']['timeframe']
    risk_params = params['risk']
    seq_len = params.get('model', {}).get('sequence_length', 60)

    tracker_file_path = get_tracker_file_path(symbol, timeframe)

    # 1. OHLCV-Daten holen (genug für Features + seq_len)
    fetch_limit = seq_len + 200  # Puffer für Indicator-Berechnung
    logger.info(f"Hole {fetch_limit} OHLCV-Kerzen für {symbol} ({timeframe})...")
    df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=fetch_limit)
    if df is None or len(df) < seq_len + 50:
        logger.error(f"Zu wenig OHLCV-Daten ({len(df) if df is not None else 0}). Breche ab.")
        return

    # 2. LSTM-Signal berechnen
    lstm_signal = get_lstm_signal(df, params, ARTIFACTS_DIR)
    logger.info(
        f"Signal: side={lstm_signal['side']} | confidence={lstm_signal['confidence']:.3f} | "
        f"long_prob={lstm_signal['long_prob']:.3f} | short_prob={lstm_signal['short_prob']:.3f}"
    )

    # 3. TP/SL-Trigger prüfen
    sl_triggered = check_stop_loss_trigger(exchange, symbol, tracker_file_path, logger)
    if sl_triggered:
        logger.warning(f"SL ausgelöst für {symbol}. Cooldown aktiv.")
        update_performance_stats(tracker_file_path, 'loss', logger)

    tp_triggered = check_take_profit_trigger(exchange, symbol, tracker_file_path, logger)
    if tp_triggered:
        logger.info(f"TP ausgelöst für {symbol}. Gut gemacht!")
        update_performance_stats(tracker_file_path, 'win', logger)

    # 4. Alte Entry-Orders (nicht-reduceOnly) stornieren
    cancel_strategy_orders(exchange, symbol, logger, tracker_file_path=None)

    # 5. Bestehende Position prüfen
    open_positions = exchange.fetch_open_positions(symbol)

    if open_positions:
        position = open_positions[0]
        logger.info(f"Offene Position: {position.get('side')} @ {position.get('entryPrice')}")

        # Margin/Leverage setzen
        try:
            exchange.set_margin_mode(symbol, risk_params.get('margin_mode', 'isolated'))
            exchange.set_leverage(symbol, risk_params['leverage'], risk_params.get('margin_mode', 'isolated'))
        except Exception:
            pass

        # Benachrichtigung für neue Position
        check_and_notify_new_position(exchange, position, params, tracker_file_path, telegram_config, logger)

        # TP/SL nachsetzen falls fehlend
        manage_existing_position(exchange, position, lstm_signal, params, tracker_file_path, logger)

    else:
        # Tracker prüfen: Cooldown nach SL?
        tracker_info = read_tracker_file(tracker_file_path)
        status = tracker_info.get('status', 'ok_to_trade')

        if status == 'stop_loss_triggered':
            # Cooldown: Erst wieder handeln wenn LSTM das Gegenteil signalisiert
            last_side = tracker_info.get('last_side')
            current_signal_side = lstm_signal.get('side')

            if last_side and current_signal_side and current_signal_side != last_side:
                logger.info(f"Cooldown beendet: LSTM signalisiert {current_signal_side} (vorheriger SL war {last_side}).")
                tracker_info['status'] = 'ok_to_trade'
                update_tracker_file(tracker_file_path, tracker_info)
            else:
                logger.info(f"Cooldown aktiv nach SL ({last_side}). Aktuelles Signal: {current_signal_side}. Warte...")
                return

        # Keine Position und kein Cooldown → Neuen Entry prüfen
        balance = exchange.fetch_balance_usdt()
        logger.info(f"Verfügbares Guthaben: {balance:.2f} USDT")

        if balance < 5.0:
            logger.warning(f"Guthaben zu niedrig ({balance:.2f} USDT) für neue Position.")
            return

        place_entry_orders(exchange, lstm_signal, params, balance, tracker_file_path, telegram_config, logger)

    logger.info(f"Trade-Zyklus abgeschlossen für {symbol} ({timeframe}).")
