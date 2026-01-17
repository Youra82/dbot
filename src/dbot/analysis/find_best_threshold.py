import os
import sys
print("find_best_threshold.py ist veraltet. dbot nutzt keine ANN-Pipeline mehr. Bitte ./show_results.sh für SMC-Backtests verwenden.")
sys.exit(1)

import os
import json
import pandas as pd
import numpy as np
import argparse
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.analysis.backtester import load_data
from dbot.utils.ann_model import load_model_and_scaler, prepare_data_for_ann


def find_best_threshold(symbol: str, timeframe: str, start_date: str, end_date: str):
    print(f"--- Starte Threshold-Analyse für {symbol} ({timeframe}) ---")
    safe_filename = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f'ann_predictor_{safe_filename}.h5')
    scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f'ann_scaler_{safe_filename}.joblib')
    model, scaler = load_model_and_scaler(model_path, scaler_path)
    if not model or not scaler:
        print("❌ Fehler: Modell/Scaler nicht gefunden. Training muss zuerst laufen.")
        return None

    data = load_data(symbol, timeframe, start_date, end_date)
    if data.empty:
        print("❌ Fehler: Keine Daten zum Analysieren gefunden.")
        return None

    X, y_true = prepare_data_for_ann(data, timeframe, verbose=False)
    if X.empty:
        print("❌ Fehler: Keine Handelssignale im Datensatz gefunden.")
        return None
    predictions = model.predict(scaler.transform(X), verbose=0).flatten()

    results = []
    best_score = -1
    best_threshold = 0.65

    for threshold in np.arange(0.60, 0.96, 0.01):
        threshold = round(threshold, 2)
        long_signals = predictions >= threshold
        short_signals = predictions <= (1 - threshold)
        total_signals = np.sum(long_signals) + np.sum(short_signals)
        if total_signals < 50:
            continue
        correct_longs = np.sum(y_true[long_signals] == 1)
        correct_shorts = np.sum(y_true[short_signals] == 0)
        total_correct = correct_longs + correct_shorts
        win_rate = total_correct / total_signals
        score = (win_rate - 0.5) * np.sqrt(total_signals)
        results.append({
            "Threshold": threshold,
            "Signale": total_signals,
            "Trefferquote": f"{win_rate:.2%}",
            "Score": score
        })
        if score > best_score:
            best_score = score
            best_threshold = threshold

    if not results:
        print("❌ Konnte keinen geeigneten Threshold mit genügend Signalen finden.")
        return None

    results_df = pd.DataFrame(results)
    print("\n--- Threshold-Analyse-Ergebnisse ---")
    print(results_df.to_string(index=False))
    print(f"\n✅ Bester gefundener Threshold: {best_threshold} (Score: {best_score:.2f})")
    return best_threshold


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Findet den optimalen Prediction Threshold.")
    parser.add_argument('--symbol', required=True, type=str)
    parser.add_argument('--timeframe', required=True, type=str)
    parser.add_argument('--start_date', required=True, type=str)
    parser.add_argument('--end_date', required=True, type=str)
    args = parser.parse_args()
    best_value = find_best_threshold(f"{args.symbol}/USDT:USDT", args.timeframe, args.start_date, args.end_date)
    if best_value:
        print("\n--- Output für Pipeline ---")
        print(best_value)
