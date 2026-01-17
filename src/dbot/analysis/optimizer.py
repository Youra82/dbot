"""DBot Physics-Optimizer

Optuna-Optimierung für die Physics-Strategie von DBot.
Verwendet den Backtester aus dbot.analysis.backtester und schreibt
Configs nach src/dbot/strategy/configs/.
"""
import os
import sys
import json
import optuna
import numpy as np
import argparse
import logging
import warnings

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
logging.getLogger('tensorflow').setLevel(logging.ERROR)
logging.getLogger('absl').setLevel(logging.ERROR)
warnings.filterwarnings('ignore', category=UserWarning, module='keras')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.analysis.backtester import load_data, run_backtest
from dbot.analysis.evaluator import evaluate_dataset
from dbot.utils.timeframe_utils import determine_htf

optuna.logging.set_verbosity(optuna.logging.WARNING)

HISTORICAL_DATA = None
CURRENT_SYMBOL = None
CURRENT_TIMEFRAME = None
CURRENT_HTF = None
CONFIG_SUFFIX = ""
MAX_DRAWDOWN_CONSTRAINT = 0.30
MIN_WIN_RATE_CONSTRAINT = 55.0
MIN_PNL_CONSTRAINT = 0.0
START_CAPITAL = 1000
OPTIM_MODE = "strict"

def create_safe_filename(symbol, timeframe):
    return f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"

def objective(trial):
    """Optuna-Objective für die Physics-Strategie.

    Optimiert die wichtigsten Physik-Parameter (VWAP/ATR/Momentum/Volumen/EMA)
    und generische Risiko-Settings.
    """

    strategy_params = {
        'type': 'physics',
        'enable_vwap_setup': True,
        'enable_impulse_pullback': True,
        'enable_volatility_expansion': True,

        # PhysicsEngine-Basics
        'atr_period': trial.suggest_int('atr_period', 10, 20),
        'atr_multiplier_trend': trial.suggest_float('atr_multiplier_trend', 1.2, 2.0),
        'momentum_period': trial.suggest_int('momentum_period', 5, 15),
        'momentum_sma_period': trial.suggest_int('momentum_sma_period', 2, 5),
        'volume_ma_period': trial.suggest_int('volume_ma_period', 10, 40),
        'volume_threshold': trial.suggest_float('volume_threshold', 1.1, 2.0),
        'regime_atr_threshold': trial.suggest_float('regime_atr_threshold', 0.01, 0.05),
        'ema_fast': trial.suggest_int('ema_fast', 10, 40),
        'ema_slow': trial.suggest_int('ema_slow', 30, 80),
        'range_lookback': trial.suggest_int('range_lookback', 10, 30),
        'range_overlap_threshold': trial.suggest_float('range_overlap_threshold', 0.6, 0.9),

        # Trade-Logik-Parameter
        'vwap_mean_reversion_threshold': trial.suggest_float('vwap_mean_reversion_threshold', 1.0, 3.0),
        'momentum_threshold': trial.suggest_float('momentum_threshold', 0.3, 1.0),
        'sl_atr_multiplier': trial.suggest_float('sl_atr_multiplier', 1.0, 2.0),
        'tp_atr_multiplier': trial.suggest_float('tp_atr_multiplier', 1.5, 3.0),
        'tp_atr_multiplier_expansion': trial.suggest_float('tp_atr_multiplier_expansion', 2.0, 4.0),
        'exit_on_regime_change': True,
        'exit_on_momentum_reversal': True,
        'exit_on_vwap_cross': False,
        'exit_on_energy_loss': True,

        # Supertrend-Settings für MTF-Bias im Live-Betrieb
        'supertrend_atr_period': trial.suggest_int('supertrend_atr_period', 7, 14),
        'supertrend_multiplier': trial.suggest_float('supertrend_multiplier', 2.0, 4.0),

        'symbol': CURRENT_SYMBOL,
        'timeframe': CURRENT_TIMEFRAME,
        'htf': CURRENT_HTF,
    }

    risk_params = {
        'risk_reward_ratio': trial.suggest_float('risk_reward_ratio', 1.5, 3.5),
        'risk_per_trade_pct': trial.suggest_float('risk_per_trade_pct', 0.5, 2.0),
        'leverage': trial.suggest_int('leverage', 3, 10),
        'trailing_stop_activation_rr': trial.suggest_float('trailing_stop_activation_rr', 1.0, 3.0),
        'trailing_stop_callback_rate_pct': trial.suggest_float('trailing_stop_callback_rate_pct', 0.3, 2.0),
        'atr_multiplier_sl': trial.suggest_float('atr_multiplier_sl', 1.2, 3.0),
        'min_sl_pct': 0.5,
    }

    result = run_backtest(HISTORICAL_DATA.copy(), strategy_params, risk_params, START_CAPITAL, verbose=False)
    
    pnl = result.get('total_pnl_pct', -1000)
    drawdown = result.get('max_drawdown_pct', 1.0)
    trades = result.get('trades_count', 0)
    win_rate = result.get('win_rate', 0)

    if OPTIM_MODE == "strict" and (
        drawdown > MAX_DRAWDOWN_CONSTRAINT or win_rate < MIN_WIN_RATE_CONSTRAINT or
        pnl < MIN_PNL_CONSTRAINT or trades < 30):
        raise optuna.exceptions.TrialPruned()
    elif OPTIM_MODE == "best_profit" and (
        drawdown > MAX_DRAWDOWN_CONSTRAINT or trades < 30):
        raise optuna.exceptions.TrialPruned()

    return pnl

