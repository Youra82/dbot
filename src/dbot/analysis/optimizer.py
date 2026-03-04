# src/dbot/analysis/optimizer.py
# Vollautomatische LSTM-Pipeline: Daten laden → Modell trainieren (einmalig) → Optuna optimiert Thresholds
# Kein Re-Training pro Trial – Optuna optimiert nur Signal-Thresholds + Risiko-Parameter
import os
import sys
import json
import logging
import argparse
import numpy as np
import pandas as pd
import optuna
from datetime import datetime
from optuna.samplers import TPESampler

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.model.feature_engineering import (
    compute_features, create_labels, build_sequences,
    fit_scaler, apply_scaler, save_scaler, FEATURE_NAMES,
)
from dbot.model.trainer import train_model as _train_model, save_model
from dbot.model.predictor import LSTMPredictor
from dbot.analysis.backtester import run_backtest

logger = logging.getLogger(__name__)
optuna.logging.set_verbosity(optuna.logging.WARNING)


# ---------------------------------------------------------------------------
# Daten laden
# ---------------------------------------------------------------------------

def load_data(symbol, timeframe, limit=2000):
    """Lädt OHLCV-Daten von Exchange oder Cache."""
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cache_path = os.path.join(PROJECT_ROOT, 'data', f"{safe_name}.csv")

    # Cache nutzen wenn frisch (< 24h)
    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        try:
            last_ts = df.index[-1]
            if last_ts.tzinfo is None:
                last_ts = last_ts.tz_localize('UTC')
            age_h = (pd.Timestamp.now(tz='UTC') - last_ts).total_seconds() / 3600
            if age_h < 24:
                logger.info(f"Nutze Cache ({age_h:.1f}h alt): {cache_path} ({len(df)} Kerzen)")
                return df
        except Exception:
            return df  # Timestamp-Parsing-Fehler → Cache direkt nutzen

    # Von Exchange laden
    try:
        with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
            secrets = json.load(f)
        account = secrets.get('dbot', [{}])[0]
        from dbot.utils.exchange import Exchange
        exchange = Exchange(account)
    except Exception as e:
        if os.path.exists(cache_path):
            logger.warning(f"Exchange nicht erreichbar, nutze alten Cache: {e}")
            return pd.read_csv(cache_path, index_col=0, parse_dates=True)
        raise ValueError(f"Keine Daten und Exchange nicht erreichbar: {e}")

    logger.info(f"Lade {limit} Kerzen für {symbol} ({timeframe}) von Exchange...")
    df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=limit)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    df.to_csv(cache_path)
    logger.info(f"Daten gecacht: {cache_path} ({len(df)} Kerzen)")
    return df


# ---------------------------------------------------------------------------
# Internes Training
# ---------------------------------------------------------------------------

