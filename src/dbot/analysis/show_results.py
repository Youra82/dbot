# src/dbot/analysis/show_results.py
# Analyse-Tool für dbot LSTM – 4 Modi wie stbot
import os
import sys
import json
import shutil
import argparse
import logging
import pandas as pd
from datetime import datetime

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
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    if not os.path.exists(configs_dir):
        return []
    return sorted([
        os.path.join(configs_dir, f)
        for f in os.listdir(configs_dir)
        if f.startswith('config_') and f.endswith('_lstm.json')
    ])


def load_ohlcv(symbol, timeframe, start_date=None, end_date=None, limit=2000):
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cache_path = os.path.join(PROJECT_ROOT, 'data', f"{safe_name}.csv")
    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        logger.info(f"Cache geladen: {safe_name} ({len(df)} Kerzen)")
    else:
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
        except Exception as e:
            logger.error(f"Konnte Daten nicht laden: {e}")
            return None

    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    if start_date:
        df = df[df.index >= pd.Timestamp(start_date, tz='UTC')]
    if end_date:
        df = df[df.index < pd.Timestamp(end_date, tz='UTC') + pd.Timedelta(days=1)]

    return df


def model_exists(symbol, timeframe):
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    return os.path.exists(os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt"))


def print_separator(char="─", width=60):
    print(char * width)


def print_header(title):
    print_separator("═")
    print(f"  {title}")
    print_separator("═")


# ─────────────────────────────────────────────────────────────
# Modus 1: Einzel-Analyse
# ─────────────────────────────────────────────────────────────

def run_single_analysis(start_capital=1000.0, start_date=None, end_date=None):
    print_header("Modus 1: Einzel-Analyse aller LSTM-Strategien")
    print(f"  Zeitraum: {start_date} bis {end_date} | Startkapital: {start_capital:.0f} USDT")

    config_files = load_all_configs()
    if not config_files:
        print("  Keine Configs gefunden. Bitte ./run_pipeline.sh ausführen.")
        return

    from dbot.model.predictor import LSTMPredictor
    from dbot.analysis.backtester import run_backtest

    results = []

    for config_path in config_files:
        with open(config_path) as f:
            config = json.load(f)
        symbol = config['market']['symbol']
        timeframe = config['market']['timeframe']
        safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"

        print(f"\n  Analysiere: {symbol} ({timeframe})")

        if not model_exists(symbol, timeframe):
            print(f"  ⚠  Kein Modell gefunden.")
            continue

        model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt")
        scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}_scaler.pkl")
        seq_len = config.get('model', {}).get('sequence_length', 60)

        try:
            predictor = LSTMPredictor.from_files(model_path, scaler_path, seq_len)
        except Exception as e:
            print(f"  ⚠  Modell-Fehler: {e}")
            continue

        df = load_ohlcv(symbol, timeframe, start_date=start_date, end_date=end_date)
        if df is None or len(df) < 200:
            print(f"  ⚠  Zu wenig Daten ({len(df) if df is not None else 0} Kerzen).")
            continue

        metrics = run_backtest(df, predictor, config, start_capital=start_capital, verbose=False)
        if 'error' in metrics:
            print(f"  ⚠  Backtest-Fehler: {metrics['error']}")
            continue

        actual_start = df.index[0].strftime('%Y-%m-%d')
        actual_end = df.index[-1].strftime('%Y-%m-%d')

        results.append({
            'Strategie': f"{symbol} ({timeframe})",
            'Zeitraum': f"{actual_start} → {actual_end}",
            'Trades': metrics.get('total_trades', 0),
            'Win-Rate': f"{metrics.get('win_rate', 0):.1f}%",
            'PnL %': f"{metrics.get('pnl_pct', 0):+.1f}%",
            'Max DD %': f"{metrics.get('max_drawdown_pct', 0):.1f}%",
            'Calmar': f"{metrics.get('calmar_ratio', 0):.2f}",
            'Endkapital': f"{metrics.get('final_capital', start_capital):.2f} USDT",
        })

    if not results:
        print("\n  Keine Ergebnisse.")
        return

    print()
    print_separator()
    df_results = pd.DataFrame(results)
    pd.set_option('display.width', 1000)
    pd.set_option('display.max_columns', None)
    print(df_results.to_string(index=False))
    print_separator()


