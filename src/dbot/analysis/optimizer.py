# src/dbot/analysis/optimizer.py
# Optuna-Optimizer: Optimiert Signal-Thresholds + Risk-Params auf vortrainiertem LSTM
# Kein Re-Training pro Trial – deutlich schneller als LSTM-Training pro Trial
import os
import sys
import json
import logging
import argparse
import numpy as np
import pandas as pd
import optuna
from optuna.samplers import TPESampler

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.model.feature_engineering import compute_features, apply_scaler, load_scaler
from dbot.model.trainer import load_model
from dbot.model.predictor import LSTMPredictor
from dbot.analysis.backtester import run_backtest

logger = logging.getLogger(__name__)

optuna.logging.set_verbosity(optuna.logging.WARNING)


def load_data(symbol, timeframe, exchange=None, limit=2000):
    """Lädt OHLCV-Daten von Exchange oder aus Cache."""
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cache_path = os.path.join(PROJECT_ROOT, 'data', f"{safe_name}.csv")

    if os.path.exists(cache_path):
        logger.info(f"Lade gecachte Daten: {cache_path}")
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        return df

    if exchange is None:
        raise ValueError("Keine gecachten Daten gefunden und kein Exchange angegeben.")

    logger.info(f"Lade Daten von Exchange für {symbol} ({timeframe})...")
    df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=limit)

    # Cache speichern
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    df.to_csv(cache_path)
    logger.info(f"Daten gecacht: {cache_path} ({len(df)} Kerzen)")
    return df


def create_objective(df_train, df_val, predictor, base_config, start_capital):
    """Erstellt die Optuna-Objective-Funktion."""
    def objective(trial):
        # Signal-Thresholds (wichtigste Parameter)
        long_threshold = trial.suggest_float('long_threshold', 0.45, 0.80)
        short_threshold = trial.suggest_float('short_threshold', 0.45, 0.80)

        # Risk-Parameter
        stop_loss_pct = trial.suggest_float('stop_loss_pct', 0.5, 5.0)
        leverage = trial.suggest_int('leverage', 1, 10)
        risk_per_entry_pct = trial.suggest_float('risk_per_entry_pct', 0.5, 3.0)

        # Config für diesen Trial
        config = {
            'market': base_config['market'],
            'model': {
                **base_config.get('model', {}),
                'long_threshold': long_threshold,
                'short_threshold': short_threshold,
            },
            'risk': {
                'stop_loss_pct': stop_loss_pct,
                'leverage': leverage,
                'risk_per_entry_pct': risk_per_entry_pct,
                'margin_mode': base_config.get('risk', {}).get('margin_mode', 'isolated'),
            },
            'behavior': base_config.get('behavior', {'use_longs': True, 'use_shorts': True}),
        }

        # Backtest auf Validierungsdaten
        metrics = run_backtest(df_val, predictor, config, start_capital=start_capital, verbose=False)

        if 'error' in metrics:
            return -999.0

        total_trades = metrics.get('total_trades', 0)
        pnl_pct = metrics.get('pnl_pct', -100)
        max_drawdown_pct = metrics.get('max_drawdown_pct', 100)
        calmar = metrics.get('calmar_ratio', 0)

        # Constraints: Zu wenig Trades oder zu hoher Drawdown → stark bestrafen
        if total_trades < 10:
            return -50.0
        if max_drawdown_pct > 40:
            return -50.0 - max_drawdown_pct

        # Zielmetrik: Calmar Ratio (PnL / MaxDrawdown)
        return calmar

    return objective


def save_best_config(symbol, timeframe, best_params, base_config, metrics):
    """Speichert die beste Config als JSON."""
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    os.makedirs(configs_dir, exist_ok=True)
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    config_path = os.path.join(configs_dir, f"config_{safe_name}_lstm.json")

    config = {
        'market': {'symbol': symbol, 'timeframe': timeframe},
        'model': {
            **base_config.get('model', {}),
            'long_threshold': round(best_params['long_threshold'], 4),
            'short_threshold': round(best_params['short_threshold'], 4),
        },
        'risk': {
            'stop_loss_pct': round(best_params['stop_loss_pct'], 2),
            'leverage': best_params['leverage'],
            'risk_per_entry_pct': round(best_params['risk_per_entry_pct'], 2),
            'margin_mode': base_config.get('risk', {}).get('margin_mode', 'isolated'),
        },
        'behavior': base_config.get('behavior', {'use_longs': True, 'use_shorts': True}),
        'initial_capital_live': base_config.get('initial_capital_live', 1000),
        '_backtest_metrics': {
            'trades': metrics.get('total_trades', 0),
            'win_rate': round(metrics.get('win_rate', 0), 1),
            'pnl_pct': round(metrics.get('pnl_pct', 0), 2),
            'max_drawdown_pct': round(metrics.get('max_drawdown_pct', 0), 2),
            'calmar_ratio': round(metrics.get('calmar_ratio', 0), 3),
        },
    }

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)
    logger.info(f"Beste Config gespeichert: {config_path}")
    return config_path


