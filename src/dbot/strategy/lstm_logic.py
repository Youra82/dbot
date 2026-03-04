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

    # SL/TP berechnen (1:2 Risk:Reward)
    sl_price = None
    tp_price = None
    if side == 'long':
        sl_price = current_price * (1 - sl_pct)
        sl_distance = current_price - sl_price
        tp_price = current_price + (2 * sl_distance)
    elif side == 'short':
        sl_price = current_price * (1 + sl_pct)
        sl_distance = sl_price - current_price
        tp_price = current_price - (2 * sl_distance)

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