# ─────────────────────────────────────────────────────────────
# Modus 2: Portfolio-Simulation (manuelle Auswahl)
# ─────────────────────────────────────────────────────────────

def run_portfolio_simulation(start_capital=1000.0, start_date=None, end_date=None):
    print_header("Modus 2: Portfolio-Simulation")
    print(f"  Zeitraum: {start_date} bis {end_date} | Startkapital: {start_capital:.0f} USDT")

    config_files = load_all_configs()
    if not config_files:
        print("  Keine Configs gefunden.")
        return

    from dbot.model.predictor import LSTMPredictor
    from dbot.analysis.backtester import run_backtest

    available = []
    print("\n  Verfügbare Strategien:")
    for i, config_path in enumerate(config_files):
        with open(config_path) as f:
            config = json.load(f)
        symbol = config['market']['symbol']
        timeframe = config['market']['timeframe']
        has_model = model_exists(symbol, timeframe)
        mark = "✓" if has_model else "✗ (kein Modell)"
        print(f"  {i+1}) {symbol} ({timeframe}) {mark}")
        if has_model:
            available.append((config_path, config))

    if not available:
        print("\n  Keine trainierten Modelle vorhanden.")
        return

    selection = input("\n  Welche Strategien simulieren? (Zahlen mit Komma, z.B. 1,2 oder 'alle'): ").strip()
    if not selection or selection.lower() == 'alle':
        selected = available
    else:
        try:
            indices = [int(x.strip()) - 1 for x in selection.split(',')]
            selected = [available[i] for i in indices if 0 <= i < len(available)]
        except (ValueError, IndexError):
            print("  Ungültige Auswahl, verwende alle.")
            selected = available

    if not selected:
        print("  Keine gültigen Strategien.")
        return

    capital_per_strategy = start_capital / len(selected)
    print(f"\n  {len(selected)} Strategie(n) | Kapital je: {capital_per_strategy:.2f} USDT\n")

    total_pnl = 0.0
    total_trades = 0
    all_wins = 0
    all_losses = 0
    max_dd_overall = 0.0
    liquidated = False
    liq_info = None
    all_results = []

    for config_path, config in selected:
        symbol = config['market']['symbol']
        timeframe = config['market']['timeframe']
        safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
        seq_len = config.get('model', {}).get('sequence_length', 60)

        model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt")
        scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}_scaler.pkl")

        try:
            predictor = LSTMPredictor.from_files(model_path, scaler_path, seq_len)
            df = load_ohlcv(symbol, timeframe, start_date=start_date, end_date=end_date)
            if df is None or len(df) < 200:
                print(f"  ⚠  Zu wenig Daten für {symbol}.")
                continue
            metrics = run_backtest(df, predictor, config, start_capital=capital_per_strategy, verbose=False)
            pnl = metrics.get('pnl_usdt', 0.0)
            total_pnl += pnl
            total_trades += metrics.get('total_trades', 0)
            all_wins += metrics.get('winning_trades', 0)
            all_losses += metrics.get('losing_trades', 0)
            dd = metrics.get('max_drawdown_pct', 0.0)
            if dd > max_dd_overall:
                max_dd_overall = dd
            if metrics.get('final_capital', capital_per_strategy) <= 0:
                liquidated = True
                liq_info = f"{symbol} ({timeframe})"

            actual_start = df.index[0].strftime('%Y-%m-%d')
            actual_end = df.index[-1].strftime('%Y-%m-%d')
            all_results.append({
                'Strategie': f"{symbol} ({timeframe})",
                'Zeitraum': f"{actual_start} → {actual_end}",
                'Kapital': f"{capital_per_strategy:.2f}",
                'PnL USDT': f"{pnl:+.2f}",
                'PnL %': f"{metrics.get('pnl_pct', 0):+.1f}%",
                'Max DD %': f"{dd:.1f}%",
                'Trades': metrics.get('total_trades', 0),
            })
        except Exception as e:
            logger.warning(f"Fehler bei {symbol}: {e}")

    if all_results:
        print_separator()
        df_r = pd.DataFrame(all_results)
        pd.set_option('display.width', 1000)
        print(df_r.to_string(index=False))
        print_separator()

    final_capital = start_capital + total_pnl
    pnl_pct = total_pnl / start_capital * 100
    win_rate = all_wins / total_trades * 100 if total_trades > 0 else 0.0

    print(f"\n--- Portfolio-Gesamt ---")
    print(f"Zeitraum:          {start_date} bis {end_date}")
    print(f"Startkapital:      {start_capital:.2f} USDT")
    print(f"Endkapital:        {final_capital:.2f} USDT")
    print(f"Gesamt PnL:        {total_pnl:+.2f} USDT ({pnl_pct:+.1f}%)")
    print(f"Anzahl Trades:     {total_trades}")
    print(f"Win-Rate:          {win_rate:.1f}%")
    print(f"Portfolio Max DD:  {max_dd_overall:.1f}%")
    print(f"Liquidiert:        {'JA — ' + liq_info if liquidated else 'NEIN'}")
    print_separator()


