# src/dbot/analysis/show_results.py
# Analyse-Tool für dbot LSTM – 4 Modi wie ltbbot
import os
import sys
import json
import argparse
import logging
import pandas as pd
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("show_results")


# ─────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────

def load_all_configs():
    """Gibt alle _lstm.json Configs zurück."""
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    if not os.path.exists(configs_dir):
        return []
    return sorted([
        os.path.join(configs_dir, f)
        for f in os.listdir(configs_dir)
        if f.startswith('config_') and f.endswith('_lstm.json')
    ])


def load_ohlcv(symbol, timeframe, limit=2000):
    """Lädt OHLCV-Daten aus Cache oder Exchange."""
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cache_path = os.path.join(PROJECT_ROOT, 'data', f"{safe_name}.csv")
    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        logger.info(f"Cache geladen: {safe_name} ({len(df)} Kerzen)")
        return df

    logger.info(f"Lade {limit} Kerzen von Exchange: {symbol} ({timeframe})...")
    try:
        with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
            secrets = json.load(f)
        account = secrets.get('dbot', [{}])[0]
        from dbot.utils.exchange import Exchange
        exchange = Exchange(account)
        df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=limit)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        df.to_csv(cache_path)
        return df
    except Exception as e:
        logger.error(f"Konnte Daten nicht laden: {e}")
        return None


def model_exists(symbol, timeframe):
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt")
    return os.path.exists(model_path)


def print_separator(char="─", width=60):
    print(char * width)


def print_header(title):
    print_separator("═")
    print(f"  {title}")
    print_separator("═")


# ─────────────────────────────────────────────────────────────
# Modus 1: Einzel-Analyse (alle trainierten Strategien)
# ─────────────────────────────────────────────────────────────

def run_single_analysis(start_capital=1000.0):
    print_header("Modus 1: Einzel-Analyse aller LSTM-Strategien")

    config_files = load_all_configs()
    if not config_files:
        print("  Keine Configs in src/dbot/strategy/configs/ gefunden.")
        print("  Bitte zuerst: python train_model.py + python -m dbot.analysis.optimizer")
        return

    from dbot.model.predictor import LSTMPredictor
    from dbot.analysis.backtester import run_backtest, print_report

    results = []

    for config_path in config_files:
        with open(config_path) as f:
            config = json.load(f)

        symbol = config['market']['symbol']
        timeframe = config['market']['timeframe']
        safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"

        print(f"\n  Analysiere: {symbol} ({timeframe})")

        if not model_exists(symbol, timeframe):
            print(f"  ⚠  Kein Modell gefunden. train_model.py ausführen.")
            continue

        model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt")
        scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}_scaler.pkl")
        seq_len = config.get('model', {}).get('sequence_length', 60)

        try:
            predictor = LSTMPredictor.from_files(model_path, scaler_path, seq_len)
        except Exception as e:
            print(f"  ⚠  Modell konnte nicht geladen werden: {e}")
            continue

        df = load_ohlcv(symbol, timeframe)
        if df is None or len(df) < 200:
            print(f"  ⚠  Zu wenig Daten.")
            continue

        metrics = run_backtest(df, predictor, config, start_capital=start_capital, verbose=False)

        if 'error' in metrics:
            print(f"  ⚠  Backtest-Fehler: {metrics['error']}")
            continue

        results.append({
            'Strategie': f"{symbol} ({timeframe})",
            'Trades': metrics['total_trades'],
            'Win-Rate': f"{metrics['win_rate']:.1f}%",
            'PnL %': f"{metrics['pnl_pct']:+.1f}%",
            'Max DD %': f"{metrics['max_drawdown_pct']:.1f}%",
            'Calmar': f"{metrics['calmar_ratio']:.2f}",
            'End-Kapital': f"{metrics['final_capital']:.0f} USDT",
        })

    if not results:
        print("\n  Keine Ergebnisse. Bitte Modelle trainieren und Configs optimieren.")
        return

    print()
    print_separator()
    df_results = pd.DataFrame(results)
    print(df_results.to_string(index=False))
    print_separator()


# ─────────────────────────────────────────────────────────────
# Modus 2: Portfolio-Simulation (kombiniertes Kapital)
# ─────────────────────────────────────────────────────────────

