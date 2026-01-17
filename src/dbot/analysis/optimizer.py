import sys
print("optimizer.py ist veraltet. dbot nutzt keine ANN-Pipeline mehr. Bitte ./show_results.sh für SMC-Backtests verwenden.")
sys.exit(1)

import os
import json
import optuna
import numpy as np
import argparse

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
import logging
logging.getLogger('tensorflow').setLevel(logging.ERROR)
logging.getLogger('absl').setLevel(logging.ERROR)
import warnings
warnings.filterwarnings('ignore', category=UserWarning, module='keras')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.analysis.backtester import load_data, run_ann_backtest
from dbot.utils.telegram import send_message
from dbot.analysis.evaluator import evaluate_dataset

optuna.logging.set_verbosity(optuna.logging.WARNING)
HISTORICAL_DATA = None
CURRENT_MODEL_PATHS = {}
CURRENT_TIMEFRAME = None
FIXED_THRESHOLD = None

MAX_DRAWDOWN_CONSTRAINT = 0.30
MIN_WIN_RATE_CONSTRAINT = 55.0
MIN_PNL_CONSTRAINT = 0.0
START_CAPITAL = 1000
OPTIM_MODE = "strict"


def objective(trial, symbol):
    params = {
        'prediction_threshold': FIXED_THRESHOLD,
        'risk_reward_ratio': trial.suggest_float('risk_reward_ratio', 2.5, 3.5),
        'risk_per_trade_pct': trial.suggest_float('risk_per_trade_pct', 8.0, 12.0),
        'leverage': trial.suggest_int('leverage', 5, 10),
        'atr_multiplier_sl': trial.suggest_float('atr_multiplier_sl', 0.8, 1.2),
        'min_sl_pct': trial.suggest_float('min_sl_pct', 0.8, 1.2),
        'trailing_stop_activation_rr': trial.suggest_float('trailing_stop_activation_rr', 1.3, 1.7),
        'trailing_stop_callback_rate_pct': trial.suggest_float('trailing_stop_callback_rate_pct', 0.3, 0.8),
        'volume_spike_multiplier': trial.suggest_float('volume_spike_multiplier', 1.3, 2.0),
        'min_atr_multiplier': trial.suggest_float('min_atr_multiplier', 1.1, 1.8),
        'min_adx': trial.suggest_int('min_adx', 15, 30)
    }

    result = run_ann_backtest(
        HISTORICAL_DATA.copy(),
        params,
        CURRENT_MODEL_PATHS,
        START_CAPITAL,
        timeframe=CURRENT_TIMEFRAME
    )

    pnl = result.get('total_pnl_pct', -1000)
    drawdown = result.get('max_drawdown_pct', 1.0)
    trades = result.get('trades_count', 0)
    win_rate = result.get('win_rate', 0)

    if OPTIM_MODE == "strict" and (drawdown > MAX_DRAWDOWN_CONSTRAINT or win_rate < MIN_WIN_RATE_CONSTRAINT or pnl < MIN_PNL_CONSTRAINT or trades < 50):
        raise optuna.exceptions.TrialPruned()
    elif OPTIM_MODE == "best_profit" and (drawdown > MAX_DRAWDOWN_CONSTRAINT or trades < 50):
        raise optuna.exceptions.TrialPruned()

    drawdown_safe = max(drawdown, 0.01)
    return pnl / drawdown_safe


def create_safe_filename(symbol, timeframe):
    return f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"