# ─────────────────────────────────────────────────────────────
# Modus 3: Automatische Portfolio-Optimierung (Greedy)
# ─────────────────────────────────────────────────────────────

def _portfolio_metrics(candidates, start_capital):
    """Berechnet Portfolio-Metriken für eine Kombination (PnL skaliert linear mit Kapital)."""
    n = len(candidates)
    if n == 0:
        return start_capital, 0.0, 0.0
    scale = 1.0 / n  # Kapital wird gleichmäßig aufgeteilt
    total_pnl = sum(s['pnl_usdt'] * scale for s in candidates)
    portfolio_end_cap = start_capital + total_pnl
    portfolio_dd = max(s['max_dd'] for s in candidates)
    return portfolio_end_cap, total_pnl, portfolio_dd


def _write_to_settings(portfolio):
    """Schreibt das optimale Portfolio in settings.json."""
    settings_path = os.path.join(PROJECT_ROOT, 'settings.json')
    backup_path = settings_path + '.backup'
    try:
        shutil.copy(settings_path, backup_path)
        with open(settings_path) as f:
            settings = json.load(f)

        new_strategies = [
            {"symbol": s['symbol'], "timeframe": s['timeframe'], "active": True}
            for s in portfolio
        ]
        settings.setdefault('live_trading_settings', {})['active_strategies'] = new_strategies

        with open(settings_path, 'w') as f:
            json.dump(settings, f, indent=4)

        print(f"\n✅ {len(portfolio)} Strategie(n) wurden in settings.json eingetragen:")
        for s in portfolio:
            print(f"   - {s['symbol']} ({s['timeframe']})")
        print(f"✅ settings.json erfolgreich aktualisiert!")
        print(f"   Backup: settings.json.backup")
    except Exception as e:
        print(f"\n❌ Fehler beim Schreiben in settings.json: {e}")