def run_portfolio_simulation(start_capital=1000.0):
    print_header("Modus 2: Portfolio-Simulation (kombiniertes Kapital)")

    config_files = load_all_configs()
    if not config_files:
        print("  Keine Configs gefunden.")
        return

    from dbot.model.predictor import LSTMPredictor
    from dbot.analysis.backtester import run_backtest

    print("\n  Verfügbare Strategien:")
    valid = []
    for i, config_path in enumerate(config_files):
        with open(config_path) as f:
            config = json.load(f)
        symbol = config['market']['symbol']
        timeframe = config['market']['timeframe']
        has_model = model_exists(symbol, timeframe)
        mark = "✓" if has_model else "✗ (kein Modell)"
        print(f"  {i+1}) {symbol} ({timeframe}) {mark}")
        if has_model:
            valid.append((config_path, config))

    if not valid:
        print("\n  Keine trainierten Modelle vorhanden.")
        return

    print(f"\n  Alle {len(valid)} Strategie(n) mit trainiertem Modell werden kombiniert.")
    capital_per_strategy = start_capital / len(valid)
    print(f"  Kapital pro Strategie: {capital_per_strategy:.0f} USDT")
    print()

    total_pnl = 0.0
    all_results = []

    for config_path, config in valid:
        symbol = config['market']['symbol']
        timeframe = config['market']['timeframe']
        safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
        seq_len = config.get('model', {}).get('sequence_length', 60)

        model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt")
        scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}_scaler.pkl")

        try:
            predictor = LSTMPredictor.from_files(model_path, scaler_path, seq_len)
            df = load_ohlcv(symbol, timeframe)
            if df is None or len(df) < 200:
                continue
            metrics = run_backtest(df, predictor, config, start_capital=capital_per_strategy, verbose=False)
            pnl = metrics.get('pnl_usdt', 0)
            total_pnl += pnl
            all_results.append({
                'Strategie': f"{symbol} ({timeframe})",
                'Kapital': capital_per_strategy,
                'PnL USDT': f"{pnl:+.2f}",
                'PnL %': f"{metrics.get('pnl_pct', 0):+.1f}%",
                'Max DD %': f"{metrics.get('max_drawdown_pct', 0):.1f}%",
                'Trades': metrics.get('total_trades', 0),
            })
        except Exception as e:
            logger.warning(f"Fehler bei {symbol}: {e}")

    if all_results:
        print_separator()
        df_r = pd.DataFrame(all_results)
        print(df_r.to_string(index=False))
        print_separator()
        final_capital = start_capital + total_pnl
        pnl_pct = total_pnl / start_capital * 100
        print(f"\n  Portfolio-Gesamt:")
        print(f"  Startkapital:  {start_capital:.0f} USDT")
        print(f"  Endkapital:    {final_capital:.0f} USDT")
        print(f"  Gesamt PnL:    {total_pnl:+.2f} USDT ({pnl_pct:+.1f}%)")
        print_separator()


# ─────────────────────────────────────────────────────────────
# Modus 3: Modell-Info + Prediction-Verteilung
# ─────────────────────────────────────────────────────────────

def run_model_info():
    print_header("Modus 3: Modell-Info & Prediction-Verteilung")

    config_files = load_all_configs()
    if not config_files:
        print("  Keine Configs gefunden.")
        return

    import torch
    from dbot.model.predictor import LSTMPredictor
    from dbot.model.feature_engineering import compute_features, apply_scaler, load_scaler

    for config_path in config_files:
        with open(config_path) as f:
            config = json.load(f)

        symbol = config['market']['symbol']
        timeframe = config['market']['timeframe']
        safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"

        print(f"\n  ── {symbol} ({timeframe}) ──")

        model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt")
        scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}_scaler.pkl")

        if not os.path.exists(model_path):
            print("  Kein Modell vorhanden.")
            continue

        # Modell-Metadaten
        try:
            checkpoint = torch.load(model_path, map_location='cpu')
            meta = checkpoint.get('metadata', {})
            print(f"  LSTM: hidden={checkpoint.get('hidden_size', '?')} | layers={checkpoint.get('num_layers', '?')} | features={checkpoint.get('n_features', '?')}")
            print(f"  Trainiert: seq_len={meta.get('seq_len', '?')} | horizon={meta.get('horizon_candles', '?')} | neutral_zone={meta.get('neutral_zone_pct', '?')}%")
            print(f"  Val Accuracy: {meta.get('best_val_acc', 0)*100:.1f}%")
        except Exception as e:
            print(f"  Metadaten nicht lesbar: {e}")

        # Prediction-Verteilung auf aktuellen Daten
        try:
            seq_len = config.get('model', {}).get('sequence_length', 60)
            predictor = LSTMPredictor.from_files(model_path, scaler_path, seq_len)
            df = load_ohlcv(symbol, timeframe, limit=500)
            if df is not None and len(df) >= seq_len + 60:
                feat_df = compute_features(df)
                scaled_df = apply_scaler(feat_df, predictor.scaler)
                all_probs = predictor.predict_batch(scaled_df)
                long_threshold = config.get('model', {}).get('long_threshold', 0.55)
                short_threshold = config.get('model', {}).get('short_threshold', 0.55)
                n = len(all_probs)
                n_long = sum(1 for p in all_probs if p[0] > long_threshold and p[0] > p[2])
                n_short = sum(1 for p in all_probs if p[2] > short_threshold and p[2] > p[0])
                n_neutral = n - n_long - n_short
                print(f"  Signal-Verteilung ({n} Kerzen):")
                print(f"    LONG:    {n_long:4d} ({n_long/n*100:.1f}%) | Threshold: {long_threshold}")
                print(f"    NEUTRAL: {n_neutral:4d} ({n_neutral/n*100:.1f}%)")
                print(f"    SHORT:   {n_short:4d} ({n_short/n*100:.1f}%) | Threshold: {short_threshold}")

                # Letztes Signal anzeigen
                last_probs = all_probs[-1]
                if last_probs[0] > long_threshold and last_probs[0] > last_probs[2]:
                    last_signal = f"LONG  (p={last_probs[0]:.3f})"
                elif last_probs[2] > short_threshold and last_probs[2] > last_probs[0]:
                    last_signal = f"SHORT (p={last_probs[2]:.3f})"
                else:
                    last_signal = f"NEUTRAL"
                print(f"  Aktuelles Signal: {last_signal}")
        except Exception as e:
            logger.warning(f"Prediction-Verteilung fehlgeschlagen: {e}")

        # Backtest-Metriken aus Config
        bt = config.get('_backtest_metrics', {})
        if bt:
            print(f"  Optimizer-Ergebnis: PnL={bt.get('pnl_pct', 0):+.1f}% | DD={bt.get('max_drawdown_pct', 0):.1f}% | Calmar={bt.get('calmar_ratio', 0):.2f} | Trades={bt.get('trades', 0)}")


