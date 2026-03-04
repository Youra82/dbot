# src/dbot/model/feature_engineering.py
# Feature-Erstellung aus OHLCV-Daten für das LSTM
import numpy as np
import pandas as pd
import ta
import logging
import pickle
import os
from sklearn.preprocessing import RobustScaler

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    'close_return',    # Log-Return der Close-Preise
    'volume_ratio',    # Volume / 20-Kerzen-Durchschnitt
    'rsi_14',          # RSI (14)
    'macd',            # MACD-Linie
    'macd_signal',     # MACD-Signal
    'bb_width',        # Bollinger Band Breite (% vom Mittelwert)
    'atr_pct',         # ATR als % vom Close
    'adx',             # ADX (Trend-Stärke)
    'ema20_dist',      # Abstand Close zu EMA20 (%)
    'ema50_dist',      # Abstand Close zu EMA50 (%)
    'high_low_range',  # (High-Low)/Close
    'close_position',  # (Close-Low)/(High-Low) – Kerzenposition
]


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Berechnet alle Features aus einem OHLCV-DataFrame.

    Args:
        df: DataFrame mit Spalten [open, high, low, close, volume]

    Returns:
        DataFrame mit Feature-Spalten (NaN-Zeilen werden getroppt)
    """
    df = df.copy()

    # Log-Return
    df['close_return'] = np.log(df['close'] / df['close'].shift(1))

    # Volume-Ratio
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()

    # RSI
    df['rsi_14'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()

    # MACD
    macd_ind = ta.trend.MACD(close=df['close'])
    df['macd'] = macd_ind.macd()
    df['macd_signal'] = macd_ind.macd_signal()

    # Bollinger Band Breite
    bb = ta.volatility.BollingerBands(close=df['close'], window=20)
    bb_mid = bb.bollinger_mavg()
    bb_width_abs = bb.bollinger_hband() - bb.bollinger_lband()
    df['bb_width'] = bb_width_abs / bb_mid.replace(0, np.nan)

    # ATR als % vom Close
    atr = ta.volatility.AverageTrueRange(
        high=df['high'], low=df['low'], close=df['close'], window=14
    ).average_true_range()
    df['atr_pct'] = atr / df['close'].replace(0, np.nan)

    # ADX
    adx_ind = ta.trend.ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14)
    df['adx'] = adx_ind.adx()

    # EMA20 / EMA50 Abstand
    ema20 = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
    ema50 = ta.trend.EMAIndicator(close=df['close'], window=50).ema_indicator()
    df['ema20_dist'] = (df['close'] - ema20) / ema20.replace(0, np.nan)
    df['ema50_dist'] = (df['close'] - ema50) / ema50.replace(0, np.nan)

    # High-Low Range
    df['high_low_range'] = (df['high'] - df['low']) / df['close'].replace(0, np.nan)

    # Close-Position innerhalb der Kerze
    hl_range = df['high'] - df['low']
    df['close_position'] = (df['close'] - df['low']) / hl_range.replace(0, np.nan)

    # NaN-Zeilen entfernen
    df = df[FEATURE_NAMES].dropna()
    return df


def create_labels(raw_df: pd.DataFrame, horizon_candles: int = 5,
                  neutral_zone_pct: float = 0.3) -> pd.Series:
    """
    Erstellt Klassifikations-Labels basierend auf zukünftiger Preisbewegung.

    Labels:
        0 = LONG   (return > +neutral_zone_pct%)
        1 = NEUTRAL (|return| ≤ neutral_zone_pct%)
        2 = SHORT  (return < -neutral_zone_pct%)

    Args:
        raw_df: Original OHLCV-DataFrame (nicht feature-transformiert)
        horizon_candles: Wie viele Kerzen in die Zukunft schauen
        neutral_zone_pct: Schwelle für Neutral-Zone (in %)

    Returns:
        pd.Series mit Integer-Labels (0, 1, 2)
    """
    close = raw_df['close']
    future_return = (close.shift(-horizon_candles) - close) / close * 100.0

    labels = pd.Series(1, index=close.index, dtype=int)  # Default: NEUTRAL
    labels[future_return > neutral_zone_pct] = 0           # LONG
    labels[future_return < -neutral_zone_pct] = 2          # SHORT

    return labels


def build_sequences(feature_df: pd.DataFrame, labels: pd.Series,
                    seq_len: int = 60) -> tuple:
    """
    Erstellt Sliding-Window-Sequenzen für das LSTM.

    Args:
        feature_df: DataFrame mit normalisierten Features (nach fit_scaler)
        labels: Series mit Labels (gleicher Index wie feature_df)
        seq_len: Länge des Eingabe-Fensters (Anzahl Kerzen)

    Returns:
        (X, y): numpy arrays
            X: (n_samples, seq_len, n_features)
            y: (n_samples,) mit Labels 0/1/2
    """
    feat_arr = feature_df.values
    label_arr = labels.reindex(feature_df.index).values

    X, y = [], []
    for i in range(seq_len, len(feat_arr)):
        # Prüfe ob Label gültig (kein NaN, also Horizon-Ende liegt im Datensatz)
        if np.isnan(label_arr[i]):
            continue
        X.append(feat_arr[i - seq_len:i])
        y.append(int(label_arr[i]))

    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int64)


def fit_scaler(feature_df: pd.DataFrame) -> tuple:
    """
    Fittet einen RobustScaler auf den Feature-DataFrame.

    Returns:
        (scaler, scaled_df)
    """
    scaler = RobustScaler()
    scaled_values = scaler.fit_transform(feature_df.values)
    scaled_df = pd.DataFrame(scaled_values, index=feature_df.index, columns=feature_df.columns)
    return scaler, scaled_df


def apply_scaler(feature_df: pd.DataFrame, scaler: RobustScaler) -> pd.DataFrame:
    """Wendet einen bereits gefitteten Scaler an."""
    scaled_values = scaler.transform(feature_df.values)
    return pd.DataFrame(scaled_values, index=feature_df.index, columns=feature_df.columns)


def save_scaler(scaler: RobustScaler, path: str):
    """Speichert den Scaler als Pickle-Datei."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        pickle.dump(scaler, f)
    logger.info(f"Scaler gespeichert: {path}")


def load_scaler(path: str) -> RobustScaler:
    """Lädt einen Scaler aus einer Pickle-Datei."""
    with open(path, 'rb') as f:
        scaler = pickle.load(f)
    logger.info(f"Scaler geladen: {path}")
    return scaler
