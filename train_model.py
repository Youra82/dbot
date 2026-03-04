#!/usr/bin/env python3
# train_model.py
# Trainiert das LSTM-Modell auf historischen Daten für ein Symbol/Timeframe-Paar
# Ausführung: python train_model.py --symbol BTC/USDT:USDT --timeframe 4h
import os
import sys
import json
import logging
import argparse
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.model.feature_engineering import (
    compute_features, create_labels, build_sequences,
    fit_scaler, apply_scaler, save_scaler, FEATURE_NAMES
)
from dbot.model.trainer import train_model, save_model
from dbot.analysis.backtester import run_backtest
from dbot.model.predictor import LSTMPredictor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(PROJECT_ROOT, 'logs', 'train_model.log')),
    ]
)
logger = logging.getLogger(__name__)


def load_data_from_exchange(symbol, timeframe, limit=3000):
    """Lädt OHLCV-Daten von Bitget via CCXT."""
    with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
        secrets = json.load(f)
    account = secrets.get('dbot', [{}])[0]

    from dbot.utils.exchange import Exchange
    exchange = Exchange(account)

    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cache_path = os.path.join(PROJECT_ROOT, 'data', f"{safe_name}.csv")

    if os.path.exists(cache_path):
        logger.info(f"Lade gecachte Daten: {cache_path}")
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        # Refresh nur wenn Cache älter als 1 Tag
        cache_age_hours = (pd.Timestamp.now(tz='UTC') - df.index[-1]).total_seconds() / 3600
        if cache_age_hours < 24:
            logger.info(f"Cache frisch ({cache_age_hours:.1f}h alt). Nutze Cache.")
            return df

    logger.info(f"Lade {limit} Kerzen für {symbol} ({timeframe}) von Bitget...")
    df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=limit)

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    df.to_csv(cache_path)
    logger.info(f"Daten gecacht: {cache_path} ({len(df)} Kerzen)")
    return df