# ─────────────────────────────────────────────────────────────
# Modus 4: Live-Status (Tracker-Dateien)
# ─────────────────────────────────────────────────────────────

def run_live_status():
    print_header("Modus 4: Live-Status (Tracker & Performance)")

    tracker_dir = os.path.join(PROJECT_ROOT, 'artifacts', 'tracker')
    if not os.path.exists(tracker_dir):
        print("  Kein Tracker-Verzeichnis gefunden (noch nie gelaufen?).")
        return

    tracker_files = sorted([f for f in os.listdir(tracker_dir) if f.endswith('.json')])
    if not tracker_files:
        print("  Keine Tracker-Dateien gefunden.")
        return

    for filename in tracker_files:
        path = os.path.join(tracker_dir, filename)
        try:
            with open(path) as f:
                tracker = json.load(f)
        except Exception:
            continue

        name = filename.replace('.json', '')
        status = tracker.get('status', 'unbekannt')
        last_side = tracker.get('last_side', '-')
        perf = tracker.get('performance', {})
        sl_ids = tracker.get('stop_loss_ids', [])
        tp_ids = tracker.get('take_profit_ids', [])

        print(f"\n  ── {name} ──")
        print(f"  Status:       {status}")
        print(f"  Letzte Seite: {last_side}")
        if sl_ids or tp_ids:
            print(f"  Offene SL-IDs: {len(sl_ids)} | TP-IDs: {len(tp_ids)}")
        if 'last_notified_entry_price' in tracker:
            print(f"  Entry-Preis:  {tracker['last_notified_entry_price']:.4f} ({tracker.get('last_notified_side', '?')})")

        if perf:
            total = perf.get('total_trades', 0)
            wins = perf.get('winning_trades', 0)
            losses = perf.get('losing_trades', 0)
            consec = perf.get('consecutive_losses', 0)
            wr = perf.get('win_rate', wins / total * 100 if total > 0 else 0)
            print(f"  Performance:  {total} Trades | Win-Rate: {wr:.1f}% | Verluste in Folge: {consec}")

            if status == 'stop_loss_triggered':
                print(f"  ⚠  Cooldown aktiv — kein neuer Entry bis LSTM Gegenrichtung signalisiert")
            elif consec >= 5:
                print(f"  ⚠  Risiko-Reduktion aktiv (5+ Verluste in Folge)")

    print()
    print_separator()

    # Logs-Zusammenfassung
    log_dir = os.path.join(PROJECT_ROOT, 'logs')
    if os.path.exists(log_dir):
        log_files = [f for f in os.listdir(log_dir) if f.startswith('dbot_') and f.endswith('.log')]
        if log_files:
            print(f"\n  Letzte Log-Einträge (master_runner.log):")
            master_log = os.path.join(log_dir, 'master_runner.log')
            if os.path.exists(master_log):
                try:
                    with open(master_log) as f:
                        lines = f.readlines()
                    for line in lines[-10:]:
                        print(f"  {line.rstrip()}")
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="dbot Analyse-Tool")
    parser.add_argument('--mode', type=int, default=1, choices=[1, 2, 3, 4],
                        help="1=Einzel 2=Portfolio 3=Modell-Info 4=Live-Status")
    parser.add_argument('--capital', type=float, default=1000.0, help="Startkapital USDT")
    args = parser.parse_args()

    if args.mode == 1:
        run_single_analysis(args.capital)
    elif args.mode == 2:
        run_portfolio_simulation(args.capital)
    elif args.mode == 3:
        run_model_info()
    elif args.mode == 4:
        run_live_status()


if __name__ == "__main__":
    main()
