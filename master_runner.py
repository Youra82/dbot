# master_runner.py
"""
DBot Master Runner - High-Frequency Momentum Scalper
Startet alle aktiven Trading-Strategien
"""
import json
import subprocess
import sys
import os
from datetime import datetime

# Path setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = SCRIPT_DIR
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))


def main():
    """
    Master Runner für DBot
    - Liest settings.json für aktive Strategien
    - Startet separate Prozesse für jede Strategie
    """
    settings_file = os.path.join(SCRIPT_DIR, 'settings.json')
    secret_file = os.path.join(SCRIPT_DIR, 'secret.json')
    bot_runner_script = os.path.join(SCRIPT_DIR, 'src', 'dbot', 'strategy', 'run.py')
    
    # Python Interpreter (Virtual Environment)
    python_executable = os.path.join(SCRIPT_DIR, '.venv', 'bin', 'python3')
    if not os.path.exists(python_executable):
        # Windows alternative
        python_executable = os.path.join(SCRIPT_DIR, '.venv', 'Scripts', 'python.exe')
    if not os.path.exists(python_executable):
        python_executable = 'python'  # Fallback to system python
    
    print("=" * 70)
    print("🚀 DBot Master Runner v1.0")
    print("   High-Frequency Momentum Scalper")
    print("=" * 70)
    print()
    
    # Load settings
    try:
        with open(settings_file, 'r') as f:
            settings = json.load(f)
        
        with open(secret_file, 'r') as f:
            secrets = json.load(f)
        
        if 'dbot' not in secrets:
            print("❌ Fehler: Kein 'dbot' Account in secret.json gefunden!")
            return
        
    except FileNotFoundError as e:
        print(f"❌ Fehler: Datei nicht gefunden: {e}")
        return
    except json.JSONDecodeError as e:
        print(f"❌ Fehler: Ungültige JSON: {e}")
        return
    
    # Get active strategies
    active_strategies = [
        s for s in settings['live_trading_settings']['active_strategies']
        if s.get('active', False)
    ]
    
    if not active_strategies:
        print("⚠️  Keine aktiven Strategien gefunden in settings.json!")
        print("   Setze 'active': true für mindestens eine Strategie")
        return
    
    print(f"📊 Gefundene aktive Strategien: {len(active_strategies)}")
    print()
    
    # Start strategy processes
    processes = []
    
    for i, strategy in enumerate(active_strategies, 1):
        symbol = strategy['symbol']
        timeframe = strategy['timeframe']
        use_momentum_filter = strategy.get('use_momentum_filter', True)
        
        print(f"[{i}/{len(active_strategies)}] Starte Strategie:")
        print(f"   Symbol: {symbol}")
        print(f"   Timeframe: {timeframe}")
        print(f"   Momentum Filter: {use_momentum_filter}")
        
        try:
            # Start subprocess
            cmd = [
                python_executable,
                bot_runner_script,
                symbol,
                timeframe,
                str(use_momentum_filter).lower()
            ]
            
            log_file = os.path.join(SCRIPT_DIR, 'logs', f'dbot_{symbol.replace("/", "")}_{timeframe}.log')
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            with open(log_file, 'a') as log:
                log.write(f"\n{'='*70}\n")
                log.write(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                log.write(f"{'='*70}\n\n")
                
                process = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=PROJECT_ROOT
                )
                processes.append(process)
            
            print(f"   ✅ Prozess gestartet (PID: {process.pid})")
            print(f"   📝 Log: {log_file}")
            print()
            
        except Exception as e:
            print(f"   ❌ Fehler beim Starten: {e}")
            print()
    
    if not processes:
        print("❌ Keine Prozesse gestartet!")
        return
    
    print("=" * 70)
    print(f"✅ {len(processes)} Strategie(n) erfolgreich gestartet")
    print("=" * 70)
    print()
    print("💡 Tipps:")
    print("   - Logs anzeigen: tail -f logs/dbot_*.log")
    print("   - Status prüfen: ./show_status.sh")
    print("   - Bot stoppen: pkill -f 'dbot'")
    print()
    
    # Wait for all processes
    try:
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        print("\n⚠️  Master Runner gestoppt durch Benutzer")
        for process in processes:
            process.terminate()


if __name__ == "__main__":
    main()
