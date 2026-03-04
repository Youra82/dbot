# src/dbot/model/predictor.py
# Lädt Modell + Scaler und generiert Live-Predictions
import os
import numpy as np
import torch
import logging
import pandas as pd

from dbot.model.trainer import load_model, DEVICE
from dbot.model.feature_engineering import (
    compute_features, apply_scaler, load_scaler, FEATURE_NAMES
)

logger = logging.getLogger(__name__)


class LSTMPredictor:
    """
    Kapselt Modell + Scaler für Live-Inference.

    Nutzung:
        predictor = LSTMPredictor.from_files(model_path, scaler_path)
        probs = predictor.predict(df_ohlcv)  # [long_prob, neutral_prob, short_prob]
    """

    def __init__(self, model, scaler, seq_len: int = 60):
        self.model = model
        self.scaler = scaler
        self.seq_len = seq_len
        self.model.eval()

    @classmethod
    def from_files(cls, model_path: str, scaler_path: str, seq_len: int = 60) -> 'LSTMPredictor':
        """Lädt Modell und Scaler von Festplatte."""
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Modell nicht gefunden: {model_path}")
        if not os.path.exists(scaler_path):
            raise FileNotFoundError(f"Scaler nicht gefunden: {scaler_path}")

        model = load_model(model_path)
        scaler = load_scaler(scaler_path)
        return cls(model, scaler, seq_len)

    def predict(self, df_ohlcv: pd.DataFrame) -> np.ndarray:
        """
        Generiert Prediction für die letzte Sequenz im DataFrame.

        Args:
            df_ohlcv: OHLCV-DataFrame mit mindestens seq_len + 50 Zeilen (für Indicators)

        Returns:
            numpy array [long_prob, neutral_prob, short_prob]
        """
        min_rows = self.seq_len + 60  # Puffer für Indicator-Berechnung
        if len(df_ohlcv) < min_rows:
            logger.warning(f"Zu wenig Daten für Prediction: {len(df_ohlcv)} < {min_rows}")
            return np.array([1/3, 1/3, 1/3])  # Uninformative Prediction

        # Features berechnen
        feature_df = compute_features(df_ohlcv)
        if len(feature_df) < self.seq_len:
            logger.warning(f"Zu wenig Feature-Zeilen nach Dropna: {len(feature_df)}")
            return np.array([1/3, 1/3, 1/3])

        # Scaler anwenden
        scaled_df = apply_scaler(feature_df, self.scaler)

        # Letztes Fenster extrahieren
        window = scaled_df.iloc[-self.seq_len:][FEATURE_NAMES].values  # (seq_len, n_features)
        X = torch.tensor(window[np.newaxis, :, :], dtype=torch.float32).to(DEVICE)  # (1, seq_len, features)

        # Prediction
        with torch.no_grad():
            probs = self.model.predict_proba(X).cpu().numpy()[0]  # (3,)

        logger.debug(f"LSTM Prediction: long={probs[0]:.3f}, neutral={probs[1]:.3f}, short={probs[2]:.3f}")
        return probs  # [long_prob, neutral_prob, short_prob]

    def predict_batch(self, feature_df_scaled: pd.DataFrame) -> np.ndarray:
        """
        Generiert Predictions für alle möglichen Fenster im DataFrame.
        Nützlich für Backtesting.

        Returns:
            numpy array (n_samples, 3)
        """
        feat_arr = feature_df_scaled[FEATURE_NAMES].values
        n = len(feat_arr)
        all_probs = []

        batch_size = 512
        X_all = []
        for i in range(self.seq_len, n):
            X_all.append(feat_arr[i - self.seq_len:i])

        if not X_all:
            return np.empty((0, 3))

        X_tensor = torch.tensor(np.array(X_all, dtype=np.float32), dtype=torch.float32)

        with torch.no_grad():
            for start in range(0, len(X_tensor), batch_size):
                batch = X_tensor[start:start + batch_size].to(DEVICE)
                probs = self.model.predict_proba(batch).cpu().numpy()
                all_probs.append(probs)

        return np.vstack(all_probs)  # (n - seq_len, 3)
