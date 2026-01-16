# src/dbot/analysis/show_results.py (Version 1 - Ported from JaegerBot)
import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import date, datetime
import logging
import argparse

logging.getLogger('tensorflow').setLevel(logging.ERROR)
logging.getLogger('absl').setLevel(logging.ERROR)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.analysis.backtester import load_data
from dbot.utils.ann_model import load_model_and_scaler
from dbot.analysis.portfolio_simulator import run_portfolio_simulation
from dbot.analysis.portfolio_optimizer import run_portfolio_optimizer
from dbot.utils.telegram import send_document


# --- Helper-Funktion für die Einzelanalyse (Modus 1) ---
def run_single_analysis_via_simulator(start_date, end_date, start_capital):
    print("--- DBot Ergebnis-Analyse (Einzel-Modus via Simulator) ---")
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    models_dir = os.path.join(PROJECT_ROOT, 'artifacts', 'models')
    all_results = []
    
    config_files = sorted([f for f in os.listdir(configs_dir) if f.startswith('config_') and f.endswith('.json')])

    if not config_files:
        print("\nKeine gültigen Konfigurationen zum Analysieren gefunden.")
        return

    for filename in config_files:
        config_path = os.path.join(configs_dir, filename)
        if not os.path.exists(config_path):
            continue

        with open(config_path, 'r') as f:
            config = json.load(f)

        symbol, timeframe = config['market']['symbol'], config['market']['timeframe']
        strategy_name = f"{symbol} ({timeframe})"

        print(f"\nAnalysiere Ergebnisse für: {strategy_name}...")

        safe_filename = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
        model_paths = {
            'model': os.path.join(models_dir, f'ann_predictor_{safe_filename}.h5'),
            'scaler': os.path.join(models_dir, f'ann_scaler_{safe_filename}.joblib')
        }

        if not os.path.exists(model_paths['model']):
            print(f"--> WARNUNG: Modell nicht gefunden. Überspringe.")
            continue

        data = load_data(symbol, timeframe, start_date, end_date)
        if data.empty:
            print(f"--> WARNUNG: Konnte keine Daten laden. Überspringe.")
            continue

        strategies_data = {
            symbol: {
                'symbol': symbol, 
                'timeframe': timeframe, 
                'data': data, 
                'model': load_model_and_scaler(model_paths['model'], model_paths['scaler'])[0], 
                'scaler': load_model_and_scaler(model_paths['model'], model_paths['scaler'])[1], 
                'params': {**config.get('strategy', {}), **config.get('risk', {})}
            }
        }
        
        result = run_portfolio_simulation(start_capital, strategies_data, start_date, end_date)
        
        if result['trade_count'] == 0:
            pnl_value = 0.0
            end_capital_value = start_capital
        else:
            pnl_value = result['total_pnl_pct']
            end_capital_value = result['end_capital']

        all_results.append({
            "Strategie": strategy_name,
            "Trades": result['trade_count'],
            "PnL %": pnl_value,
            "Max DD %": result['max_drawdown_pct'],
            "Endkapital": end_capital_value
        })

    if not all_results:
        print("\nKeine gültigen Konfigurationen mehr übrig.")
        return

    results_df = pd.DataFrame(all_results)
    results_df = results_df.sort_values(by="PnL %", ascending=False)

    display_columns = ["Strategie", "Trades", "PnL %", "Max DD %", "Endkapital"]

    pd.set_option('display.width', 1000)
    pd.set_option('display.max_columns', None)
    print("\n\n==================================================================================")
    print(f"                 Zusammenfassung (Startkapital: {start_capital} USDT)")
    print("==================================================================================")
    pd.set_option('display.float_format', '{:.2f}'.format)
    print(results_df.fillna('-').to_string(index=False, columns=display_columns))
    print("==================================================================================")


