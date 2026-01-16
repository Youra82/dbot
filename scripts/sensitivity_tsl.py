#!/usr/bin/env python3
"""
TSL Sensitivity Analysis für DBot
Testet verschiedene Aktivierungs-Ratios für Trailing Stop Loss
High-Frequency Anpassung: Schnellere Aktivierung getestet
"""
import os
import json
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
import sys
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.analysis.backtester import load_data, calculate_supertrend_direction
from dbot.utils.ann_model import load_model_and_scaler, create_ann_features
import numpy as np

# Config and symbol (DBot spezifisch)
config_path = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs', 'config_BTCUSDTUSDT_1m.json')
with open(config_path, 'r') as f:
    cfg = json.load(f)

symbol = cfg['market']['symbol']
timeframe = cfg['market']['timeframe']
sym_key = symbol.replace('/', '').replace(':', '')
model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f'ann_predictor_{sym_key}_{timeframe}.h5')
scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f'ann_scaler_{sym_key}_{timeframe}.joblib')

print('DBot TSL Sensitivity Analysis')
print('Using config:', config_path)
print('Model:', model_path)
print('Scaler:', scaler_path)

# Load model and scaler
model, scaler = load_model_and_scaler(model_path, scaler_path)
if model is None:
    raise SystemExit('Model not found')

# Load data (shorter period for HF)
start_date = '2025-11-01'
end_date = '2025-12-17'
raw = load_data(symbol, timeframe, start_date, end_date)
if raw.empty:
    raise SystemExit('No data loaded')

# prepare features
data = create_ann_features(raw.copy())
data.dropna(inplace=True)

# common params from config
params_base = cfg['risk'].copy()
params_base['prediction_threshold'] = cfg.get('strategy', {}).get('prediction_threshold', 0.6)

# DBot HF: Teste aggressivere Aktivierungen
activation_values = [1.0, 1.25, 1.5, 1.75]
results = []