def main():
    global HISTORICAL_DATA, CURRENT_MODEL_PATHS, CURRENT_TIMEFRAME, FIXED_THRESHOLD, MAX_DRAWDOWN_CONSTRAINT, MIN_WIN_RATE_CONSTRAINT, MIN_PNL_CONSTRAINT, START_CAPITAL, OPTIM_MODE

    parser = argparse.ArgumentParser(description="Parameter-Optimierung für DBot")
    parser.add_argument('--symbols', required=True, type=str)
    parser.add_argument('--timeframes', required=True, type=str)
    parser.add_argument('--start_date', required=True, type=str)
    parser.add_argument('--end_date', required=True, type=str)
    parser.add_argument('--jobs', required=True, type=int)
    parser.add_argument('--max_drawdown', required=True, type=float)
    parser.add_argument('--start_capital', required=True, type=float)
    parser.add_argument('--min_win_rate', required=True, type=float)
    parser.add_argument('--trials', required=True, type=int)
    parser.add_argument('--min_pnl', required=True, type=float)
    parser.add_argument('--mode', required=True, type=str)
    parser.add_argument('--threshold', required=True, type=float)
    parser.add_argument('--top_n', type=int, default=0)
    args = parser.parse_args()

    FIXED_THRESHOLD = args.threshold
    MAX_DRAWDOWN_CONSTRAINT = args.max_drawdown / 100.0
    MIN_WIN_RATE_CONSTRAINT = args.min_win_rate
    MIN_PNL_CONSTRAINT = args.min_pnl
    START_CAPITAL = args.start_capital
    N_TRIALS = args.trials
    OPTIM_MODE = args.mode
    TOP_N_STRATEGIES = args.top_n

    symbols, timeframes = args.symbols.split(), args.timeframes.split()
    tasks = [{'symbol': f"{s}/USDT:USDT", 'timeframe': tf} for s in symbols for tf in timeframes]

    for task in tasks:
        symbol, timeframe = task['symbol'], task['timeframe']
        CURRENT_TIMEFRAME = timeframe

        print(f"\n===== Optimiere: {symbol} ({timeframe}) mit festem Threshold: {FIXED_THRESHOLD} =====")

        safe_filename = create_safe_filename(symbol, timeframe)
        CURRENT_MODEL_PATHS = {
            'model': os.path.join(PROJECT_ROOT, 'artifacts', 'models', f'ann_predictor_{safe_filename}.h5'),
            'scaler': os.path.join(PROJECT_ROOT, 'artifacts', 'models', f'ann_scaler_{safe_filename}.joblib')
        }

        HISTORICAL_DATA = load_data(symbol, timeframe, args.start_date, args.end_date)
        if HISTORICAL_DATA.empty:
            continue

        print("\n--- Bewertung der Datensatz-Qualität ---")
        evaluation = evaluate_dataset(HISTORICAL_DATA.copy(), timeframe)
        print(f"Note: {evaluation['score']} / 10\n" + "\n".join(evaluation['justification']) + "\n----------------------------------------")

        db_file = os.path.join(PROJECT_ROOT, 'artifacts', 'db', 'optuna_studies.db')
        os.makedirs(os.path.dirname(db_file), exist_ok=True)

        storage_url = f"sqlite:///{db_file}?timeout=60"
        study_name = f"ann_{safe_filename}_{OPTIM_MODE}"

        study = optuna.create_study(storage=storage_url, study_name=study_name, direction="maximize", load_if_exists=True)

        objective_wrapper = lambda trial: objective(trial, symbol)
        study.optimize(objective_wrapper, n_trials=N_TRIALS, n_jobs=args.jobs, show_progress_bar=True)

        valid_trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
        if not valid_trials:
            print(f"\n❌ FEHLER: Für {symbol} ({timeframe}) konnte keine Konfiguration gefunden werden.")
            continue

        best_trial = max(valid_trials, key=lambda t: t.value)
        best_params = best_trial.params
        best_params['prediction_threshold'] = FIXED_THRESHOLD

        config_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
        os.makedirs(config_dir, exist_ok=True)
        config_output_path = os.path.join(config_dir, f'config_{safe_filename}.json')

        behavior_config = {"use_longs": True, "use_shorts": True}

        config_output = {
            "market": {"symbol": symbol, "timeframe": timeframe},
            "strategy": {"prediction_threshold": FIXED_THRESHOLD},
            "risk": {
                "margin_mode": "isolated",
                "risk_per_trade_pct": round(best_params['risk_per_trade_pct'], 2),
                "risk_reward_ratio": round(best_params['risk_reward_ratio'], 2),
                "leverage": best_params['leverage'],
                "trailing_stop_activation_rr": round(best_params['trailing_stop_activation_rr'], 2),
                "trailing_stop_callback_rate_pct": round(best_params['trailing_stop_callback_rate_pct'], 2),
                'atr_multiplier_sl': round(best_params['atr_multiplier_sl'], 2),
                'min_sl_pct': round(best_params['min_sl_pct'], 2)
            },
            "filters": {
                "volume_spike_multiplier": round(best_params['volume_spike_multiplier'], 2),
                "min_atr_multiplier": round(best_params['min_atr_multiplier'], 2),
                "min_adx": best_params['min_adx']
            },
            "behavior": behavior_config
        }
        with open(config_output_path, 'w') as f:
            json.dump(config_output, f, indent=4)
        print(f"\n✔ Beste Konfiguration wurde in '{config_output_path}' gespeichert.")

    try:
        with open(os.path.join(PROJECT_ROOT, 'secret.json'), "r") as f:
            secrets = json.load(f)
        telegram_config = secrets.get('telegram', {})
    except Exception:
        telegram_config = {}


if __name__ == "__main__":
    main()
