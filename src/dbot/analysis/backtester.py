import argparse
import json
import math
import os
import sys
from datetime import datetime

import pandas as pd
import ta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.utils.exchange import Exchange
from dbot.strategy.sr_engine import SREngine
from dbot.strategy.trade_logic import get_titan_signal


class Bias:
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


def load_account_config():
    secret_path = os.path.join(PROJECT_ROOT, 'secret.json')
    if not os.path.exists(secret_path):
        raise FileNotFoundError("secret.json nicht gefunden – API Keys erforderlich für Daten-Download.")
    with open(secret_path, 'r') as f:
        secrets = json.load(f)
    api_setup = secrets.get('dbot', [None])[0]
    if not api_setup:
        raise ValueError("Kein dbot Account in secret.json gefunden.")
    return {
        'apiKey': api_setup.get('apiKey') or api_setup.get('api_key', ''),
        'secret': api_setup.get('secret', ''),
        'password': api_setup.get('password', '')
    }


def fetch_ohlcv(symbol, timeframe, start_date, end_date):
    try:
        account_config = load_account_config()
        exchange = Exchange(account_config)
        print(f"[FETCH] {symbol} {timeframe} {start_date} -> {end_date} ...", flush=True)
        df = exchange.fetch_historical_ohlcv(symbol, timeframe, start_date, end_date)
        if df is None or df.empty:
            print(f"FEHLER: Keine Daten für {symbol} {timeframe} im Zeitraum {start_date} - {end_date}")
            return pd.DataFrame()
        print(f"[FETCH] Fertig: {len(df)} Kerzen", flush=True)
        return df
    except Exception as e:
        print(f"FEHLER beim Datenabruf: {e}")
        return pd.DataFrame()


def simulate_smc_backtest(df, params):
    if df is None or df.empty:
        return {"error": "Keine Daten vorhanden"}
    
    if len(df) < 100:
        return {"error": f"Zu wenige Daten für Backtest (nur {len(df)} Kerzen, min. 100 erforderlich)"}

    df = df.copy()
    
    # Timestamp handling - prüfe ob bereits Index oder Spalte
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df.set_index('timestamp', inplace=True)
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)

    # ATR einmal berechnen
    atr_indicator = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14)
    df['atr'] = atr_indicator.average_true_range()

    start_capital = params.get('start_capital', 1000.0)
    equity = start_capital
    peak_equity = start_capital
    max_dd = 0.0
    fee_pct = params.get('fee_pct', 0.0005)

    leverage = params.get('leverage', 8)
    risk_per_trade = params.get('risk_per_trade', 0.12)
    atr_mult = params.get('atr_multiplier_sl', 1.0)
    min_sl_pct = params.get('min_sl_pct', 0.003)
    rr = params.get('risk_reward_ratio', 2.5)
    act_rr = params.get('trailing_stop_activation_rr', 1.5)
    callback_pct = params.get('trailing_stop_callback_rate_pct', 0.5) / 100.0

    engine = SREngine(settings=params.get('strategy', {}))

    position = None
    trades = []
    equity_curve = []

    lookback = max(50, params.get('lookback', 200))

    for idx in range(lookback, len(df)):
        window = df.iloc[:idx + 1]
        current = window.iloc[-1]

        processed = engine.process_dataframe(window.copy())
        current_candle = processed.iloc[-1]

        # Position Management
        if position:
            exit_price = None
            if position['side'] == 'long':
                if not position['trailing_active'] and current['high'] >= position['activation_price']:
                    position['trailing_active'] = True
                if position['trailing_active']:
                    position['peak_price'] = max(position['peak_price'], current['high'])
                    trailing_sl = position['peak_price'] * (1 - callback_pct)
                    position['stop_loss'] = max(position['stop_loss'], trailing_sl)
                if current['low'] <= position['stop_loss']:
                    exit_price = position['stop_loss']
                elif not position['trailing_active'] and current['high'] >= position['take_profit']:
                    exit_price = position['take_profit']
            else:
                if not position['trailing_active'] and current['low'] <= position['activation_price']:
                    position['trailing_active'] = True
                if position['trailing_active']:
                    position['peak_price'] = min(position['peak_price'], current['low'])
                    trailing_sl = position['peak_price'] * (1 + callback_pct)
                    position['stop_loss'] = min(position['stop_loss'], trailing_sl)
                if current['high'] >= position['stop_loss']:
                    exit_price = position['stop_loss']
                elif not position['trailing_active'] and current['low'] <= position['take_profit']:
                    exit_price = position['take_profit']

            if exit_price:
                pnl_pct = (exit_price / position['entry_price'] - 1) if position['side'] == 'long' else (1 - exit_price / position['entry_price'])
                notional = position['notional']
                pnl_usd = notional * pnl_pct
                total_fees = notional * fee_pct * 2
                net_pnl = pnl_usd - total_fees
                equity += net_pnl
                trades.append({
                    'side': position['side'],
                    'entry_time': position['entry_time'],
                    'exit_time': current.name,
                    'entry': position['entry_price'],
                    'exit': exit_price,
                    'pnl_usd': net_pnl
                })
                position = None
                peak_equity = max(peak_equity, equity)
                if peak_equity > 0:
                    dd = (peak_equity - equity) / peak_equity
                    max_dd = max(max_dd, dd)

        # Entry-Signal prüfen wenn frei
        if position is None:
            signal_side, signal_price = get_titan_signal(processed, current_candle, params, Bias.NEUTRAL)
            if signal_side:
                entry_price = signal_price or current['close']
                current_atr = current_candle.get('atr') or current.get('atr')
                if pd.isna(current_atr) or current_atr <= 0:
                    continue
                sl_distance_atr = current_atr * atr_mult
                sl_distance_min = entry_price * min_sl_pct
                sl_distance = max(sl_distance_atr, sl_distance_min)
                if sl_distance <= 0:
                    continue
                risk_usd = equity * risk_per_trade
                sl_pct = sl_distance / entry_price
                notional = risk_usd / sl_pct
                amount = notional / entry_price
                if amount <= 0 or notional <= 0:
                    continue
                if signal_side == 'buy':
                    sl_price = entry_price - sl_distance
                    tp_price = entry_price + sl_distance * rr
                    activation_price = entry_price + sl_distance * act_rr
                else:
                    sl_price = entry_price + sl_distance
                    tp_price = entry_price - sl_distance * rr
                    activation_price = entry_price - sl_distance * act_rr

                position = {
                    'side': 'long' if signal_side == 'buy' else 'short',
                    'entry_price': entry_price,
                    'entry_time': current.name,
                    'stop_loss': sl_price,
                    'take_profit': tp_price,
                    'activation_price': activation_price,
                    'trailing_active': False,
                    'peak_price': entry_price,
                    'notional': notional * leverage
                }

        equity_curve.append({
            'timestamp': current.name,
            'equity': equity
        })

    trades_count = len(trades)
    wins = sum(1 for t in trades if t['pnl_usd'] > 0)
    win_rate = (wins / trades_count * 100) if trades_count else 0
    pnl_pct = ((equity - start_capital) / start_capital * 100) if start_capital else 0

    return {
        'final_equity': equity,
        'start_equity': start_capital,
        'pnl_pct': pnl_pct,
        'trades': trades,
        'trades_count': trades_count,
        'win_rate': win_rate,
        'max_drawdown_pct': max_dd * 100,
        'equity_curve': equity_curve
    }