for activation in activation_values:
    params = params_base.copy()
    params['trailing_stop_activation_rr'] = activation
    
    # Features & predictions
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
    X = data[feature_cols]
    features_scaled = scaler.transform(X)
    preds = model.predict(features_scaled, verbose=0).flatten()
    df = data.copy()
    df['prediction'] = preds
    df['supertrend_direction'] = calculate_supertrend_direction(df)
    df.dropna(inplace=True)

    pred_threshold = params.get('prediction_threshold', 0.6)
    activation_rr = params.get('trailing_stop_activation_rr', 1.5)
    callback_rate = params.get('trailing_stop_callback_rate_pct', 0.5) / 100.0  # HF: enger
    min_sl_pct = params.get('min_sl_pct', 0.3) / 100.0  # HF: enger
    leverage = params.get('leverage', 8)
    risk_reward_ratio = params.get('risk_reward_ratio', 2.0)
    fee_pct = 0.0005

    start_capital = 1000.0
    current_capital = start_capital
    peak = start_capital
    max_dd = 0.0
    trades = 0
    wins = 0
    tsl_activations = 0
    exits_by_tsl = 0
    exits_by_tp = 0

    position = None

    for i in range(len(df)):
        row = df.iloc[i]
        # manage position
        if position:
            exit_price = None
            if position['side'] == 'long':
                if not position['trailing_active'] and row['high'] >= position['activation_price']:
                    position['trailing_active'] = True
                    tsl_activations += 1
                if position['trailing_active']:
                    position['peak_price'] = max(position['peak_price'], row['high'])
                    trailing_sl = position['peak_price'] * (1 - position['callback_rate'])
                    position['stop_loss'] = max(position['stop_loss'], trailing_sl)
                if row['low'] <= position['stop_loss']:
                    exit_price = position['stop_loss']
                    exits_by_tsl += 1
                elif not position['trailing_active'] and row['high'] >= position['take_profit']:
                    exit_price = position['take_profit']
                    exits_by_tp += 1
            else:
                if not position['trailing_active'] and row['low'] <= position['activation_price']:
                    position['trailing_active'] = True
                    tsl_activations += 1
                if position['trailing_active']:
                    position['peak_price'] = min(position['peak_price'], row['low'])
                    trailing_sl = position['peak_price'] * (1 + position['callback_rate'])
                    position['stop_loss'] = min(position['stop_loss'], trailing_sl)
                if row['high'] >= position['stop_loss']:
                    exit_price = position['stop_loss']
                    exits_by_tsl += 1
                elif not position['trailing_active'] and row['low'] <= position['take_profit']:
                    exit_price = position['take_profit']
                    exits_by_tp += 1

            if exit_price is not None:
                pnl_pct = (exit_price / position['entry_price'] - 1) if position['side'] == 'long' else (1 - exit_price / position['entry_price'])
                notional = position['notional']
                pnl = notional * pnl_pct
                fees = notional * fee_pct * 2
                net = pnl - fees
                risk_amount = start_capital * position['risk_per_trade']
                if net < -risk_amount: net = -risk_amount
                max_profit = risk_amount * position['risk_reward']
                if net > max_profit: net = max_profit
                current_capital += net
                if net > 0: wins += 1
                trades += 1
                peak = max(peak, current_capital)
                if peak > 0:
                    dd = (peak - current_capital) / peak
                    max_dd = max(max_dd, dd)
                position = None

        # open new
        if not position:
            side = 'long' if row['prediction'] >= pred_threshold else 'short' if row['prediction'] <= (1 - pred_threshold) else None
            if side:
                st = row.get('supertrend_direction', None)
                if st == 1.0 and side == 'short':
                    continue
                if st == -1.0 and side == 'long':
                    continue
                entry_price = row['close']
                sl_distance = entry_price * min_sl_pct
                if sl_distance <= 0: continue
                notional = (current_capital * (params.get('risk_per_trade_pct', 1.5)/100.0)) / min_sl_pct
                margin_used = notional / leverage
                if margin_used > current_capital: continue
                take_profit = entry_price + sl_distance * risk_reward_ratio if side == 'long' else entry_price - sl_distance * risk_reward_ratio
                activation_price = entry_price + sl_distance * activation_rr if side == 'long' else entry_price - sl_distance * activation_rr
                position = {
                    'side': side, 'entry_price': entry_price, 
                    'stop_loss': entry_price - sl_distance if side=='long' else entry_price + sl_distance,
                    'take_profit': take_profit, 'notional': notional, 'margin_used': margin_used,
                    'trailing_active': False, 'activation_price': activation_price, 'peak_price': entry_price,
                    'callback_rate': callback_rate, 'risk_per_trade': (params.get('risk_per_trade_pct',1.5)/100.0), 
                    'risk_reward': risk_reward_ratio
                }

    total_return = ((current_capital - start_capital)/start_capital)*100
    win_rate = (wins / trades *100) if trades>0 else 0
    results.append({
        'activation_rr': activation, 'trades': trades, 'tsl_activations': tsl_activations, 
        'exits_by_tsl': exits_by_tsl, 'exits_by_tp': exits_by_tp, 'total_return_pct': total_return, 
        'max_drawdown_pct': max_dd*100, 'win_rate_pct': win_rate
    })

# print summary
print('\n' + '='*80)
print(f'DBot TSL Sensitivity Results for {symbol} {timeframe}')
print('='*80)
for r in results:
    print(f"activation_rr={r['activation_rr']}: trades={r['trades']}, tsl_activations={r['tsl_activations']}, "
          f"exits_by_tsl={r['exits_by_tsl']}, exits_by_tp={r['exits_by_tp']}, "
          f"return={r['total_return_pct']:.2f}%, maxDD={r['max_drawdown_pct']:.2f}%, win_rate={r['win_rate_pct']:.1f}%")
print('='*80)