def _train_and_save(
    symbol, timeframe, df_train,
    seq_len, horizon, neutral_zone_pct, epochs,
    model_path, scaler_path,
    inner_val_split=0.15,
):
    """Trainiert LSTM auf df_train (einmalig) und speichert Modell + Scaler."""
    logger.info(f"{'='*55}")
    logger.info(f"  LSTM Training: {symbol} ({timeframe})")
    logger.info(f"  seq_len={seq_len} | horizon={horizon} | neutral_zone={neutral_zone_pct}% | epochs={epochs}")
    logger.info(f"{'='*55}")

    feature_df = compute_features(df_train)
    labels = create_labels(df_train, horizon_candles=horizon, neutral_zone_pct=neutral_zone_pct)
    aligned_labels = labels.reindex(feature_df.index)

    # Label-Verteilung anzeigen
    lbl_names = {0: 'LONG', 1: 'NEUTRAL', 2: 'SHORT'}
    for lbl, cnt in aligned_labels.value_counts().sort_index().items():
        logger.info(f"  {lbl_names.get(lbl, lbl)}: {cnt} ({cnt / len(aligned_labels) * 100:.1f}%)")

    # Inner Train/Val Split (für Early Stopping – nur innerhalb der Trainings-Daten)
    split = int(len(feature_df) * (1 - inner_val_split))
    scaler, scaled_train = fit_scaler(feature_df.iloc[:split])
    scaled_val_inner = apply_scaler(feature_df.iloc[split:], scaler)

    X_train, y_train = build_sequences(scaled_train, aligned_labels.iloc[:split], seq_len=seq_len)
    X_val, y_val = build_sequences(scaled_val_inner, aligned_labels.iloc[split:], seq_len=seq_len)

    logger.info(f"Sequenzen: Train={X_train.shape} | Val={X_val.shape}")
    if len(X_train) < 50:
        raise ValueError(f"Zu wenig Trainings-Sequenzen ({len(X_train)}). Mehr Daten oder kleineres seq_len verwenden.")

    model, history = _train_model(
        X_train, y_train, X_val, y_val,
        model_config={'hidden_size': 128, 'num_layers': 2, 'dropout': 0.2, 'fc_hidden': 64},
        epochs=epochs,
        patience=15,
    )

    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    save_model(model, model_path, metadata={
        'symbol': symbol,
        'timeframe': timeframe,
        'seq_len': seq_len,
        'horizon_candles': horizon,
        'neutral_zone_pct': neutral_zone_pct,
        'n_features': len(FEATURE_NAMES),
        'feature_names': FEATURE_NAMES,
        'best_val_acc': max(history['val_acc']),
        'trained_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
    })
    save_scaler(scaler, scaler_path)
    logger.info(f"Modell gespeichert: {model_path} | Beste Val Acc: {max(history['val_acc']):.4f}")


# ---------------------------------------------------------------------------
# Optuna Objective
# ---------------------------------------------------------------------------

def create_objective(df_val, predictor, base_config, start_capital, mode, max_drawdown, min_win_rate, min_pnl):
    """Erstellt die Optuna-Objective-Funktion."""
    def objective(trial):
        long_threshold = trial.suggest_float('long_threshold', 0.45, 0.80)
        short_threshold = trial.suggest_float('short_threshold', 0.45, 0.80)
        stop_loss_pct = trial.suggest_float('stop_loss_pct', 0.5, 5.0)
        leverage = trial.suggest_int('leverage', 1, 10)
        risk_per_entry_pct = trial.suggest_float('risk_per_entry_pct', 0.5, 3.0)
        rr_min = trial.suggest_float('rr_min', 1.0, 2.5)
        rr_spread = trial.suggest_float('rr_spread', 0.5, 2.5)  # rr_max = rr_min + rr_spread
        rr_max = rr_min + rr_spread

        config = {
            'market': base_config['market'],
            'model': {
                **base_config.get('model', {}),
                'long_threshold': long_threshold,
                'short_threshold': short_threshold,
                'rr_min': rr_min,
                'rr_max': rr_max,
            },
            'risk': {
                'stop_loss_pct': stop_loss_pct,
                'leverage': leverage,
                'risk_per_entry_pct': risk_per_entry_pct,
                'margin_mode': base_config.get('risk', {}).get('margin_mode', 'isolated'),
            },
            'behavior': base_config.get('behavior', {'use_longs': True, 'use_shorts': True}),
        }

        metrics = run_backtest(df_val, predictor, config, start_capital=start_capital, verbose=False)
        if 'error' in metrics:
            return -999.0

        total_trades = metrics.get('total_trades', 0)
        pnl_pct = metrics.get('pnl_pct', -100)
        max_dd = metrics.get('max_drawdown_pct', 100)
        win_rate = metrics.get('win_rate', 0)
        calmar = metrics.get('calmar_ratio', 0)

        if total_trades < 10:
            return -50.0

        if mode == 'strict':
            if max_dd > max_drawdown:
                return -50.0 - max_dd
            if win_rate < min_win_rate:
                return -50.0
            if pnl_pct < min_pnl:
                return -50.0
        else:  # best_profit
            if max_dd > max_drawdown:
                return -50.0 - max_dd

        return calmar

    return objective


# ---------------------------------------------------------------------------
# Config speichern
# ---------------------------------------------------------------------------

