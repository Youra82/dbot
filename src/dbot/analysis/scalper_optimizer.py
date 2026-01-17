#!/usr/bin/env python3
"""
Scalper Strategy Parameter Optimizer
Findet die besten Parameter für aggressive_scalper.py durch Grid-Search
"""

import os
import sys
import json
import argparse
from itertools import product
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.analysis.scalper_backtester import fetch_ohlcv, simulate_smc_backtest


def get_optimized_date_range(timeframe, end_date=None):
    """
    Intelligente Datumsbereich-Auswahl basierend auf Timeframe
    """
    if end_date is None:
        # Gestern verwenden (heute hat noch keine vollständigen Daten)
        end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    
    # Für 1m: nur 1 Tag (zu viele Daten sonst)
    # Für 5m: 3 Tage
    # Für 15m+: 7 Tage
    if timeframe == '1m':
        days = 1
    elif timeframe == '5m':
        days = 3
    else:
        days = 7
    
    start_dt = end_dt - timedelta(days=days)
    return start_dt.strftime('%Y-%m-%d'), end_date


def create_parameter_grid():
    """
    Erstellt eine reduzierte Parameter-Grid für Grid-Search
    Statt 243 Kombinationen: ~24 Kombinationen
    """
    return {
        'rsi_oversold': [25, 30],       # 2 Werte
        'rsi_overbought': [70, 75],     # 2 Werte
        'ema_fast': [5, 8],             # 2 Werte
        'ema_slow': [20, 30],           # 2 Werte
        'min_confidence': [0.5, 0.6],   # 2 Werte
        'roc_threshold': [0.2, 0.3]     # 2 Werte
    }
    # Total: 2^6 = 64 Kombinationen (akzeptabel)


def run_single_backtest(symbol, timeframe, start_date, end_date, params):
    """
    Führt einen einzelnen Backtest mit gegebenen Parametern durch
    """
    try:
        df = fetch_ohlcv(symbol, timeframe, start_date, end_date)
        if df is None or df.empty or len(df) < 100:
            return None
        
        result = simulate_smc_backtest(df, params)
        
        if 'error' in result:
            return None
        
        return {
            'pnl_pct': result['pnl_pct'],
            'trades': result['trades_count'],
            'win_rate': result['win_rate'],
            'max_dd': result['max_drawdown_pct'],
            'final_equity': result['final_equity'],
            'params': params.copy()
        }
    except Exception as e:
        print(f"  [ERROR] {e}", flush=True)
        return None


def optimize_parameters(symbol, timeframe, start_date, end_date, start_capital=1000):
    """
    Optimiert Parameter durch Grid-Search
    """
    print(f"\n{'='*60}")
    print(f"  Optimizer für {symbol} ({timeframe})")
    print(f"  Zeitraum: {start_date} → {end_date}")
    print(f"{'='*60}\n")
    
    # Parameter-Grid erstellen
    param_grid = create_parameter_grid()
    
    # Alle Kombinationen generieren
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    combinations = list(product(*values))
    
    total_combinations = len(combinations)
    print(f"Testing {total_combinations} parameter combinations...")
    print(f"(Progress wird angezeigt: X/{total_combinations})\n")
    
    results = []
    best_result = None
    best_score = -float('inf')
    
    for idx, combo in enumerate(combinations, 1):
        # Parameter-Dict erstellen
        params = {
            'start_capital': start_capital,
            # Strategy params
            'rsi_period': 14,
            'rsi_oversold': combo[0],
            'rsi_overbought': combo[1],
            'ema_fast': combo[2],
            'ema_slow': combo[3],
            'min_confidence': combo[4],
            'roc_threshold': combo[5]
        }
        
        # Progress anzeigen (jede 5. oder bei wichtigen)
        if idx % 5 == 0 or idx == 1 or idx == total_combinations:
            print(f"[{idx}/{total_combinations}] Testing: RSI={combo[0]}/{combo[1]} EMA={combo[2]}/{combo[3]} Conf={combo[4]} ROC={combo[5]}", flush=True)
        
        result = run_single_backtest(symbol, timeframe, start_date, end_date, params)
        
        if result is None:
            continue
        
        results.append(result)
        
        # Scoring: PnL × Win-Rate - Max-DD
        # Ziel: Hoher PnL, hohe Win-Rate, niedriger Drawdown
        score = result['pnl_pct'] * (result['win_rate'] / 100.0) - (result['max_dd'] * 0.5)
        
        if score > best_score:
            best_score = score
            best_result = result
            print(f"  → NEW BEST! PnL={result['pnl_pct']:.2f}% WR={result['win_rate']:.1f}% DD={result['max_dd']:.2f}% Trades={result['trades']} (Score={score:.2f})")
    
    return best_result, results


def save_best_config(symbol, timeframe, best_result, output_dir='artifacts/optimized_configs'):
    """
    Speichert die beste Konfiguration
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Clean symbol name für Dateiname
    safe_symbol = symbol.replace('/', '').replace(':', '')
    filename = f"best_config_{safe_symbol}_{timeframe}.json"
    filepath = os.path.join(output_dir, filename)
    
    config = {
        'symbol': symbol,
        'timeframe': timeframe,
        'optimized_at': datetime.now().isoformat(),
        'performance': {
            'pnl_pct': best_result['pnl_pct'],
            'trades': best_result['trades'],
            'win_rate': best_result['win_rate'],
            'max_drawdown': best_result['max_dd']
        },
        'parameters': best_result['params']
    }
    
    with open(filepath, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"\n[SUCCESS] Best config saved to: {filepath}")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Scalper Strategy Optimizer")
    parser.add_argument('--symbol', required=True, help='Trading symbol (e.g., BTC/USDT:USDT)')
    parser.add_argument('--timeframe', required=True, help='Timeframe (1m, 5m, 15m)')
    parser.add_argument('--start_date', help='Start date YYYY-MM-DD (auto if not set)')
    parser.add_argument('--end_date', help='End date YYYY-MM-DD (today if not set)')
    parser.add_argument('--start_capital', type=float, default=1000, help='Starting capital in USDT')
    
    args = parser.parse_args()
    
    # Intelligente Datumsbereich-Auswahl
    if not args.start_date or not args.end_date:
        args.start_date, args.end_date = get_optimized_date_range(args.timeframe, args.end_date)
        print(f"[INFO] Auto-selected date range: {args.start_date} -> {args.end_date}")
    
    # Optimierung durchführen
    best_result, all_results = optimize_parameters(
        args.symbol,
        args.timeframe,
        args.start_date,
        args.end_date,
        args.start_capital
    )
    
    if best_result is None:
        print("\n[ERROR] No valid results found. Try different parameters or date range.")
        sys.exit(1)
    
    # Beste Config speichern
    config_path = save_best_config(args.symbol, args.timeframe, best_result)
    
    # Zusammenfassung
    print(f"\n{'='*60}")
    print(f"  OPTIMIZATION COMPLETE")
    print(f"{'='*60}")
    print(f"Best Parameters:")
    for key, value in best_result['params'].items():
        if key != 'start_capital':
            print(f"  {key}: {value}")
    print(f"\nPerformance:")
    print(f"  PnL: {best_result['pnl_pct']:.2f}%")
    print(f"  Win-Rate: {best_result['win_rate']:.1f}%")
    print(f"  Trades: {best_result['trades']}")
    print(f"  Max DD: {best_result['max_dd']:.2f}%")
    print(f"\nTotal tested: {len(all_results)} valid combinations")
    print(f"Config saved: {config_path}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
