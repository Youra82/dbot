# src/dbot/analysis/portfolio_simulator.py (Version 1 - Ported from JaegerBot)
import pandas as pd
import numpy as np
from tqdm import tqdm
import os
import sys
from datetime import datetime
import math

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.utils.ann_model import prepare_data_for_ann, create_ann_features
from dbot.analysis.backtester import load_data, calculate_supertrend_direction


def run_portfolio_simulation(start_capital, strategies_data, start_date, end_date):
    """
    Führt eine chronologische Portfolio-Simulation mit mehreren Strategien durch.
    """
    print("\n--- Starte Portfolio-Simulation... ---")

    all_signals = []

    # --- START: SuperTrend Trenddaten laden und generieren ---
    print("1/4: Trenddaten (SuperTrend) laden und generieren...")
    st_data_cache = {}
    for key, strat in strategies_data.items():
        data_with_features = strat['data'].copy()
        if not data_with_features.empty:
            st_direction = calculate_supertrend_direction(data_with_features)
            st_data_cache[strat['symbol']] = st_direction
    # --- ENDE SuperTrend Trenddaten laden ---

    print("2/4: Generiere Handelssignale für alle Strategien...")
    for key, strat in strategies_data.items():
        data = strat['data']
        model = strat['model']
        scaler = strat['scaler']
        params = strat['params']
        timeframe = strat['timeframe']
        symbol = strat['symbol']
        
        # Risk/Reward Ratio für die Simulation speichern
        rr_ratio = params.get('risk_reward_ratio', 3.0)

        # Führe Indikator-Berechnung durch
        data_with_features = create_ann_features(data.copy())
        data_with_features.dropna(inplace=True)
        if data_with_features.empty:
            continue

        # Feature-Spalten definieren (MUSS EXAKT mit ann_model.py übereinstimmen!)
        feature_cols = [
            # Basis-Features
            'bb_width', 'bb_pband', 'obv', 'rsi', 'macd_diff', 'macd', 
            'atr_normalized', 'adx', 'adx_pos', 'adx_neg',
            
            # Volume-Features
            'volume_ratio', 'mfi', 'cmf',
            
            # Trend-Features
            'price_to_ema20', 'price_to_ema50',
            
            # Momentum-Features
            'stoch_k', 'stoch_d', 'williams_r', 'roc', 'cci',
            
            # Support/Resistance
            'price_to_resistance', 'price_to_support',
            
            # Price Action
            'high_low_range', 'close_to_high', 'close_to_low',
            
            # Zeitliche Features
            'day_of_week', 'hour_of_day',
            
            # Returns & Volatilität
            'returns_lag1', 'returns_lag2', 'returns_lag3', 'hist_volatility'
        ]

        # Skalieren und Vorhersage
        features_scaled = scaler.transform(data_with_features[feature_cols])
        predictions = model.predict(features_scaled, verbose=0).flatten()
        data_with_features['prediction'] = predictions
        
        # SuperTrend Direction für den Filter hinzufügen
        st_direction_series = st_data_cache.get(symbol)
        if st_direction_series is None or st_direction_series.empty:
            continue

        data_with_features['st_direction'] = st_direction_series
        data_with_features.dropna(subset=['st_direction'], inplace=True) 

        pred_threshold = params.get('prediction_threshold', 0.52)
        use_supertrend_filter = params.get('use_supertrend_filter', False)  # Für Scalping default OFF

        # Generiere Signale - mit optionalem SuperTrend-Filter
        if use_supertrend_filter:
            # Mit SuperTrend: Nur Longs im Long-Trend (1.0), nur Shorts im Short-Trend (-1.0)
            long_signals_filtered = data_with_features[(data_with_features['prediction'] >= pred_threshold) & (data_with_features['st_direction'] == 1.0)]
            short_signals_filtered = data_with_features[(data_with_features['prediction'] <= (1 - pred_threshold)) & (data_with_features['st_direction'] == -1.0)]
        else:
            # Ohne SuperTrend-Filter: Nur basierend auf ANN-Prediction
            long_signals_filtered = data_with_features[data_with_features['prediction'] >= pred_threshold]
            short_signals_filtered = data_with_features[data_with_features['prediction'] <= (1 - pred_threshold)]

        # Sammle alle Signale
        for index, row in long_signals_filtered.iterrows():
            all_signals.append({
                'timestamp': index, 'symbol': symbol, 'timeframe': timeframe, 'side': 'long',
                'entry_price': row['close'], 'params': params, 'config_key': key,
                'risk_per_trade_pct': params.get('risk_per_trade_pct', 10.0) / 100,
                'risk_reward_ratio': rr_ratio
            })
        for index, row in short_signals_filtered.iterrows():
            all_signals.append({
                'timestamp': index, 'symbol': symbol, 'timeframe': timeframe, 'side': 'short',
                'entry_price': row['close'], 'params': params, 'config_key': key,
                'risk_per_trade_pct': params.get('risk_per_trade_pct', 10.0) / 100,
                'risk_reward_ratio': rr_ratio
            })

    if not all_signals:
        print("Keine Handelssignale im gewählten Zeitraum gefunden.")
        return {
            "start_capital": start_capital, "end_capital": start_capital, "total_pnl_pct": 0.0,
            "trade_count": 0, "win_rate": 0.0, "max_drawdown_pct": 0.0,
            "max_drawdown_date": None, "min_equity": start_capital, "liquidation_date": None,
            "equity_curve": pd.DataFrame({'timestamp': [datetime.strptime(start_date, "%Y-%m-%d")], 'equity': [start_capital], 'drawdown_pct': [0.0]})
        }

    all_signals.sort(key=lambda x: x['timestamp'])

    # Kombiniere alle Timeframes für die Equity Curve
    all_timestamps = set()
    for key, strat in strategies_data.items():
        all_timestamps.update(strat['data'].index)
    sorted_timestamps = sorted(list(all_timestamps))

    # --- 3. Chronologische Simulation (mit TSL-Logik) ---
    print("3/4: Führe chronologische Backtests durch...")

    equity = start_capital
    peak_equity = start_capital
    max_drawdown_pct = 0.0
    max_drawdown_date = None
    min_equity_ever = start_capital
    liquidation_date = None

    open_positions = {}
    trade_history = []
    equity_curve = []

    fee_pct = 0.05 / 100
    max_allowed_effective_leverage = 10
    absolute_max_notional_value = 1000000
    min_notional = 5.0

    signal_idx = 0
    for ts in tqdm(sorted_timestamps, desc="Simuliere Portfolio"):
        if liquidation_date:
            break

        current_total_equity = equity
        unrealized_pnl = 0

        # --- 3a. Offene Positionen managen (Trailing-Stop-Logik) ---
        positions_to_close = []
        for key in list(open_positions.keys()):
            pos = open_positions[key]
            strat_data = strategies_data.get(pos['symbol_key'])
            if not strat_data or ts not in strat_data['data'].index:
                continue

            current_candle = strat_data['data'].loc[ts]
            pos['last_known_price'] = current_candle['close']
            exit_price = None

            if pos['side'] == 'long':
                if not pos['trailing_active'] and current_candle['high'] >= pos['activation_price']:
                    pos['trailing_active'] = True
                if pos['trailing_active']:
                    pos['peak_price'] = max(pos['peak_price'], current_candle['high'])
                    trailing_sl = pos['peak_price'] * (1 - pos['callback_rate'])
                    pos['stop_loss'] = max(pos['stop_loss'], trailing_sl)
                if current_candle['low'] <= pos['stop_loss']:
                    exit_price = pos['stop_loss']
                elif not pos['trailing_active'] and current_candle['high'] >= pos['take_profit']:
                    exit_price = pos['take_profit']

            elif pos['side'] == 'short':
                if not pos['trailing_active'] and current_candle['low'] <= pos['activation_price']:
                    pos['trailing_active'] = True
                if pos['trailing_active']:
                    pos['peak_price'] = min(pos['peak_price'], current_candle['low'])
                    trailing_sl = pos['peak_price'] * (1 + pos['callback_rate'])
                    pos['stop_loss'] = min(pos['stop_loss'], trailing_sl)
                if current_candle['high'] >= pos['stop_loss']:
                    exit_price = pos['stop_loss']
                elif not pos['trailing_active'] and current_candle['low'] <= pos['take_profit']:
                    exit_price = pos['take_profit']

            if exit_price:
                pnl_pct = (exit_price / pos['entry_price'] - 1) if pos['side'] == 'long' else (1 - exit_price / pos['entry_price'])
                pnl_usd = pos['notional_value'] * pnl_pct
                total_fees = pos['notional_value'] * fee_pct * 2
                
                risk_per_trade_pct = pos['risk_per_trade_pct']
                risk_amount_usd = start_capital * risk_per_trade_pct
                
                net_pnl = pnl_usd - total_fees
                
                # Max. Verlust ist der riskierte Betrag pro Trade
                if net_pnl < -risk_amount_usd:
                    net_pnl = -risk_amount_usd
                    
                # Max. Gewinn ist der riskierte Betrag * Risk/Reward Ratio
                risk_reward_ratio = pos['risk_reward_ratio']
                max_profit_usd = risk_amount_usd * risk_reward_ratio
                if net_pnl > max_profit_usd:
                    net_pnl = max_profit_usd
                    
                equity += net_pnl
                trade_history.append({'config_key': pos['config_key'], 'pnl': net_pnl})
                positions_to_close.append(key)
            else:
                pnl_mult = 1 if pos['side'] == 'long' else -1
                unrealized_pnl += pos['notional_value'] * (current_candle['close'] / pos['entry_price'] - 1) * pnl_mult

        for key in positions_to_close:
            del open_positions[key]

        # --- 3b. Neue Signale prüfen und Positionen eröffnen ---
        while signal_idx < len(all_signals) and all_signals[signal_idx]['timestamp'] == ts:
            signal = all_signals[signal_idx]
            symbol_key = signal['symbol']
            config_key = signal['config_key']
            
            pos_key = f"{symbol_key}_{signal['timeframe']}"

            if pos_key in open_positions:
                signal_idx += 1
                continue

            if equity <= 0:
                signal_idx += 1
                continue

            params = signal['params']
            risk_params = params.get('risk', {})

            risk_per_trade_pct = signal.get('risk_per_trade_pct', 0.10)
            risk_reward_ratio = signal.get('risk_reward_ratio', 3.0)
            initial_sl_pct = risk_params.get('initial_sl_pct', 1.0) / 100.0
            leverage = risk_params.get('leverage', 8)
            activation_rr = risk_params.get('trailing_stop_activation_rr', 1.5)
            callback_rate = risk_params.get('trailing_stop_callback_rate_pct', 0.5) / 100.0
            
            entry_price = signal['entry_price']
            risk_amount_usd = equity * risk_per_trade_pct

            sl_distance = entry_price * initial_sl_pct
            if sl_distance <= 0:
                signal_idx += 1
                continue

            notional_value = risk_amount_usd / initial_sl_pct 
            
            max_notional_by_leverage = equity * max_allowed_effective_leverage
            final_notional_value = min(notional_value, max_notional_by_leverage, absolute_max_notional_value)

            if final_notional_value < min_notional:
                signal_idx += 1
                continue

            margin_used = final_notional_value / leverage
            current_total_margin = sum(p['margin_used'] for p in open_positions.values())
            if current_total_margin + margin_used > equity:
                signal_idx += 1
                continue

            if signal['side'] == 'long':
                stop_loss = entry_price - sl_distance
                take_profit = entry_price + sl_distance * risk_reward_ratio
                activation_price = entry_price + sl_distance * activation_rr
            else:
                stop_loss = entry_price + sl_distance
                take_profit = entry_price - sl_distance * risk_reward_ratio
                activation_price = entry_price - sl_distance * activation_rr

            open_positions[pos_key] = {
                'side': signal['side'], 'entry_price': entry_price,
                'stop_loss': stop_loss, 'take_profit': take_profit,
                'notional_value': final_notional_value, 'margin_used': margin_used,
                'trailing_active': False, 'activation_price': activation_price,
                'peak_price': entry_price, 'callback_rate': callback_rate,
                'last_known_price': entry_price, 
                'symbol_key': symbol_key, 
                'config_key': config_key, 
                'risk_per_trade_pct': risk_per_trade_pct,
                'risk_reward_ratio': risk_reward_ratio
            }

            signal_idx += 1

        # --- 3c. Equity Curve und Drawdown aktualisieren ---
        current_total_equity = equity + unrealized_pnl
        equity_curve.append({'timestamp': ts, 'equity': current_total_equity})

        peak_equity = max(peak_equity, current_total_equity)
        drawdown = (peak_equity - current_total_equity) / peak_equity if peak_equity > 0 else 0
        if drawdown > max_drawdown_pct:
            max_drawdown_pct = drawdown
            max_drawdown_date = ts

        min_equity_ever = min(min_equity_ever, current_total_equity)
        if current_total_equity <= 0 and not liquidation_date:
            liquidation_date = ts

    # 4/4: Ergebnisse vorbereiten
    print("4/4: Bereite Analyse-Ergebnisse vor...")
    final_equity = equity_curve[-1]['equity'] if equity_curve else start_capital
    total_pnl_pct = (final_equity / start_capital - 1) * 100 if start_capital > 0 else 0
    wins = sum(1 for t in trade_history if t['pnl'] > 0)
    trade_count = len(trade_history)
    win_rate = (wins / trade_count * 100) if trade_count else 0

    trade_df = pd.DataFrame(trade_history)
    strategy_key_col = 'config_key' 

    pnl_per_strategy = trade_df.groupby(strategy_key_col)['pnl'].sum().reset_index() if not trade_df.empty else pd.DataFrame(columns=[strategy_key_col, 'pnl'])
    trades_per_strategy = trade_df.groupby(strategy_key_col).size().reset_index(name='trades') if not trade_df.empty else pd.DataFrame(columns=[strategy_key_col, 'trades'])

    equity_df = pd.DataFrame(equity_curve)
    if not equity_df.empty:
        equity_df['peak'] = equity_df['equity'].cummax()
        equity_df['drawdown_pct'] = ((equity_df['peak'] - equity_df['equity']) / equity_df['peak'].replace(0, np.nan)).fillna(0)
        equity_df['timestamp'] = pd.to_datetime(equity_df['timestamp'])
        equity_df.set_index('timestamp', inplace=True, drop=False)

    print("Analyse abgeschlossen.")

    return {
        "start_capital": start_capital, "end_capital": final_equity, "total_pnl_pct": total_pnl_pct,
        "trade_count": trade_count, "win_rate": win_rate, "max_drawdown_pct": max_drawdown_pct * 100,
        "max_drawdown_date": max_drawdown_date, "min_equity": min_equity_ever, "liquidation_date": liquidation_date,
        "pnl_per_strategy": pnl_per_strategy, "trades_per_strategy": trades_per_strategy,
        "equity_curve": equity_df
    }