def run_shared_mode(is_auto: bool, start_date, end_date, start_capital, max_drawdown=100.0):
    mode_name = "Automatische Portfolio-Optimierung" if is_auto else "Manuelle Portfolio-Simulation"
    print(f"--- DBot {mode_name} ---")
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    models_dir = os.path.join(PROJECT_ROOT, 'artifacts', 'models')
    available_strategies = []
    
    if os.path.isdir(configs_dir):
        for filename in sorted(os.listdir(configs_dir)):
            if filename.startswith('config_') and filename.endswith('.json'):
                base_name = filename.replace('config_', '').replace('.json', '').replace('_macd', '')
                try:
                    parts = base_name.split('_')
                    timeframe = parts[-1]
                    symbol_part = "_".join(parts[:-1])
                    model_name = f"ann_predictor_{symbol_part}_{timeframe}.h5"
                    if os.path.exists(os.path.join(models_dir, model_name)):
                        available_strategies.append(filename)
                except IndexError:
                    continue
    
    if not available_strategies:
        print("Keine optimierten Strategien gefunden.")
        return

    selected_files = []
    if not is_auto:
        print("\nVerfügbare Strategien:")
        for i, name in enumerate(available_strategies):
            print(f"  {i+1}) {name}")
        selection = input("\nWelche Strategien sollen simuliert werden? (Zahlen mit Komma, z.B. 1,3,4 oder 'alle'): ")
        try:
            if selection.lower() == 'alle':
                selected_files = available_strategies
            else:
                selected_files = [available_strategies[int(i.strip()) - 1] for i in selection.split(',')]
        except (ValueError, IndexError):
            print("Ungültige Auswahl. Breche ab.")
            return
    else: 
        selected_files = available_strategies

    strategies_data = {}
    print("\nLade Daten und Modelle für gewählte Strategien...")
    for filename in selected_files:
        with open(os.path.join(configs_dir, filename), 'r') as f:
            config = json.load(f)
        symbol, timeframe = config['market']['symbol'], config['market']['timeframe']
        safe_filename = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
        
        model_paths = {
            'model': os.path.join(models_dir, f'ann_predictor_{safe_filename}.h5'),
            'scaler': os.path.join(models_dir, f'ann_scaler_{safe_filename}.joblib')
        }
        try:
            model, scaler = load_model_and_scaler(model_paths['model'], model_paths['scaler'])
        except Exception as e:
            print(f"WARNUNG: Konnte Modell/Scaler für {filename} nicht laden. Fehler: {e}. Wird ignoriert.")
            continue
            
        data = load_data(symbol, timeframe, start_date, end_date)
        if model and scaler and not data.empty:
            strategies_data[symbol] = {
                'symbol': symbol, 'timeframe': timeframe, 'data': data,
                'model': model, 'scaler': scaler,
                'params': {**config.get('strategy', {}), **config.get('risk', {})}
            }
        else:
            print(f"WARNUNG: Konnte Daten/Modell für {filename} nicht laden. Wird ignoriert.")
    
    if not strategies_data:
        print("Konnte für keine der gewählten Strategien Daten laden. Breche ab.")
        return

    equity_df = pd.DataFrame()
    csv_path = ""
    caption = ""
    trade_count = 0
    
    try:
        d1 = datetime.strptime(start_date, "%Y-%m-%d")
        d2 = datetime.strptime(end_date, "%Y-%m-%d")
        total_days = (d2 - d1).days
        if total_days <= 0:
            total_days = 1
    except Exception:
        total_days = 0

    if is_auto:
        print(f"\nINFO: Starte Optimierung mit maximal {max_drawdown:.2f}% Drawdown-Beschränkung.")

        strategies_data_for_optimizer = {}
        for filename in selected_files:
            try:
                with open(os.path.join(configs_dir, filename), 'r') as f:
                    config = json.load(f)
                symbol_key = config['market']['symbol']
                if symbol_key in strategies_data:
                    strategies_data_for_optimizer[filename] = strategies_data[symbol_key]
            except Exception:
                pass

        results = run_portfolio_optimizer(start_capital, strategies_data_for_optimizer, start_date, end_date, max_drawdown)

        if results and 'final_result' in results:
            final_report = results['final_result']
            trade_count = final_report.get('trade_count', 0)
            
            days_per_trade_str = ""
            if trade_count > 0 and total_days > 0:
                days_per_trade = total_days / trade_count
                days_per_trade_str = f" (entspricht 1 Trade alle {days_per_trade:.1f} Tage)"

            print("\n=======================================================")
            print("     Ergebnis der automatischen Portfolio-Optimierung")
            print("=======================================================")
            print(f"Zeitraum: {start_date} bis {end_date} ({total_days} Tage)\nStartkapital: {start_capital:.2f} USDT")
            print(f"Maximal erlaubter DD: {max_drawdown:.2f}%")
            print("\nOptimales Portfolio gefunden (" + str(len(results['optimal_portfolio'])) + " Strategien):")
            for strat_filename in results['optimal_portfolio']:
                print(f"  - {strat_filename}")
            print("\n--- Simulierte Performance dieses optimalen Portfolios ---")
            print(f"Endkapital:       {final_report['end_capital']:.2f} USDT")
            print(f"Gesamt PnL:       {final_report['end_capital'] - start_capital:+.2f} USDT ({final_report['total_pnl_pct']:.2f}%)")
            print(f"Anzahl Trades:    {trade_count}{days_per_trade_str}")
            print(f"Portfolio Max DD:   {final_report['max_drawdown_pct']:.2f}%")
            print(f"Liquidiert:       {'JA, am ' + final_report['liquidation_date'].strftime('%Y-%m-%d') if final_report['liquidation_date'] else 'NEIN'}")

            optimal_configs_file = os.path.join(PROJECT_ROOT, '.optimal_configs.tmp')
            with open(optimal_configs_file, 'w') as f:
                f.write('\n'.join(results['optimal_portfolio']))
            
            csv_path = os.path.join(PROJECT_ROOT, 'optimal_portfolio_equity.csv')
            caption = f"Automatischer Portfolio-Optimierungsbericht\nMax. erlaubter DD: {max_drawdown:.2f}%\nTrades: {trade_count}{days_per_trade_str}\nEndkapital: {final_report['end_capital']:.2f} USDT"
            equity_df = final_report.get('equity_curve')
        else:
            print("\n=======================================================")
            print("     Ergebnis der automatischen Portfolio-Optimierung")
            print("=======================================================")
            print(f"❌ Es konnte kein Portfolio gefunden werden, das die Drawdown-Beschränkung von {max_drawdown:.2f}% erfüllt.")
            
    else:
        print("\n--- Starte Manuelle Portfolio-Simulation... ---")
        
        final_report = run_portfolio_simulation(start_capital, strategies_data, start_date, end_date)
        
        trade_count = final_report.get('trade_count', 0)
        
        days_per_trade_str = ""
        if trade_count > 0 and total_days > 0:
            days_per_trade = total_days / trade_count
            days_per_trade_str = f" (entspricht 1 Trade alle {days_per_trade:.1f} Tage)"

        print("\n=======================================================")
        print("     Ergebnis der Manuellen Portfolio-Simulation")
        print("=======================================================")
        print(f"Zeitraum: {start_date} bis {end_date} ({total_days} Tage)\nStartkapital: {start_capital:.2f} USDT")
        print(f"Simulierte Strategien: {len(strategies_data)}")
        for key in strategies_data.keys():
            print(f"  - {key}")
            
        print("\n--- Simulierte Performance dieses Portfolios ---")
        print(f"Endkapital:       {final_report['end_capital']:.2f} USDT")
        print(f"Gesamt PnL:       {final_report['end_capital'] - start_capital:+.2f} USDT ({final_report['total_pnl_pct']:.2f}%)")
        print(f"Anzahl Trades:    {trade_count}{days_per_trade_str}")
        print(f"Portfolio Max DD:   {final_report['max_drawdown_pct']:.2f}%")
        print(f"Liquidiert:       {'JA, am ' + final_report['liquidation_date'].strftime('%Y-%m-%d') if final_report['liquidation_date'] else 'NEIN'}")
        
        csv_path = os.path.join(PROJECT_ROOT, 'manual_portfolio_equity.csv')
        caption = f"Manueller Portfolio-Bericht\nStrategien: {len(strategies_data)}\nTrades: {trade_count}{days_per_trade_str}\nEndkapital: {final_report['end_capital']:.2f} USDT"
        equity_df = final_report.get('equity_curve')

    if equity_df is not None and not equity_df.empty:
        print("\n--- Export ---")
        print(f"✔ Details zur Equity-Kurve wurden nach '{os.path.basename(csv_path)}' exportiert.")
        equity_df[['timestamp', 'equity', 'drawdown_pct']].to_csv(csv_path, index=False)
        print("=======================================================")

        try:
            with open(os.path.join(PROJECT_ROOT, 'secret.json'), 'r') as f:
                secrets = json.load(f)
            telegram_config = secrets.get('telegram', {})
            if telegram_config.get('bot_token'):
                print("Sende Bericht an Telegram...")
                send_document(telegram_config.get('bot_token'), telegram_config.get('chat_id'), csv_path, caption)
                print("✔ Bericht wurde erfolgreich an Telegram gesendet.")
        except Exception as e:
            print(f"ⓘ Konnte Bericht nicht an Telegram senden: {e}")
    else:
        if is_auto:
            pass
        else:
            print("\nKeine Equity-Daten zum Exportieren vorhanden (Möglicherweise 0 Trades).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', default='1', type=str)
    args = parser.parse_args()
    
    print("\n--- Bitte Konfiguration für den Backtest festlegen ---")
    start_date = input(f"Startdatum (JJJJ-MM-TT) [Standard: 2023-01-01]: ") or "2023-01-01"
    end_date = input(f"Enddatum (JJJJ-MM-TT) [Standard: Heute]: ") or date.today().strftime("%Y-%m-%d")
    start_capital = int(input(f"Startkapital in USDT eingeben [Standard: 1000]: ") or 1000)

    max_dd_input = 100.0
    if args.mode == '3':
        max_dd_input = float(input(f"Gewünschten maximalen Drawdown in % eingeben [Standard: 30]: ") or 30.0)

    print("--------------------------------------------------")
    if args.mode == '2':
        run_shared_mode(is_auto=False, start_date=start_date, end_date=end_date, start_capital=start_capital, max_drawdown=100.0)
    elif args.mode == '3':
        run_shared_mode(is_auto=True, start_date=start_date, end_date=end_date, start_capital=start_capital, max_drawdown=max_dd_input)
    else:
        run_single_analysis_via_simulator(start_date=start_date, end_date=end_date, start_capital=start_capital)