def run_auto_portfolio_optimizer(start_capital=1000.0, start_date=None, end_date=None):
    print_header("Modus 3: Automatische Portfolio-Optimierung")
    print(f"  Zeitraum: {start_date} bis {end_date} | Startkapital: {start_capital:.0f} USDT")

    max_dd_str = input("\n  Gewünschter maximaler Drawdown in % [Standard: 30]: ").strip()
    try:
        target_max_dd = float(max_dd_str) if max_dd_str else 30.0
    except ValueError:
        print("  Ungültige Eingabe, verwende Standard: 30%")
        target_max_dd = 30.0
    print(f"  Ziel: Maximaler Profit bei max. {target_max_dd:.0f}% Drawdown.\n")

    config_files = load_all_configs()
    if not config_files:
        print("  Keine Configs gefunden. Bitte ./run_pipeline.sh ausführen.")
        return

    from dbot.model.predictor import LSTMPredictor
    from dbot.analysis.backtester import run_backtest

    # ── 1. Alle Strategien laden & Einzel-Backtest ──────────────
    print("  1/3: Analysiere Einzel-Performance & filtere nach Max DD...")
    single_results = []

    for config_path in config_files:
        with open(config_path) as f:
            config = json.load(f)
        symbol = config['market']['symbol']
        timeframe = config['market']['timeframe']
        safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
        filename = os.path.basename(config_path)

        if not model_exists(symbol, timeframe):
            continue

        model_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}.pt")
        scaler_path = os.path.join(PROJECT_ROOT, 'artifacts', 'models', f"{safe_name}_scaler.pkl")
        seq_len = config.get('model', {}).get('sequence_length', 60)

        try:
            predictor = LSTMPredictor.from_files(model_path, scaler_path, seq_len)
            df = load_ohlcv(symbol, timeframe, start_date=start_date, end_date=end_date)
            if df is None or len(df) < 200:
                continue
            metrics = run_backtest(df, predictor, config, start_capital=start_capital, verbose=False)
            if 'error' in metrics:
                continue

            max_dd = metrics.get('max_drawdown_pct', 100.0)
            end_capital = metrics.get('final_capital', start_capital)
            pnl_usdt = metrics.get('pnl_usdt', 0.0)
            liquidated = end_capital <= 0

            if not liquidated and max_dd <= target_max_dd:
                single_results.append({
                    'filename': filename,
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'end_capital': end_capital,
                    'pnl_usdt': pnl_usdt,
                    'max_dd': max_dd,
                })
        except Exception as e:
            logger.warning(f"Fehler bei {symbol} ({timeframe}): {e}")

    if not single_results:
        print(f"\n  Keine Strategie erfüllt Max DD <= {target_max_dd:.0f}%. Portfolio-Optimierung nicht möglich.")
        return

    # Sortiere nach Endkapital (beste zuerst)
    single_results.sort(key=lambda x: x['end_capital'], reverse=True)

    # ── 2. Greedy: Bestes Einzel-Portfolio aufbauen ──────────────
    best = single_results[0]
    best_end_cap, _, best_dd = _portfolio_metrics([best], start_capital)
    print(f"  2/3: Beste Einzelstrategie: {best['filename']} "
          f"(Endkapital: {best_end_cap:.2f} USDT, Max DD: {best_dd:.1f}%)")
    print("  3/3: Suche optimales Team...")

    best_portfolio = [best]
    candidate_pool = single_results[1:]

    while True:
        best_addition = None
        current_best_cap, _, _ = _portfolio_metrics(best_portfolio, start_capital)

        for candidate in candidate_pool:
            combined = best_portfolio + [candidate]
            new_cap, _, new_dd = _portfolio_metrics(combined, start_capital)
            if new_dd <= target_max_dd and new_cap > current_best_cap:
                current_best_cap = new_cap
                best_addition = candidate

        if best_addition:
            new_cap, _, new_dd = _portfolio_metrics(best_portfolio + [best_addition], start_capital)
            print(f"  -> Füge hinzu: {best_addition['filename']} "
                  f"(Neues Kapital: {new_cap:.2f} USDT, Max DD: {new_dd:.1f}%)")
            best_portfolio.append(best_addition)
            candidate_pool.remove(best_addition)
        else:
            print("  Keine weitere Verbesserung des Profits "
                  "(unter Einhaltung des Max DD) durch Hinzufügen von Strategien gefunden. "
                  "Optimierung beendet.")
            break

    # ── Ergebnis anzeigen ────────────────────────────────────────
    final_cap, total_pnl, portfolio_dd = _portfolio_metrics(best_portfolio, start_capital)
    pnl_pct = total_pnl / start_capital * 100

    print()
    print("=" * 55)
    print("     Ergebnis der automatischen Portfolio-Optimierung")
    print("=" * 55)
    print(f"Zeitraum:           {start_date} bis {end_date}")
    print(f"Startkapital:       {start_capital:.2f} USDT")
    print(f"Bedingung:          Max Drawdown <= {target_max_dd:.0f}%")
    print(f"\nOptimales Portfolio ({len(best_portfolio)} Strategie(n)):")
    for s in best_portfolio:
        print(f"  - {s['filename']}")
    print()
    print("--- Simulierte Performance dieses Portfolios ---")
    print(f"Endkapital:         {final_cap:.2f} USDT")
    print(f"Gesamt PnL:         {total_pnl:+.2f} USDT ({pnl_pct:+.1f}%)")
    print(f"Portfolio Max DD:   {portfolio_dd:.1f}%")
    print(f"Liquidiert:         NEIN")
    print("=" * 55)

    # ── Settings.json aktualisieren? ─────────────────────────────
    print()
    answer = input("─" * 49 + "\nSollen die optimalen Ergebnisse automatisch in settings.json eingetragen werden? (j/n): ").strip().lower()
    if answer in ['j', 'y', 'ja', 'yes']:
        _write_to_settings(best_portfolio)
    else:
        print("\nℹ  Settings wurden NICHT aktualisiert.")
        print("Du kannst die Strategien später manuell in settings.json eintragen.")