def main():
    os.makedirs(os.path.join(PROJECT_ROOT, 'logs'), exist_ok=True)

    parser = argparse.ArgumentParser(description="dbot LSTM Training")
    parser.add_argument('--symbol', required=True, type=str, help="z.B. BTC/USDT:USDT")
    parser.add_argument('--timeframe', required=True, type=str, help="z.B. 4h")
    parser.add_argument('--seq-len', type=int, default=60, help="LSTM Eingabe-Fenster (Kerzen)")
    parser.add_argument('--horizon', type=int, default=5, help="Vorhersage-Horizont (Kerzen)")
    parser.add_argument('--neutral-zone', type=float, default=0.3, help="Neutrale Zone in %")
    parser.add_argument('--epochs', type=int, default=50, help="Training-Epochen")
    parser.add_argument('--batch-size', type=int, default=64, help="Batch-Größe")
    parser.add_argument('--lr', type=float, default=1e-3, help="Lernrate")
    parser.add_argument('--val-split', type=float, default=0.15, help="Validierungs-Anteil")
    parser.add_argument('--data-file', type=str, help="Lokale CSV-Datei statt Exchange")
    parser.add_argument('--limit', type=int, default=3000, help="Anzahl Kerzen von Exchange")
    args = parser.parse_args()

    symbol = args.symbol
    timeframe = args.timeframe
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"

    logger.info(f"{'='*60}")
    logger.info(f"  dbot LSTM Training: {symbol} ({timeframe})")
    logger.info(f"  seq_len={args.seq_len} | horizon={args.horizon} | neutral_zone={args.neutral_zone}%")
    logger.info(f"  epochs={args.epochs} | batch_size={args.batch_size} | lr={args.lr}")
    logger.info(f"{'='*60}")

    # 1. Daten laden
    if args.data_file and os.path.exists(args.data_file):
        logger.info(f"Lade Daten aus Datei: {args.data_file}")
        df = pd.read_csv(args.data_file, index_col=0, parse_dates=True)
    else:
        df = load_data_from_exchange(symbol, timeframe, limit=args.limit)

    if df is None or len(df) < 300:
        logger.error(f"Zu wenig Daten: {len(df) if df is not None else 0}")
        sys.exit(1)

    logger.info(f"Daten geladen: {len(df)} Kerzen | {df.index[0]} → {df.index[-1]}")

    # 2. Features berechnen
    logger.info("Berechne Features...")
    feature_df = compute_features(df)
    logger.info(f"Features: {feature_df.shape} | NaN-Zeilen entfernt: {len(df) - len(feature_df)}")

    # 3. Labels erstellen
    logger.info(f"Erstelle Labels (horizon={args.horizon}, neutral_zone={args.neutral_zone}%)...")
    labels = create_labels(df, horizon_candles=args.horizon, neutral_zone_pct=args.neutral_zone)

    # Label-Verteilung anzeigen
    aligned_labels = labels.reindex(feature_df.index)
    label_counts = aligned_labels.value_counts().sort_index()
    label_names = {0: 'LONG', 1: 'NEUTRAL', 2: 'SHORT'}
    for lbl, count in label_counts.items():
        pct = count / len(aligned_labels) * 100
        logger.info(f"  {label_names.get(lbl, lbl)}: {count} ({pct:.1f}%)")

    # 4. Train/Val Split (chronologisch)
    val_split_idx = int(len(feature_df) * (1 - args.val_split))
    test_split_idx = int(len(feature_df) * 0.9)  # Letzte 10% als Test (blind)

    feature_train = feature_df.iloc[:val_split_idx]
    feature_val = feature_df.iloc[val_split_idx:test_split_idx]
    feature_test = feature_df.iloc[test_split_idx:]

    labels_train = aligned_labels.iloc[:val_split_idx]
    labels_val = aligned_labels.iloc[val_split_idx:test_split_idx]
    labels_test = aligned_labels.iloc[test_split_idx:]

    logger.info(f"Split: Train={len(feature_train)} | Val={len(feature_val)} | Test={len(feature_test)}")

    # 5. Scaler fitten (nur auf Trainingsdaten!)
    logger.info("Fitte RobustScaler auf Trainingsdaten...")
    scaler, scaled_train = fit_scaler(feature_train)
    scaled_val = apply_scaler(feature_val, scaler)

    # 6. Sequenzen erstellen
    logger.info(f"Erstelle Sliding-Window-Sequenzen (seq_len={args.seq_len})...")
    X_train, y_train = build_sequences(scaled_train, labels_train, seq_len=args.seq_len)
    X_val, y_val = build_sequences(scaled_val, labels_val, seq_len=args.seq_len)

    logger.info(f"Train: X={X_train.shape}, y={y_train.shape}")
    logger.info(f"Val:   X={X_val.shape}, y={y_val.shape}")

    if len(X_train) < 50 or len(X_val) < 10:
        logger.error("Zu wenig Sequenzen für Training. Mehr Daten oder kleineres seq_len verwenden.")
        sys.exit(1)

    # 7. Modell trainieren
    logger.info("Starte LSTM-Training...")
    model, history = train_model(
        X_train, y_train, X_val, y_val,
        model_config={'hidden_size': 128, 'num_layers': 2, 'dropout': 0.2, 'fc_hidden': 64},
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        patience=15,
    )

    # 8. Modell + Scaler speichern
    models_dir = os.path.join(PROJECT_ROOT, 'artifacts', 'models')
    os.makedirs(models_dir, exist_ok=True)

    model_path = os.path.join(models_dir, f"{safe_name}.pt")
    scaler_path = os.path.join(models_dir, f"{safe_name}_scaler.pkl")

    metadata = {
        'symbol': symbol,
        'timeframe': timeframe,
        'seq_len': args.seq_len,
        'horizon_candles': args.horizon,
        'neutral_zone_pct': args.neutral_zone,
        'n_features': len(FEATURE_NAMES),
        'feature_names': FEATURE_NAMES,
        'train_size': len(X_train),
        'val_size': len(X_val),
        'best_val_acc': max(history['val_acc']),
    }

    save_model(model, model_path, metadata=metadata)
    save_scaler(scaler, scaler_path)

    logger.info(f"Modell gespeichert: {model_path}")
    logger.info(f"Scaler gespeichert: {scaler_path}")

    # 9. Zusammenfassung
    best_val_acc = max(history['val_acc'])
    logger.info(f"\n{'='*60}")
    logger.info(f"  Training abgeschlossen!")
    logger.info(f"  Beste Val Accuracy: {best_val_acc:.4f} ({best_val_acc*100:.1f}%)")
    logger.info(f"  Modell:  {model_path}")
    logger.info(f"  Scaler:  {scaler_path}")
    logger.info(f"\n  Nächster Schritt:")
    logger.info(f"  python -m dbot.analysis.optimizer --symbol {symbol} --timeframe {timeframe}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
