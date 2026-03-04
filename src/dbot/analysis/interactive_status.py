#!/usr/bin/env python3
"""
Interactive Charts für dbot LSTM
Zeigt Candlestick-Chart mit LSTM Trade-Signale (Entry/Exit Long/Short) + Equity Curve
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

# Konstanten (analog backtester.py, kein torch-Import nötig)
FEE_PCT = 0.0006
SLIPPAGE_PCT = 0.0005


def _dynamic_rr(confidence, threshold, rr_min=1.5, rr_max=3.0):
    conf_range = 1.0 - threshold
    if conf_range <= 0:
        return rr_min
    t = max(0.0, min(1.0, (confidence - threshold) / conf_range))
    return rr_min + t * (rr_max - rr_min)

logger = logging.getLogger('interactive_status')
if not logger.handlers:
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(ch)


# ---------------------------------------------------------------------------
# Config-Auswahl
# ---------------------------------------------------------------------------

def get_config_files():
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    if not os.path.exists(configs_dir):
        return []
    return sorted(
        [(f, os.path.join(configs_dir, f))
         for f in os.listdir(configs_dir)
         if f.startswith('config_') and f.endswith('_lstm.json')]
    )


def select_configs():
    configs = get_config_files()
    if not configs:
        logger.error("Keine Konfigurationsdateien gefunden!")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Verfuegbare Konfigurationen:")
    print("=" * 60)
    for idx, (filename, _) in enumerate(configs, 1):
        clean = filename.replace('config_', '').replace('_lstm.json', '')
        print(f"{idx:2d}) {clean}")
    print("=" * 60)
    print("\nWaehle Konfiguration(en) zum Anzeigen:")
    print("  Einzeln:  z.B. '1' oder '5'")
    print("  Mehrfach: z.B. '1,3,5' oder '1 3 5'")
    print("  Alle:     'alle'")

    selection = input("\nAuswahl: ").strip()
    if selection.lower() == 'alle':
        return configs

    selected = []
    for part in selection.replace(',', ' ').split():
        try:
            idx = int(part)
            if 1 <= idx <= len(configs):
                selected.append(configs[idx - 1])
            else:
                logger.warning(f"Index {idx} ausserhalb des Bereichs")
        except ValueError:
            logger.warning(f"Ungueltige Eingabe: {part}")

    if not selected:
        logger.error("Keine gueltigen Konfigurationen gewaehlt!")
        sys.exit(1)

    return selected


# ---------------------------------------------------------------------------
# OHLCV-Daten laden
# ---------------------------------------------------------------------------

def load_ohlcv(symbol, timeframe, start_date=None, end_date=None):
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cache_path = os.path.join(PROJECT_ROOT, 'data', f"{safe_name}.csv")

    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        logger.info(f"Cache geladen: {safe_name} ({len(df)} Kerzen)")
    else:
        logger.info(f"Lade Kerzen von Exchange: {symbol} ({timeframe})...")
        try:
            with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
                secrets = json.load(f)
            account = secrets.get('dbot', [{}])[0]
            from dbot.utils.exchange import Exchange
            exchange = Exchange(account)
            df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=2000)
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            df.to_csv(cache_path)
        except Exception as e:
            logger.error(f"Konnte Daten nicht laden: {e}")
            return None

    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    if start_date:
        df = df[df.index >= pd.Timestamp(start_date, tz='UTC')]
    if end_date:
        df = df[df.index < pd.Timestamp(end_date, tz='UTC') + pd.Timedelta(days=1)]
    return df


# ---------------------------------------------------------------------------
# Trades aus LSTM-Backtest extrahieren (für Chart-Markierungen)
# ---------------------------------------------------------------------------

def extract_trades_lstm(df, predictor, config, start_capital):
    """
    Fuehrt LSTM-Simulation durch und gibt Trade-Liste zurueck.
    Jeder Trade: {side, entry_time, entry_price, exit_time, exit_price, pnl_usd}
    """
    from dbot.model.feature_engineering import compute_features, apply_scaler
    model_cfg = config.get('model', {})
    risk_cfg = config['risk']

    long_threshold = model_cfg.get('long_threshold', 0.55)
    short_threshold = model_cfg.get('short_threshold', 0.55)
    rr_min = model_cfg.get('rr_min', 1.5)
    rr_max = model_cfg.get('rr_max', 3.0)
    sl_pct = risk_cfg['stop_loss_pct'] / 100.0
    leverage = risk_cfg.get('leverage', 5)
    risk_per_entry_pct = risk_cfg.get('risk_per_entry_pct', 1.0)
    use_longs = config.get('behavior', {}).get('use_longs', True)
    use_shorts = config.get('behavior', {}).get('use_shorts', True)

    feature_df = compute_features(df)
    if len(feature_df) < predictor.seq_len + 10:
        logger.warning("Zu wenig Daten fuer Trade-Extraktion.")
        return []

    scaled_df = apply_scaler(feature_df, predictor.scaler)
    all_probs = predictor.predict_batch(scaled_df)

    pred_index = feature_df.index[predictor.seq_len:]
    ohlcv_pred = df.loc[pred_index].copy()
    ohlcv_pred['long_prob'] = all_probs[:, 0]
    ohlcv_pred['short_prob'] = all_probs[:, 2]

    ohlcv_pred['signal'] = 0
    ohlcv_pred.loc[
        (ohlcv_pred['long_prob'] > long_threshold) &
        (ohlcv_pred['long_prob'] > ohlcv_pred['short_prob']),
        'signal'
    ] = 1
    ohlcv_pred.loc[
        (ohlcv_pred['short_prob'] > short_threshold) &
        (ohlcv_pred['short_prob'] > ohlcv_pred['long_prob']),
        'signal'
    ] = -1

    if not use_longs:
        ohlcv_pred.loc[ohlcv_pred['signal'] == 1, 'signal'] = 0
    if not use_shorts:
        ohlcv_pred.loc[ohlcv_pred['signal'] == -1, 'signal'] = 0

    capital = start_capital
    position = None
    trades = []

    for ts, row in ohlcv_pred.iterrows():
        current_price = float(row['close'])
        signal = int(row['signal'])

        if position is not None:
            pos_side = position['side']
            hit_sl = (pos_side == 'long' and current_price <= position['sl_price']) or \
                     (pos_side == 'short' and current_price >= position['sl_price'])
            hit_tp = (pos_side == 'long' and current_price >= position['tp_price']) or \
                     (pos_side == 'short' and current_price <= position['tp_price'])

            if hit_sl or hit_tp:
                exit_price = position['sl_price'] if hit_sl else position['tp_price']
                exit_price *= (1 - SLIPPAGE_PCT) if pos_side == 'long' else (1 + SLIPPAGE_PCT)

                if pos_side == 'long':
                    pnl = (exit_price - position['entry_price']) * position['amount']
                else:
                    pnl = (position['entry_price'] - exit_price) * position['amount']

                fee = position['notional'] * (FEE_PCT * 2)
                pnl -= fee
                capital += pnl

                trades.append({
                    'side': pos_side,
                    'entry_time': position['entry_time'],
                    'entry_price': position['entry_price'],
                    'exit_time': ts,
                    'exit_price': exit_price,
                    'pnl_usd': pnl,
                })
                position = None

        if position is None and signal != 0:
            side = 'long' if signal == 1 else 'short'
            risk_margin = start_capital * (risk_per_entry_pct / 100.0)
            notional = risk_margin * leverage
            amount = notional / current_price

            if notional < 0.01:
                continue

            confidence = float(row['long_prob']) if side == 'long' else float(row['short_prob'])
            threshold = long_threshold if side == 'long' else short_threshold
            rr = _dynamic_rr(confidence, threshold, rr_min, rr_max)

            if side == 'long':
                entry_price = current_price * (1 + SLIPPAGE_PCT)
                sl_price = entry_price * (1 - sl_pct)
                tp_price = entry_price + rr * (entry_price - sl_price)
            else:
                entry_price = current_price * (1 - SLIPPAGE_PCT)
                sl_price = entry_price * (1 + sl_pct)
                tp_price = entry_price - rr * (sl_price - entry_price)

            position = {
                'side': side,
                'entry_price': entry_price,
                'sl_price': sl_price,
                'tp_price': tp_price,
                'amount': amount,
                'notional': notional,
                'entry_time': ts,
            }

    return trades


# ---------------------------------------------------------------------------
# Equity Curve aus Trades aufbauen
# ---------------------------------------------------------------------------

def build_equity_curve(df, trades, start_capital):
    equity = start_capital
    trade_events = sorted(
        [{'time': pd.to_datetime(t['exit_time']), 'pnl_usd': t['pnl_usd']}
         for t in trades],
        key=lambda x: x['time']
    )

    equity_data = []
    t_idx = 0
    for ts, _ in df.iterrows():
        while t_idx < len(trade_events) and trade_events[t_idx]['time'] <= ts:
            equity += trade_events[t_idx]['pnl_usd']
            t_idx += 1
        equity_data.append({'timestamp': ts, 'equity': equity})

    return pd.DataFrame(equity_data).set_index('timestamp')


# ---------------------------------------------------------------------------
# Interaktiver Chart (Plotly)
# ---------------------------------------------------------------------------

def create_interactive_chart(symbol, timeframe, df, trades, equity_df,
                              start_capital, start_date=None, end_date=None, window=None):
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        logger.error("plotly nicht installiert. Bitte: pip install plotly")
        return None

    chart_df = df.copy()
    if window:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window)
        chart_df = chart_df[chart_df.index >= cutoff]
    if start_date:
        chart_df = chart_df[chart_df.index >= pd.to_datetime(start_date, utc=True)]
    if end_date:
        chart_df = chart_df[chart_df.index <= pd.to_datetime(end_date, utc=True)]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=chart_df.index,
        open=chart_df['open'], high=chart_df['high'],
        low=chart_df['low'], close=chart_df['close'],
        name='OHLC',
        increasing_line_color='#16a34a',
        decreasing_line_color='#dc2626',
    ), secondary_y=False)

    # Trade-Signale
    entry_long_x, entry_long_y = [], []
    exit_long_x,  exit_long_y  = [], []
    entry_short_x, entry_short_y = [], []
    exit_short_x,  exit_short_y  = [], []

    chart_start = chart_df.index.min() if len(chart_df) > 0 else None
    chart_end = chart_df.index.max() if len(chart_df) > 0 else None

    for t in trades:
        et = pd.to_datetime(t['entry_time'])
        xt = pd.to_datetime(t['exit_time'])
        # Nur Trades im Chartbereich anzeigen
        if chart_start and (et < chart_start and xt < chart_start):
            continue
        if chart_end and (et > chart_end and xt > chart_end):
            continue
        if t['side'] == 'long':
            if chart_start is None or et >= chart_start:
                entry_long_x.append(et); entry_long_y.append(t['entry_price'])
            if chart_start is None or xt >= chart_start:
                exit_long_x.append(xt); exit_long_y.append(t['exit_price'])
        else:
            if chart_start is None or et >= chart_start:
                entry_short_x.append(et); entry_short_y.append(t['entry_price'])
            if chart_start is None or xt >= chart_start:
                exit_short_x.append(xt); exit_short_y.append(t['exit_price'])

    if entry_long_x:
        fig.add_trace(go.Scatter(
            x=entry_long_x, y=entry_long_y, mode='markers',
            marker=dict(color='#16a34a', symbol='triangle-up', size=14,
                        line=dict(width=1.2, color='#0f5132')),
            name='Entry Long',
        ), secondary_y=False)

    if exit_long_x:
        fig.add_trace(go.Scatter(
            x=exit_long_x, y=exit_long_y, mode='markers',
            marker=dict(color='#22d3ee', symbol='circle', size=12,
                        line=dict(width=1.1, color='#0e7490')),
            name='Exit Long',
        ), secondary_y=False)

    if entry_short_x:
        fig.add_trace(go.Scatter(
            x=entry_short_x, y=entry_short_y, mode='markers',
            marker=dict(color='#f59e0b', symbol='triangle-down', size=14,
                        line=dict(width=1.2, color='#92400e')),
            name='Entry Short',
        ), secondary_y=False)

    if exit_short_x:
        fig.add_trace(go.Scatter(
            x=exit_short_x, y=exit_short_y, mode='markers',
            marker=dict(color='#ef4444', symbol='diamond', size=12,
                        line=dict(width=1.1, color='#7f1d1d')),
            name='Exit Short',
        ), secondary_y=False)

    # Equity Curve
    if not equity_df.empty:
        eq_plot = equity_df.copy()
        if chart_start:
            eq_plot = eq_plot[eq_plot.index >= chart_start]
        if chart_end:
            eq_plot = eq_plot[eq_plot.index <= chart_end]
        if not eq_plot.empty:
            fig.add_trace(go.Scatter(
                x=eq_plot.index, y=eq_plot['equity'],
                name='Kontostand',
                line=dict(color='#2563eb', width=2),
                opacity=0.75,
            ), secondary_y=True)

    # Statistiken für Titel
    total_trades = len(trades)
    wins = sum(1 for t in trades if t['pnl_usd'] > 0)
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    total_pnl = sum(t['pnl_usd'] for t in trades)
    pnl_pct = total_pnl / start_capital * 100
    end_cap = equity_df['equity'].iloc[-1] if not equity_df.empty else start_capital

    title_text = (
        f"{symbol} {timeframe} — dbot LSTM | "
        f"Start: ${start_capital:.0f} | "
        f"End: ${end_cap:.0f} | "
        f"PnL: {'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}% | "
        f"Trades: {total_trades} | "
        f"Win Rate: {win_rate:.1f}%"
    )

    fig.update_layout(
        title=dict(text=title_text, font=dict(size=13), x=0.5, xanchor='center'),
        height=720,
        hovermode='x unified',
        template='plotly_white',
        dragmode='zoom',
        xaxis=dict(rangeslider=dict(visible=True), fixedrange=False),
        yaxis=dict(fixedrange=False),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5),
    )
    fig.update_yaxes(title_text='Preis (USDT)', secondary_y=False)
    fig.update_yaxes(title_text='Kontostand (USDT)', secondary_y=True)

    return fig


# ---------------------------------------------------------------------------
# Haupt-Funktion (wird von show_results.py aufgerufen)
# ---------------------------------------------------------------------------

def run(start_capital=1000.0, start_date=None, end_date=None):
    selected_configs = select_configs()

    print("\n" + "=" * 60)
    print("Chart-Optionen:")
    print("=" * 60)
    win_input = input("Letzten N Tage anzeigen [leer=alle]:       ").strip()
    window = int(win_input) if win_input.isdigit() else None

    tg_input = input("Telegram versenden? (j/n) [Standard: n]:   ").strip().lower()
    send_telegram = tg_input in ['j', 'y', 'yes', 'ja']

    telegram_config = {}
    if send_telegram:
        try:
            with open(os.path.join(PROJECT_ROOT, 'secret.json'), 'r') as f:
                secrets = json.load(f)
            telegram_config = secrets.get('telegram', {})
        except Exception as e:
            logger.warning(f"secret.json nicht lesbar: {e}")
            send_telegram = False

    for filename, filepath in selected_configs:
        try:
            logger.info(f"\nVerarbeite {filename}...")

            with open(filepath, 'r') as f:
                config = json.load(f)

            symbol = config['market']['symbol']
            timeframe = config['market']['timeframe']
            safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"

            # Modell laden
            model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt")
            scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}_scaler.pkl")
            seq_len = config.get('model', {}).get('sequence_length', 60)

            if not os.path.exists(model_path):
                logger.warning(f"Kein Modell gefunden fuer {filename}, ueberspringe.")
                continue

            from dbot.model.predictor import LSTMPredictor
            predictor = LSTMPredictor.from_files(model_path, scaler_path, seq_len)

            # Daten laden (immer gesamte Range fuer vollstaendige Trade-Historie)
            logger.info(f"Lade OHLCV-Daten fuer {symbol} {timeframe}...")
            df = load_ohlcv(symbol, timeframe, start_date=start_date, end_date=end_date)
            if df is None or len(df) < 200:
                logger.warning(f"Zu wenig Daten fuer {symbol} {timeframe}")
                continue

            # Trades extrahieren
            logger.info("Extrahiere Trades fuer Chart-Markierungen...")
            trades = extract_trades_lstm(df, predictor, config, start_capital)
            logger.info(f"  {len(trades)} Trades gefunden")

            # Equity Curve
            equity_df = build_equity_curve(df, trades, start_capital)

            # Chart erstellen
            logger.info("Erstelle interaktiven Chart...")
            fig = create_interactive_chart(
                symbol, timeframe, df, trades, equity_df,
                start_capital, start_date, end_date, window,
            )

            if fig is None:
                continue

            output_dir = os.path.join(PROJECT_ROOT, 'artifacts', 'charts')
            os.makedirs(output_dir, exist_ok=True)
            clean = filename.replace('config_', '').replace('_lstm.json', '')
            output_file = os.path.join(output_dir, f"dbot_{clean}.html")
            fig.write_html(output_file)
            logger.info(f"Chart gespeichert: {output_file}")

            if send_telegram and telegram_config.get('bot_token'):
                try:
                    from dbot.utils.telegram import send_document
                    send_document(
                        telegram_config['bot_token'],
                        telegram_config['chat_id'],
                        output_file,
                        caption=f"dbot LSTM Chart: {symbol} {timeframe}",
                    )
                    logger.info("Chart via Telegram versendet")
                except Exception as e:
                    logger.warning(f"Telegram-Versand fehlgeschlagen: {e}")

        except Exception as e:
            logger.error(f"Fehler bei {filename}: {e}", exc_info=True)
            continue

    logger.info("\nAlle Charts generiert!")
