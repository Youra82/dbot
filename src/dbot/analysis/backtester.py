# src/dbot/analysis/backtester.py
# Backtest-Engine für dbot (LSTM-Signale)
import os
import sys
import json
import logging
import argparse
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.model.feature_engineering import (
    compute_features, create_labels, build_sequences, apply_scaler, load_scaler, FEATURE_NAMES
)
from dbot.model.trainer import load_model
from dbot.model.predictor import LSTMPredictor

logger = logging.getLogger(__name__)

FEE_PCT = 0.0006     # 0.06% Taker-Fee
SLIPPAGE_PCT = 0.0005  # 0.05% Slippage


def _dynamic_rr(confidence: float, threshold: float, rr_min: float = 1.5, rr_max: float = 3.0) -> float:
    """Skaliert R:R linear zwischen rr_min und rr_max basierend auf LSTM-Konfidenz."""
    conf_range = 1.0 - threshold
    if conf_range <= 0:
        return rr_min
    t = (confidence - threshold) / conf_range
    t = max(0.0, min(1.0, t))
    return rr_min + t * (rr_max - rr_min)


def run_backtest(
    df: pd.DataFrame,
    predictor: LSTMPredictor,
    config: dict,
    start_capital: float = 1000.0,
    verbose: bool = True,
) -> dict:
    """
    Führt einen Backtest mit LSTM-Signalen durch.

    Args:
        df: OHLCV-DataFrame (historisch)
        predictor: Trainierter LSTMPredictor
        config: Strategy-Config dict
        start_capital: Startkapital in USDT
        verbose: Ob Fortschritt geloggt werden soll

    Returns:
        dict mit Performance-Metriken
    """
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

    # Features + Predictions für alle Kerzen
    feature_df = compute_features(df)
    if len(feature_df) < predictor.seq_len + 10:
        logger.error(f"Zu wenig Daten für Backtest: {len(feature_df)}")
        return {'error': 'insufficient_data'}

    scaler = predictor.scaler
    scaled_df = apply_scaler(feature_df, scaler)

    # Alle Predictions in einem Batch
    all_probs = predictor.predict_batch(scaled_df)  # (n - seq_len, 3)

    # Alignment: Index der Predictions entspricht feature_df.iloc[seq_len:]
    pred_index = feature_df.index[predictor.seq_len:]
    assert len(all_probs) == len(pred_index), "Längen-Mismatch bei Predictions"

    # OHLCV mit Prediction-Index joinen
    ohlcv_pred = df.loc[pred_index].copy()
    ohlcv_pred['long_prob'] = all_probs[:, 0]
    ohlcv_pred['neutral_prob'] = all_probs[:, 1]
    ohlcv_pred['short_prob'] = all_probs[:, 2]

    # Signale
    ohlcv_pred['signal'] = 0  # 0 = neutral
    ohlcv_pred.loc[
        (ohlcv_pred['long_prob'] > long_threshold) &
        (ohlcv_pred['long_prob'] > ohlcv_pred['short_prob']),
        'signal'
    ] = 1  # LONG

    ohlcv_pred.loc[
        (ohlcv_pred['short_prob'] > short_threshold) &
        (ohlcv_pred['short_prob'] > ohlcv_pred['long_prob']),
        'signal'
    ] = -1  # SHORT

    # Deaktiviere Seiten basierend auf Config
    if not use_longs:
        ohlcv_pred.loc[ohlcv_pred['signal'] == 1, 'signal'] = 0
    if not use_shorts:
        ohlcv_pred.loc[ohlcv_pred['signal'] == -1, 'signal'] = 0

    # Backtest-Simulation
    capital = start_capital
    position = None  # {'side': 'long'|'short', 'entry_price': float, 'sl_price': float, 'tp_price': float, 'amount': float}
    trades = []

    for i, (ts, row) in enumerate(ohlcv_pred.iterrows()):
        current_price = float(row['close'])
        signal = int(row['signal'])

        # Prüfe offene Position
        if position is not None:
            pos_side = position['side']
            sl_price = position['sl_price']
            tp_price = position['tp_price']
            entry_price = position['entry_price']
            amount = position['amount']

            # Prüfe ob SL/TP getroffen (vereinfacht: am aktuellen Close)
            hit_sl = (pos_side == 'long' and current_price <= sl_price) or \
                     (pos_side == 'short' and current_price >= sl_price)
            hit_tp = (pos_side == 'long' and current_price >= tp_price) or \
                     (pos_side == 'short' and current_price <= tp_price)

            if hit_sl or hit_tp:
                exit_price = sl_price if hit_sl else tp_price
                exit_price *= (1 - SLIPPAGE_PCT) if pos_side == 'long' else (1 + SLIPPAGE_PCT)

                if pos_side == 'long':
                    pnl = (exit_price - entry_price) / entry_price * amount * leverage
                else:
                    pnl = (entry_price - exit_price) / entry_price * amount * leverage

                # Fees
                fee = amount * (FEE_PCT * 2)  # Entry + Exit
                pnl -= fee

                capital += pnl
                result = 'win' if pnl > 0 else 'loss'

                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': ts,
                    'side': pos_side,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl_usdt': pnl,
                    'pnl_pct': pnl / start_capital * 100,
                    'result': result,
                    'capital_after': capital,
                })

                if verbose and len(trades) % 10 == 0:
                    logger.info(f"Trade {len(trades)}: {pos_side} {result} | PnL: {pnl:.2f} USDT | Capital: {capital:.2f}")

                position = None

        # Neuen Entry prüfen (nur wenn keine offene Position)
        if position is None and signal != 0:
            side = 'long' if signal == 1 else 'short'

            # Positionsgröße
            risk_amount = start_capital * (risk_per_entry_pct / 100.0)
            sl_distance = current_price * sl_pct
            if sl_distance <= 0:
                continue
            amount = risk_amount / sl_distance

            # Mindest-Notional
            if amount * current_price < 5.0:
                continue

            # Einstiegskosten (Slippage) + dynamisches R:R
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
                'entry_time': ts,
            }

    # Zusammenfassung
    return _compute_metrics(trades, start_capital, capital)