def save_best_config(symbol, timeframe, best_params, base_config, metrics):
    """Speichert die beste Config als JSON."""
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    os.makedirs(configs_dir, exist_ok=True)
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    config_path = os.path.join(configs_dir, f"config_{safe_name}_lstm.json")

    rr_min = best_params['rr_min']
    rr_max = rr_min + best_params['rr_spread']

    config = {
        'market': {'symbol': symbol, 'timeframe': timeframe},
        'model': {
            **base_config.get('model', {}),
            'long_threshold': round(best_params['long_threshold'], 4),
            'short_threshold': round(best_params['short_threshold'], 4),
            'rr_min': round(rr_min, 2),
            'rr_max': round(rr_max, 2),
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
    logger.info(f"Config gespeichert: {config_path}")
    return config_path


# ---------------------------------------------------------------------------
# Haupt-Funktion
# ---------------------------------------------------------------------------

def run_optimizer(
    symbol: str,
    timeframe: str,
    n_trials: int = 100,
    start_capital: float = 1000.0,
    val_split: float = 0.2,
    limit: int = 2000,
    epochs: int = 50,
    horizon: int = 5,
    neutral_zone_pct: float = 0.3,
    seq_len: int = 60,
    force_retrain: bool = False,
    mode: str = 'strict',
    max_drawdown: float = 30.0,
    min_win_rate: float = 0.0,
    min_pnl: float = 0.0,
):
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt")
    scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}_scaler.pkl")

    # 1. Daten laden
    df = load_data(symbol, timeframe, limit=limit)
    if df is None or len(df) < 300:
        raise ValueError(f"Zu wenig Daten: {len(df) if df is not None else 0}")
    logger.info(f"Daten: {len(df)} Kerzen | {df.index[0]} → {df.index[-1]}")

    # 2. Train/Optuna Split (chronologisch – kein Lookahead!)
    split_idx = int(len(df) * (1 - val_split))
    df_for_training = df.iloc[:split_idx]
    df_for_optuna = df.iloc[split_idx:]
    logger.info(f"Split: Training={len(df_for_training)} Kerzen | Optuna-Val={len(df_for_optuna)} Kerzen")

    # 3. LSTM trainieren (einmalig) – oder vorhandenes Modell nutzen
    if force_retrain or not os.path.exists(model_path):
        _train_and_save(
            symbol, timeframe, df_for_training,
            seq_len, horizon, neutral_zone_pct, epochs,
            model_path, scaler_path,
        )
    else:
        logger.info(f"Modell bereits vorhanden: {model_path} (nutze --force-retrain um neu zu trainieren)")

    # 4. Predictor laden
    predictor = LSTMPredictor.from_files(model_path, scaler_path, seq_len)
    logger.info(f"LSTM-Predictor geladen.")

    # 5. Basis-Config (aus bestehender Config oder Defaults)
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    config_path = os.path.join(configs_dir, f"config_{safe_name}_lstm.json")
    base_config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            base_config = json.load(f)
    base_config.setdefault('market', {'symbol': symbol, 'timeframe': timeframe})
    base_config.setdefault('model', {
        'sequence_length': seq_len,
        'horizon_candles': horizon,
        'neutral_zone_pct': neutral_zone_pct,
        'rr_min': 1.5,
        'rr_max': 3.0,
    })

    # 6. Optuna Optimierung (kein Re-Training pro Trial)
    study = optuna.create_study(direction='maximize', sampler=TPESampler(seed=42))
    objective = create_objective(
        df_for_optuna, predictor, base_config, start_capital,
        mode=mode, max_drawdown=max_drawdown, min_win_rate=min_win_rate, min_pnl=min_pnl,
    )
    logger.info(f"Starte Optuna: {n_trials} Trials für {symbol} ({timeframe}) [Modus: {mode}]...")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    best_trial = study.best_trial
    logger.info(f"Beste Trial: Calmar={best_trial.value:.3f} | Params: {best_trial.params}")

    # 7. Finaler Backtest mit besten Parametern
    best_rr_min = best_trial.params['rr_min']
    best_rr_max = best_rr_min + best_trial.params['rr_spread']
    best_config_tmp = {
        'market': {'symbol': symbol, 'timeframe': timeframe},
        'model': {
            **base_config.get('model', {}),
            'long_threshold': best_trial.params['long_threshold'],
            'short_threshold': best_trial.params['short_threshold'],
            'rr_min': best_rr_min,
            'rr_max': best_rr_max,
        },
        'risk': {
            'stop_loss_pct': best_trial.params['stop_loss_pct'],
            'leverage': best_trial.params['leverage'],
            'risk_per_entry_pct': best_trial.params['risk_per_entry_pct'],
            'margin_mode': base_config.get('risk', {}).get('margin_mode', 'isolated'),
        },
        'behavior': base_config.get('behavior', {'use_longs': True, 'use_shorts': True}),
    }
    final_metrics = run_backtest(df_for_optuna, predictor, best_config_tmp, start_capital=start_capital, verbose=True)

    # 8. Config speichern
    out_path = save_best_config(symbol, timeframe, best_trial.params, base_config, final_metrics)
    return best_trial.params, final_metrics, out_path


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(description="dbot Vollautomatische LSTM-Pipeline: Training + Optimierung")
    parser.add_argument('--symbols', required=True, nargs='+', help="Handelspaare, z.B. BTC/USDT:USDT ETH/USDT:USDT")
    parser.add_argument('--timeframes', required=True, nargs='+', help="Zeitfenster, z.B. 4h 1h")
    parser.add_argument('--start-capital', type=float, default=1000.0, help="Startkapital in USDT")
    parser.add_argument('--trials', type=int, default=100, help="Anzahl Optuna-Trials")
    parser.add_argument('--epochs', type=int, default=50, help="LSTM Training-Epochen")
    parser.add_argument('--horizon', type=int, default=5, help="Vorhersage-Horizont (Kerzen)")
    parser.add_argument('--neutral-zone', type=float, default=0.3, help="Neutrale Zone in %%")
    parser.add_argument('--seq-len', type=int, default=60, help="LSTM Eingabe-Fenster (Kerzen)")
    parser.add_argument('--val-split', type=float, default=0.2, help="Anteil für Optuna-Validierung (0-1)")
    parser.add_argument('--limit', type=int, default=2000, help="Anzahl Kerzen von Exchange")
    parser.add_argument('--force-retrain', action='store_true', default=False, help="Modell neu trainieren auch wenn vorhanden")
    parser.add_argument('--mode', choices=['strict', 'best_profit'], default='strict', help="Optimierungs-Modus")
    parser.add_argument('--max-drawdown', type=float, default=30.0, help="Max erlaubter Drawdown %%")
    parser.add_argument('--min-win-rate', type=float, default=0.0, help="Min Win-Rate %%")
    parser.add_argument('--min-pnl', type=float, default=0.0, help="Min PnL %%")
    args = parser.parse_args()

    for symbol in args.symbols:
        for timeframe in args.timeframes:
            print(f"\n{'='*55}")
            print(f"  Pipeline: {symbol} ({timeframe})")
            print(f"{'='*55}")
            try:
                best_params, metrics, config_path = run_optimizer(
                    symbol=symbol,
                    timeframe=timeframe,
                    n_trials=args.trials,
                    start_capital=args.start_capital,
                    val_split=args.val_split,
                    limit=args.limit,
                    epochs=args.epochs,
                    horizon=args.horizon,
                    neutral_zone_pct=args.neutral_zone,
                    seq_len=args.seq_len,
                    force_retrain=args.force_retrain,
                    mode=args.mode,
                    max_drawdown=args.max_drawdown,
                    min_win_rate=args.min_win_rate,
                    min_pnl=args.min_pnl,
                )
                print(f"\n  Optimierung abgeschlossen!")
                print(f"  Config: {config_path}")
                print(f"  Calmar: {metrics.get('calmar_ratio', 0):.3f} | PnL: {metrics.get('pnl_pct', 0):.1f}% | Trades: {metrics.get('total_trades', 0)}")
            except Exception as e:
                print(f"\n  FEHLER für {symbol} ({timeframe}): {e}")
                logger.exception(e)


if __name__ == '__main__':
    main()