def run_optimizer(
    symbol: str,
    timeframe: str,
    n_trials: int = 100,
    start_capital: float = 1000.0,
    val_split: float = 0.2,
    exchange=None,
):
    """Haupt-Optimierungs-Funktion."""
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"

    # Modell + Scaler laden
    model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt")
    scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}_scaler.pkl")

    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"Modell nicht gefunden: {model_path}\n"
            f"Bitte zuerst ausführen: python train_model.py --symbol {symbol} --timeframe {timeframe}"
        )

    # Basis-Config (aus bestehender Config oder Default)
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    config_path = os.path.join(configs_dir, f"config_{safe_name}_lstm.json")
    base_config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            base_config = json.load(f)

    seq_len = base_config.get('model', {}).get('sequence_length', 60)
    predictor = LSTMPredictor.from_files(model_path, scaler_path, seq_len)
    logger.info(f"LSTM-Predictor geladen: {model_path}")

    # Daten laden
    df = load_data(symbol, timeframe, exchange=exchange)
    if df is None or len(df) < 300:
        raise ValueError(f"Zu wenig Daten für Optimierung: {len(df) if df is not None else 0}")

    # Train/Val Split (chronologisch – kein Lookahead!)
    split_idx = int(len(df) * (1 - val_split))
    df_train = df.iloc[:split_idx]
    df_val = df.iloc[split_idx:]
    logger.info(f"Daten: {len(df)} Kerzen | Train: {len(df_train)} | Val: {len(df_val)}")

    # Optuna Studie
    study = optuna.create_study(direction='maximize', sampler=TPESampler(seed=42))
    objective = create_objective(df_train, df_val, predictor, base_config, start_capital)

    logger.info(f"Starte Optuna-Optimierung: {n_trials} Trials für {symbol} ({timeframe})...")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    best_trial = study.best_trial
    logger.info(f"\nBeste Trial: Calmar={best_trial.value:.3f}")
    logger.info(f"Beste Parameter: {best_trial.params}")

    # Finalen Backtest mit besten Parametern
    best_config = {
        'market': {'symbol': symbol, 'timeframe': timeframe},
        'model': {**base_config.get('model', {}), **{
            'long_threshold': best_trial.params['long_threshold'],
            'short_threshold': best_trial.params['short_threshold'],
        }},
        'risk': {
            'stop_loss_pct': best_trial.params['stop_loss_pct'],
            'leverage': best_trial.params['leverage'],
            'risk_per_entry_pct': best_trial.params['risk_per_entry_pct'],
            'margin_mode': base_config.get('risk', {}).get('margin_mode', 'isolated'),
        },
        'behavior': base_config.get('behavior', {'use_longs': True, 'use_shorts': True}),
    }

    final_metrics = run_backtest(df_val, predictor, best_config, start_capital=start_capital, verbose=True)

    # Config speichern
    config_path = save_best_config(symbol, timeframe, best_trial.params, base_config, final_metrics)

    return best_trial.params, final_metrics, config_path


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(description="dbot LSTM Optimizer")
    parser.add_argument('--symbol', required=True, type=str)
    parser.add_argument('--timeframe', required=True, type=str)
    parser.add_argument('--trials', type=int, default=100, help="Anzahl Optuna-Trials")
    parser.add_argument('--start-capital', type=float, default=1000.0)
    parser.add_argument('--val-split', type=float, default=0.2, help="Anteil Validierungsdaten (0-1)")
    args = parser.parse_args()

    # Exchange nur laden wenn keine gecachten Daten
    exchange = None
    safe_name = f"{args.symbol.replace('/', '').replace(':', '')}_{args.timeframe}"
    cache_path = os.path.join(PROJECT_ROOT, 'data', f"{safe_name}.csv")

    if not os.path.exists(cache_path):
        try:
            with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
                secrets = json.load(f)
            account = secrets.get('dbot', [{}])[0]
            from dbot.utils.exchange import Exchange
            exchange = Exchange(account)
        except Exception as e:
            logger.warning(f"Konnte Exchange nicht laden: {e}. Wird gecachte Daten verwenden.")

    try:
        best_params, metrics, config_path = run_optimizer(
            symbol=args.symbol,
            timeframe=args.timeframe,
            n_trials=args.trials,
            start_capital=args.start_capital,
            val_split=args.val_split,
            exchange=exchange,
        )
        print(f"\nOptimierung abgeschlossen!")
        print(f"Config gespeichert: {config_path}")
        print(f"Calmar: {metrics.get('calmar_ratio', 0):.3f} | PnL: {metrics.get('pnl_pct', 0):.1f}% | Trades: {metrics.get('total_trades', 0)}")
    except FileNotFoundError as e:
        print(f"\nFEHLER: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
