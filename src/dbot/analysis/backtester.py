import os
import pandas as pd
import numpy as np
from datetime import timedelta
import json
import sys
import ta
import math

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.utils.exchange import Exchange
from dbot.utils.ann_model import prepare_data_for_ann, load_model_and_scaler, create_ann_features
from dbot.utils.supertrend_indicator import SuperTrendLocal


def load_data(symbol, timeframe, start_date_str, end_date_str):
    cache_dir = os.path.join(PROJECT_ROOT, 'data', 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    symbol_filename = symbol.replace('/', '-').replace(':', '-')
    cache_file = os.path.join(cache_dir, f"{symbol_filename}_{timeframe}.csv")
    if os.path.exists(cache_file):
        data = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        try:
            if data.index.min() <= pd.to_datetime(start_date_str, utc=True) and data.index.max() >= pd.to_datetime(end_date_str, utc=True):
                return data.loc[start_date_str:end_date_str]
        except Exception:
            pass
    print(f"Starte Download für {symbol} ({timeframe}) von der Börse...")
    try:
        with open(os.path.join(PROJECT_ROOT, 'secret.json'), "r") as f:
            secrets = json.load(f)
        api_setup = secrets.get('dbot', [None])[0]
        if not api_setup:
            print("Fehler: Kein dbot Account in secret.json gefunden.")
            return pd.DataFrame()
        
        # Erstelle account_config dict für Exchange-Klasse
        account_config = {
            'apiKey': api_setup.get('apiKey') or api_setup.get('api_key', ''),
            'secret': api_setup.get('secret', ''),
            'password': api_setup.get('password', '')
        }
        exchange = Exchange(account_config)
        full_data = exchange.fetch_historical_ohlcv(symbol, timeframe, start_date_str, end_date_str)
        if not full_data.empty:
            full_data.to_csv(cache_file)
            return full_data
    except Exception as e:
        print(f"Fehler beim Daten-Download: {e}")
    return pd.DataFrame()


def get_higher_timeframe(tf):
    if 'm' in tf:
        return '1h'
    if tf == '1h':
        return '4h'
    if tf in ['2h', '4h', '6h']:
        return '1d'
    if tf == '1d':
        return None
    return '1d'


def calculate_supertrend_direction(data):
    st_indicator = SuperTrendLocal(data['high'], data['low'], data['close'], window=10, multiplier=3.0)
    return st_indicator.get_supertrend_direction().shift(1)


def run_ann_backtest(data, params, model_paths, start_capital=1000, use_macd_filter=False, htf_data=None, timeframe=None, verbose=False, params_for_htf_load=None):
    model, scaler = load_model_and_scaler(model_paths['model'], model_paths['scaler'])
    if not model or not scaler:
        raise Exception("Modell/Scaler nicht gefunden!")

    if not timeframe:
        raise ValueError("Backtester benötigt ein 'timeframe' Argument für die Daten-Vorbereitung!")

    data_with_features = create_ann_features(data.copy())
    data_with_features.dropna(inplace=True)
    data_with_features['supertrend_direction'] = calculate_supertrend_direction(data_with_features)
    data_with_features.dropna(inplace=True)

    if data_with_features.empty:
        return {"total_pnl_pct": 0, "trades_count": 0, "win_rate": 0, "max_drawdown_pct": 1.0, "end_capital": start_capital}

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

    missing_cols = [col for col in feature_cols if col not in data_with_features.columns]
    if missing_cols:
        raise ValueError(f"Fehlende Spalten in data_with_features: {missing_cols}")

    data_for_scaling = data_with_features[feature_cols]
    features_scaled = scaler.transform(data_for_scaling)
    predictions = model.predict(features_scaled, verbose=0).flatten()
    data_with_features['prediction'] = pd.Series(predictions, index=data_with_features.index)

    pred_threshold = params.get('prediction_threshold', 0.6)
    risk_reward_ratio = params.get('risk_reward_ratio', 3.0)
    risk_per_trade_pct = params.get('risk_per_trade_pct', 10.0) / 100
    activation_rr = params.get('trailing_stop_activation_rr', 1.5)
    callback_rate = params.get('trailing_stop_callback_rate_pct', 0.5) / 100
    initial_sl_pct = params.get('initial_sl_pct', params.get('min_sl_pct', 1.0)) / 100.0
    leverage = params.get('leverage', 8)
    volume_spike_multiplier = params.get('volume_spike_multiplier', 1.5)
    min_atr_multiplier = params.get('min_atr_multiplier', 1.2)
    min_adx = params.get('min_adx', 15)
    fee_pct = 0.05 / 100

    current_capital, trades_count, wins_count = start_capital, 0, 0
    peak_capital, max_drawdown_pct = start_capital, 0.0
    position = None
    trades = []

    for i in range(len(data_with_features)):
        current = data_with_features.iloc[i]

        if position:
            exit_price, reason = None, None
            if position['side'] == 'long':
                if not position['trailing_active'] and current['high'] >= position['activation_price']:
                    position['trailing_active'] = True
                if position['trailing_active']:
                    position['peak_price'] = max(position['peak_price'], current['high'])
                    trailing_sl = position['peak_price'] * (1 - callback_rate)
                    position['stop_loss'] = max(position['stop_loss'], trailing_sl)
                if current['low'] <= position['stop_loss']:
                    exit_price = position['stop_loss']
                elif not position['trailing_active'] and current['high'] >= position['take_profit']:
                    exit_price = position['take_profit']
            elif position['side'] == 'short':
                if not position['trailing_active'] and current['low'] <= position['activation_price']:
                    position['trailing_active'] = True
                if position['trailing_active']:
                    position['peak_price'] = min(position['peak_price'], current['low'])
                    trailing_sl = position['peak_price'] * (1 + callback_rate)
                    position['stop_loss'] = min(position['stop_loss'], trailing_sl)
                if current['high'] >= position['stop_loss']:
                    exit_price = position['stop_loss']
                elif not position['trailing_active'] and current['low'] <= position['take_profit']:
                    exit_price = position['take_profit']

            if exit_price:
                pnl_pct = (exit_price / position['entry_price'] - 1) if position['side'] == 'long' else (1 - exit_price / position['entry_price'])
                notional_value = position['margin_used'] * leverage
                pnl_usd = notional_value * pnl_pct
                total_fees = notional_value * fee_pct * 2
                risk_amount_usd = start_capital * risk_per_trade_pct
                net_pnl = pnl_usd - total_fees
                if net_pnl < -risk_amount_usd:
                    net_pnl = -risk_amount_usd
                current_capital += net_pnl
                if position['side'] == 'long':
                    trades.append({
                        'entry_long': {'time': position['entry_time'], 'price': position['entry_price']},
                        'exit_long': {'time': data_with_features.index[i], 'price': exit_price}
                    })
                else:
                    trades.append({
                        'entry_short': {'time': position['entry_time'], 'price': position['entry_price']},
                        'exit_short': {'time': data_with_features.index[i], 'price': exit_price}
                    })
                if net_pnl > 0:
                    wins_count += 1
                trades_count += 1
                position = None
                peak_capital = max(peak_capital, current_capital)
                if peak_capital > 0:
                    drawdown = (peak_capital - current_capital) / peak_capital
                    max_drawdown_pct = max(max_drawdown_pct, drawdown)
                if current_capital <= 0:
                    break

        if not position:
            side = 'long' if current['prediction'] >= pred_threshold else 'short' if current['prediction'] <= (1 - pred_threshold) else None
            trade_allowed = True

            if side:
                st_direction = current['supertrend_direction']
                if st_direction == 1.0 and side == 'short':
                    trade_allowed = False
                elif st_direction == -1.0 and side == 'long':
                    trade_allowed = False

                if trade_allowed:
                    current_adx = current.get('adx', 0)
                    if current_adx < min_adx:
                        trade_allowed = False
                    if 'volume_ratio' in current.index:
                        if current['volume_ratio'] < volume_spike_multiplier:
                            trade_allowed = False
                    if i >= 50:
                        recent_atr = data_with_features['atr_normalized'].iloc[i-50:i]
                        avg_atr = recent_atr.mean()
                        if current['atr_normalized'] < avg_atr * min_atr_multiplier:
                            trade_allowed = False
                        if current['atr_normalized'] > avg_atr * 2.0:
                            trade_allowed = False

                if side and trade_allowed:
                    entry_price = current['close']
                    entry_time = data_with_features.index[i]
                    risk_amount_usd = current_capital * risk_per_trade_pct

                    sl_distance = entry_price * initial_sl_pct
                    if sl_distance == 0:
                        continue

                    notional_value = risk_amount_usd / initial_sl_pct
                    margin_used = notional_value / leverage
                    if margin_used > current_capital:
                        continue

                    stop_loss_distance = entry_price * initial_sl_pct
                    stop_loss = entry_price - stop_loss_distance if side == 'long' else entry_price + stop_loss_distance
                    take_profit = entry_price + (entry_price - stop_loss) * risk_reward_ratio if side == 'long' else entry_price - (stop_loss - entry_price) * risk_reward_ratio
                    activation_price = entry_price + stop_loss_distance * activation_rr if side == 'long' else entry_price - stop_loss_distance * activation_rr

                    position = {
                        'side': side,
                        'entry_price': entry_price,
                        'entry_time': entry_time,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'margin_used': margin_used,
                        'notional_value': notional_value,
                        'trailing_active': False,
                        'activation_price': activation_price,
                        'peak_price': entry_price,
                        'callback_rate': callback_rate
                    }

    win_rate = (wins_count / trades_count * 100) if trades_count > 0 else 0
    final_pnl_pct = ((current_capital - start_capital) / start_capital) * 100 if start_capital > 0 else 0
    return {
        "total_pnl_pct": final_pnl_pct,
        "trades_count": trades_count,
        "win_rate": win_rate,
        "max_drawdown_pct": max_drawdown_pct,
        "end_capital": current_capital,
        "trades": trades
    }