# ─────────────────────────────────────────────────────────────
# Modus 4: Live-Status (Tracker-Dateien)
# ─────────────────────────────────────────────────────────────

def run_live_status(start_date=None, end_date=None):
    print_header("Modus 4: Live-Status (Tracker & Performance)")
    if start_date and end_date:
        print(f"  Zeitraum: {start_date} bis {end_date}\n")

    tracker_dir = os.path.join(PROJECT_ROOT, 'artifacts', 'tracker')
    if not os.path.exists(tracker_dir) or not os.listdir(tracker_dir):
        print("  Keine Tracker-Dateien gefunden (Bot noch nicht gestartet).")
    else:
        tracker_files = sorted([f for f in os.listdir(tracker_dir) if f.endswith('.json')])
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
                consec = perf.get('consecutive_losses', 0)
                wr = wins / total * 100 if total > 0 else 0
                print(f"  Performance:  {total} Trades | Win-Rate: {wr:.1f}% | Verluste in Folge: {consec}")
                if status == 'stop_loss_triggered':
                    print(f"  ⚠  Cooldown aktiv")
                elif consec >= 5:
                    print(f"  ⚠  Risiko-Reduktion aktiv (5+ Verluste in Folge)")

        print()
        print_separator()

    log_dir = os.path.join(PROJECT_ROOT, 'logs')
    master_log = os.path.join(log_dir, 'master_runner.log') if log_dir else None
    if master_log and os.path.exists(master_log):
        print(f"\n  Letzte Log-Einträge (master_runner.log):")
        try:
            with open(master_log) as f:
                lines = f.readlines()
            if start_date:
                lines = [l for l in lines if l[:10] >= start_date]
            for line in lines[-15:]:
                print(f"  {line.rstrip()}")
        except Exception:
            pass
    else:
        print("\n  Kein Log vorhanden (master_runner noch nicht gestartet).")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="dbot Analyse-Tool")
    parser.add_argument('--mode', type=int, default=1, choices=[1, 2, 3, 4])
    args = parser.parse_args()

    print("\n--- Konfiguration ---")
    start_date = input("Startdatum (JJJJ-MM-TT) [Standard: 2022-01-01]: ").strip() or "2022-01-01"
    end_date = input(f"Enddatum   (JJJJ-MM-TT) [Standard: Heute]: ").strip() or datetime.now().strftime("%Y-%m-%d")
    cap_str = input("Startkapital USDT         [Standard: 1000]: ").strip()
    start_capital = float(cap_str) if cap_str else 1000.0
    print(f"Zeitraum: {start_date} → {end_date} | Kapital: {start_capital:.0f} USDT")
    print_separator()

    if args.mode == 1:
        run_single_analysis(start_capital, start_date, end_date)
    elif args.mode == 2:
        run_portfolio_simulation(start_capital, start_date, end_date)
    elif args.mode == 3:
        run_auto_portfolio_optimizer(start_capital, start_date, end_date)
    elif args.mode == 4:
        run_live_status(start_date, end_date)


if __name__ == "__main__":
    main()