def _compute_metrics(trades: list, start_capital: float, final_capital: float) -> dict:
    """Berechnet Performance-Metriken aus Trade-Liste."""
    if not trades:
        return {
            'total_trades': 0, 'win_rate': 0.0, 'pnl_pct': 0.0,
            'max_drawdown_pct': 0.0, 'calmar_ratio': 0.0,
            'avg_win_usdt': 0.0, 'avg_loss_usdt': 0.0, 'start_capital': start_capital,
        }

    df_trades = pd.DataFrame(trades)
    wins = df_trades[df_trades['result'] == 'win']
    losses = df_trades[df_trades['result'] == 'loss']

    total_pnl = final_capital - start_capital
    pnl_pct = total_pnl / start_capital * 100

    # Max Drawdown
    capital_series = pd.Series([start_capital] + list(df_trades['capital_after']))
    rolling_max = capital_series.cummax()
    drawdown = (capital_series - rolling_max) / rolling_max * 100
    max_drawdown_pct = abs(drawdown.min())

    # Calmar Ratio (annualisiert, vereinfacht)
    calmar = (pnl_pct / max_drawdown_pct) if max_drawdown_pct > 0 else 0.0

    return {
        'total_trades': len(trades),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': len(wins) / len(trades) * 100,
        'pnl_usdt': total_pnl,
        'pnl_pct': pnl_pct,
        'max_drawdown_pct': max_drawdown_pct,
        'calmar_ratio': calmar,
        'avg_win_usdt': float(wins['pnl_usdt'].mean()) if len(wins) > 0 else 0.0,
        'avg_loss_usdt': float(losses['pnl_usdt'].mean()) if len(losses) > 0 else 0.0,
        'start_capital': start_capital,
        'final_capital': final_capital,
    }