def main():
    parser = argparse.ArgumentParser(description="DBot SMC Backtester (interaktiv von show_results.sh aufgerufen)")
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--timeframe', required=True)
    parser.add_argument('--start_date', required=True)
    parser.add_argument('--end_date', required=True)
    parser.add_argument('--leverage', type=float, default=8.0)
    parser.add_argument('--risk_per_trade', type=float, default=0.12, help='Dezimal, z.B. 0.12 = 12%')
    parser.add_argument('--fee_pct', type=float, default=0.0005)
    parser.add_argument('--atr_multiplier_sl', type=float, default=1.0)
    parser.add_argument('--min_sl_pct', type=float, default=0.003)
    parser.add_argument('--risk_reward_ratio', type=float, default=2.5)
    parser.add_argument('--trailing_stop_activation_rr', type=float, default=1.5)
    parser.add_argument('--trailing_stop_callback_rate_pct', type=float, default=0.5)
    parser.add_argument('--start_capital', type=float, default=1000.0)
    parser.add_argument('--export', type=str, default=None, help='CSV Pfad für Equity-Kurve')

    args = parser.parse_args()

    df = fetch_ohlcv(args.symbol, args.timeframe, args.start_date, args.end_date)

    params = {
        'market': {
            'symbol': args.symbol,
            'timeframe': args.timeframe,
            'htf': None
        },
        'risk': {},
        'strategy': {},
        'leverage': args.leverage,
        'risk_per_trade': args.risk_per_trade,
        'fee_pct': args.fee_pct,
        'atr_multiplier_sl': args.atr_multiplier_sl,
        'min_sl_pct': args.min_sl_pct,
        'risk_reward_ratio': args.risk_reward_ratio,
        'trailing_stop_activation_rr': args.trailing_stop_activation_rr,
        'trailing_stop_callback_rate_pct': args.trailing_stop_callback_rate_pct,
        'start_capital': args.start_capital
    }

    result = simulate_smc_backtest(df, params)
    if 'error' in result:
        print(result['error'])
        sys.exit(1)

    print("====================================================")
    print(f"Backtest: {args.symbol} ({args.timeframe}) {args.start_date} -> {args.end_date}")
    print(f"Start: {result['start_equity']:.2f} | Ende: {result['final_equity']:.2f} | PnL: {result['pnl_pct']:.2f}%")
    print(f"Trades: {result['trades_count']} | Win-Rate: {result['win_rate']:.2f}% | Max DD: {result['max_drawdown_pct']:.2f}%")

    if args.export:
        equity_df = pd.DataFrame(result['equity_curve'])
        equity_df.to_csv(args.export, index=False)
        print(f"Equity-Kurve exportiert nach {args.export}")
        try:
            base, _ = os.path.splitext(args.export)
            params_out = base + "_params.json"
            meta = {
                'symbol': args.symbol,
                'timeframe': args.timeframe,
                'start_date': args.start_date,
                'end_date': args.end_date,
                'leverage': args.leverage,
                'risk_per_trade': args.risk_per_trade,
                'fee_pct': args.fee_pct,
                'atr_multiplier_sl': args.atr_multiplier_sl,
                'min_sl_pct': args.min_sl_pct,
                'risk_reward_ratio': args.risk_reward_ratio,
                'trailing_stop_activation_rr': args.trailing_stop_activation_rr,
                'trailing_stop_callback_rate_pct': args.trailing_stop_callback_rate_pct,
                'start_capital': args.start_capital
            }
            with open(params_out, 'w') as f:
                json.dump(meta, f, indent=2)
            print(f"Run-Parameter gespeichert nach {params_out}")
        except Exception as e:
            print(f"Warnung: Konnte Parameter nicht speichern: {e}")


if __name__ == '__main__':
    main()