def main():
    global HISTORICAL_DATA, CURRENT_SYMBOL, CURRENT_TIMEFRAME, CURRENT_HTF, CONFIG_SUFFIX, MAX_DRAWDOWN_CONSTRAINT, MIN_WIN_RATE_CONSTRAINT, MIN_PNL_CONSTRAINT, START_CAPITAL, OPTIM_MODE
    parser = argparse.ArgumentParser(description="Parameter-Optimierung für DBot Physics-Strategie")
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
    parser.add_argument('--config_suffix', type=str, default="")
    args = parser.parse_args()

    CONFIG_SUFFIX = args.config_suffix
    MAX_DRAWDOWN_CONSTRAINT, MIN_WIN_RATE_CONSTRAINT, MIN_PNL_CONSTRAINT = args.max_drawdown / 100.0, args.min_win_rate, args.min_pnl
    START_CAPITAL, N_TRIALS, OPTIM_MODE = args.start_capital, args.trials, args.mode

    symbols, timeframes = args.symbols.split(), args.timeframes.split()
    TASKS = [{'symbol': f"{s}/USDT:USDT", 'timeframe': tf} for s in symbols for tf in timeframes]

    for task in TASKS:
        symbol, timeframe = task['symbol'], task['timeframe']
        CURRENT_SYMBOL = symbol
        CURRENT_TIMEFRAME = timeframe
        CURRENT_HTF = determine_htf(timeframe)

        print(f"\n===== Optimiere: {symbol} ({timeframe}) [Physics-Strategie] =====")
        HISTORICAL_DATA = load_data(symbol, timeframe, args.start_date, args.end_date)
        if HISTORICAL_DATA.empty: continue

        DB_FILE = os.path.join(PROJECT_ROOT, 'artifacts', 'db', 'optuna_studies_physics.db')
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        STORAGE_URL = f"sqlite:///{DB_FILE}?timeout=60"
        study_name = f"phys_st_{create_safe_filename(symbol, timeframe)}{CONFIG_SUFFIX}_{OPTIM_MODE}"

        # Alte Study löschen falls vorhanden, um mit frischen Parametern zu starten
        try:
            optuna.delete_study(study_name=study_name, storage=STORAGE_URL)
            print(f"  -> Alte Study '{study_name}' gelöscht, starte neu...")
        except KeyError:
            pass  # Study existiert noch nicht

        study = optuna.create_study(storage=STORAGE_URL, study_name=study_name, direction="maximize", load_if_exists=False)
        try:
            study.optimize(objective, n_trials=N_TRIALS, n_jobs=args.jobs, show_progress_bar=True)
        except Exception as e:
            print(f"FEHLER: {e}")
            continue

        valid_trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
        if not valid_trials: continue

        best_trial = max(valid_trials, key=lambda t: t.value)
        best_params = best_trial.params

        config_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
        os.makedirs(config_dir, exist_ok=True)
        config_output_path = os.path.join(config_dir, f'config_{create_safe_filename(symbol, timeframe)}{CONFIG_SUFFIX}.json')

        # Robuste Config-Erstellung für DBot Physics
        strategy_config = {
            "type": "physics",
            "enable_vwap_setup": True,
            "enable_impulse_pullback": True,
            "enable_volatility_expansion": True,

            "atr_period": best_params.get('atr_period', 14),
            "atr_multiplier_trend": round(best_params.get('atr_multiplier_trend', 1.5), 2),
            "momentum_period": best_params.get('momentum_period', 10),
            "momentum_sma_period": best_params.get('momentum_sma_period', 3),
            "volume_ma_period": best_params.get('volume_ma_period', 20),
            "volume_threshold": round(best_params.get('volume_threshold', 1.2), 2),
            "regime_atr_threshold": round(best_params.get('regime_atr_threshold', 0.02), 4),
            "ema_fast": best_params.get('ema_fast', 20),
            "ema_slow": best_params.get('ema_slow', 50),
            "range_lookback": best_params.get('range_lookback', 20),
            "range_overlap_threshold": round(best_params.get('range_overlap_threshold', 0.7), 2),

            "vwap_mean_reversion_threshold": round(best_params.get('vwap_mean_reversion_threshold', 2.0), 2),
            "momentum_threshold": round(best_params.get('momentum_threshold', 0.5), 2),
            "sl_atr_multiplier": round(best_params.get('sl_atr_multiplier', 1.2), 2),
            "tp_atr_multiplier": round(best_params.get('tp_atr_multiplier', 1.8), 2),
            "tp_atr_multiplier_expansion": round(best_params.get('tp_atr_multiplier_expansion', 2.5), 2),
            "exit_on_regime_change": True,
            "exit_on_momentum_reversal": True,
            "exit_on_vwap_cross": False,
            "exit_on_energy_loss": True,

            "supertrend_atr_period": best_params.get('supertrend_atr_period', 10),
            "supertrend_multiplier": round(best_params.get('supertrend_multiplier', 3.0), 2),
        }

        risk_config = {
            "margin_mode": "isolated",
            "risk_per_trade_pct": round(best_params.get('risk_per_trade_pct', 1.0), 2),
            "risk_reward_ratio": round(best_params.get('risk_reward_ratio', 2.0), 2),
            "leverage": best_params.get('leverage', 5),
            "trailing_stop_activation_rr": round(best_params.get('trailing_stop_activation_rr', 1.5), 2),
            "trailing_stop_callback_rate_pct": round(best_params.get('trailing_stop_callback_rate_pct', 0.5), 2),
            "atr_multiplier_sl": round(best_params.get('atr_multiplier_sl', 2.0), 2),
            "min_sl_pct": 0.5,
        }

        config_output = {
            "market": {"symbol": symbol, "timeframe": timeframe, "htf": CURRENT_HTF},
            "strategy": strategy_config,
            "risk": risk_config,
        }
        with open(config_output_path, 'w') as f: json.dump(config_output, f, indent=4)
        print(f"\n✔ Beste Konfiguration gespeichert.")

if __name__ == "__main__":
    main()