def print_report(metrics: dict):
    """Gibt einen formatierten Backtest-Report aus."""
    print("\n" + "="*50)
    print("  dbot LSTM Backtest Report")
    print("="*50)
    print(f"  Trades:        {metrics.get('total_trades', 0)}")
    print(f"  Win-Rate:      {metrics.get('win_rate', 0):.1f}%")
    print(f"  PnL:           {metrics.get('pnl_usdt', 0):.2f} USDT ({metrics.get('pnl_pct', 0):.1f}%)")
    print(f"  Max Drawdown:  {metrics.get('max_drawdown_pct', 0):.1f}%")
    print(f"  Calmar Ratio:  {metrics.get('calmar_ratio', 0):.2f}")
    print(f"  Avg Win:       {metrics.get('avg_win_usdt', 0):.2f} USDT")
    print(f"  Avg Loss:      {metrics.get('avg_loss_usdt', 0):.2f} USDT")
    print(f"  Startkapital:  {metrics.get('start_capital', 0):.2f} USDT")
    print(f"  Endkapital:    {metrics.get('final_capital', 0):.2f} USDT")
    print("="*50 + "\n")


def load_config(symbol, timeframe):
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    config_path = os.path.join(configs_dir, f"config_{safe_name}_lstm.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config nicht gefunden: {config_path}")
    with open(config_path, 'r') as f:
        return json.load(f)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(description="dbot LSTM Backtester")
    parser.add_argument('--symbol', required=True, type=str, help="Handelspaar (z.B. BTC/USDT:USDT)")
    parser.add_argument('--timeframe', required=True, type=str, help="Zeitrahmen (z.B. 4h)")
    parser.add_argument('--start-capital', type=float, default=1000.0, help="Startkapital USDT")
    parser.add_argument('--data-file', type=str, help="Pfad zu lokaler CSV-Datei (optional)")
    args = parser.parse_args()

    symbol = args.symbol
    timeframe = args.timeframe
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"

    config = load_config(symbol, timeframe)
    seq_len = config.get('model', {}).get('sequence_length', 60)

    # Modell + Scaler laden
    model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt")
    scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}_scaler.pkl")

    if not os.path.exists(model_path):
        print(f"FEHLER: Modell nicht gefunden: {model_path}")
        print("Bitte zuerst ausführen: python train_model.py --symbol ... --timeframe ...")
        sys.exit(1)

    predictor = LSTMPredictor.from_files(model_path, scaler_path, seq_len)

    # Daten laden
    if args.data_file and os.path.exists(args.data_file):
        df = pd.read_csv(args.data_file, index_col=0, parse_dates=True)
        logger.info(f"Daten aus Datei geladen: {len(df)} Kerzen")
    else:
        # Daten von Exchange laden (braucht secret.json)
        try:
            with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
                secrets = json.load(f)
            account = secrets.get('dbot', [{}])[0]

            sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))
            from dbot.utils.exchange import Exchange
            exchange = Exchange(account)
            logger.info(f"Lade historische Daten für {symbol} ({timeframe})...")
            df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=2000)
        except Exception as e:
            print(f"FEHLER: Konnte keine Daten laden: {e}")
            sys.exit(1)

    if df is None or len(df) < 200:
        print("FEHLER: Zu wenig Daten für Backtest.")
        sys.exit(1)

    # Backtest ausführen
    logger.info(f"Starte Backtest für {symbol} ({timeframe}) mit {len(df)} Kerzen...")
    metrics = run_backtest(df, predictor, config, start_capital=args.start_capital)

    if 'error' in metrics:
        print(f"FEHLER: {metrics['error']}")
        sys.exit(1)

    print_report(metrics)


if __name__ == "__main__":
    main()
