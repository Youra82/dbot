# src/dbot/strategy/lstm_logic.py
# Signal-Generierung aus LSTM-Predictions
import os
import logging
import numpy as np
import pandas as pd

from dbot.model.predictor import LSTMPredictor

logger = logging.getLogger(__name__)

# Globaler Cache: Predictor pro (model_path) nicht jedes Mal neu laden
_predictor_cache: dict = {}


def _dynamic_rr(confidence: float, threshold: float, rr_min: float = 1.5, rr_max: float = 3.0) -> float:
    """
    Skaliert R:R linear zwischen rr_min und rr_max basierend auf LSTM-Konfidenz.

    confidence = threshold  →  rr_min  (gerade über Threshold)
    confidence = 1.0        →  rr_max  (maximale Sicherheit)
    """
    conf_range = 1.0 - threshold
    if conf_range <= 0:
        return rr_min
    t = (confidence - threshold) / conf_range
    t = max(0.0, min(1.0, t))
    return rr_min + t * (rr_max - rr_min)


def _get_predictor(model_path: str, scaler_path: str, seq_len: int) -> LSTMPredictor:
    """Lädt Predictor aus Cache oder Festplatte."""
    key = (model_path, scaler_path)
    if key not in _predictor_cache:
        logger.info(f"Lade LSTM-Predictor: {model_path}")
        _predictor_cache[key] = LSTMPredictor.from_files(model_path, scaler_path, seq_len)
    return _predictor_cache[key]


def get_lstm_signal(df: pd.DataFrame, config: dict, artifacts_dir: str) -> dict:
    """
    Hauptfunktion: Berechnet LSTM-Signal für die aktuelle Marktlage.

    Args:
        df: OHLCV-DataFrame (neueste Kerzen, mind. seq_len + 60 Zeilen)
        config: Strategy-Config dict (enthält 'model' und 'risk' Keys)
        artifacts_dir: Pfad zum artifacts/models/ Verzeichnis

    Returns:
        dict mit Signal-Informationen:
            {
                'side': 'long' | 'short' | None,
                'confidence': float,
                'long_prob': float,
                'neutral_prob': float,
                'short_prob': float,
                'entry_price': float,
                'sl_price': float,
                'tp_price': float,
                'regime': str,
            }
    """
    symbol = config['market']['symbol']
    timeframe = config['market']['timeframe']
    model_cfg = config.get('model', {})
    risk_cfg = config['risk']

    seq_len = model_cfg.get('sequence_length', 60)
    long_threshold = model_cfg.get('long_threshold', 0.55)
    short_threshold = model_cfg.get('short_threshold', 0.55)
    rr_min = model_cfg.get('rr_min', 1.5)
    rr_max = model_cfg.get('rr_max', 3.0)
    sl_pct = risk_cfg['stop_loss_pct'] / 100.0

    # Modell und Scaler Pfade
    safe_name = f"{symbol.replace('/', '-').replace(':', '-')}_{timeframe}"
    model_path = os.path.join(artifacts_dir, 'models', f"{safe_name}.pt")
    scaler_path = os.path.join(artifacts_dir, 'models', f"{safe_name}_scaler.pkl")

    # Initialer Return-Wert (kein Signal)
    current_price = float(df['close'].iloc[-1])
    no_signal = {
        'side': None,
        'confidence': 0.0,
        'long_prob': 1/3,
        'neutral_prob': 1/3,
        'short_prob': 1/3,
        'entry_price': current_price,
        'sl_price': None,
        'tp_price': None,
        'regime': 'NO_MODEL',
    }

    # Prüfe ob Modell existiert
    if not os.path.exists(model_path):
        logger.warning(f"LSTM-Modell nicht gefunden: {model_path}. Bitte zuerst train_model.py ausführen.")
        return no_signal

    # Predictor laden (cached)
    try:
        predictor = _get_predictor(model_path, scaler_path, seq_len)
    except Exception as e:
        logger.error(f"Fehler beim Laden des Predictors: {e}")
        return no_signal

    # Prediction generieren
    try:
        probs = predictor.predict(df)  # [long_prob, neutral_prob, short_prob]
    except Exception as e:
        logger.error(f"Fehler bei LSTM-Prediction: {e}")
        return no_signal

    long_prob, neutral_prob, short_prob = probs[0], probs[1], probs[2]
    confidence = max(long_prob, short_prob)

    # Signal bestimmen
    side = None
    if long_prob > long_threshold and long_prob > short_prob:
        side = 'long'
    elif short_prob > short_threshold and short_prob > long_prob:
        side = 'short'

    # Regime basierend auf Confidence
    if confidence > 0.65:
        regime = 'LSTM_HIGH_CONF'
    elif confidence > 0.50:
        regime = 'LSTM_MED_CONF'
    else:
        regime = 'LSTM_LOW_CONF'

    # SL/TP berechnen (dynamisches R:R basierend auf LSTM-Konfidenz)
    sl_price = None
    tp_price = None
    if side is not None:
        threshold = long_threshold if side == 'long' else short_threshold
        rr = _dynamic_rr(confidence, threshold, rr_min, rr_max)
        if side == 'long':
            sl_price = current_price * (1 - sl_pct)
            sl_distance = current_price - sl_price
            tp_price = current_price + (rr * sl_distance)
        else:
            sl_price = current_price * (1 + sl_pct)
            sl_distance = sl_price - current_price
            tp_price = current_price - (rr * sl_distance)
        logger.debug(f"Dynamisches R:R: confidence={confidence:.3f} | threshold={threshold:.3f} | R:R=1:{rr:.2f}")

    result = {
        'side': side,
        'confidence': confidence,
        'long_prob': long_prob,
        'neutral_prob': neutral_prob,
        'short_prob': short_prob,
        'entry_price': current_price,
        'sl_price': sl_price,
        'tp_price': tp_price,
        'regime': regime,
    }

    logger.info(
        f"LSTM Signal | long={long_prob:.3f} | neutral={neutral_prob:.3f} | short={short_prob:.3f} "
        f"| Signal: {side or 'NEUTRAL'} | Regime: {regime}"
    )

    return result
