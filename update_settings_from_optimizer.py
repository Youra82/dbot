#!/usr/bin/env python3
"""
Script um die settings.json basierend auf den Optimierungs-Ergebnissen zu aktualisieren.
"""
import json
import os
import sys
from pathlib import Path

def parse_config_filename(filename):
    """
    Extrahiert Symbol und Timeframe aus einem Config-Dateinamen.
    z.B. "config_SOLUSDTUSDT_15m.json" -> ("SOL/USDT:USDT", "15m")
    """
    # Entferne "config_" und ".json"
    base = filename.replace('config_', '').replace('.json', '')
    
    # Timeframes die möglich sind
    timeframes = ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d', '1w']
    
    # Finde Timeframe am Ende
    timeframe = None
    for tf in timeframes:
        if base.endswith('_' + tf):
            timeframe = tf
            symbol_part = base[:-len('_' + tf)]
            break
    
    if not timeframe:
        return None, None
    
    # Konvertiere z.B. "SOLUSDTUSDT" -> "SOL/USDT:USDT"
    # Format: BASEUSDTUSDT -> BASE/USDT:USDT
    if symbol_part.endswith('USDTUSDT'):
        base_currency = symbol_part[:-8]  # Entferne "USDTUSDT"
        symbol = f"{base_currency}/USDT:USDT"
    else:
        # Fallback für andere Formate
        symbol = symbol_part
    
    return symbol, timeframe


def update_settings_with_optimal_strategies(optimal_configs, settings_path='settings.json'):
    """
    Aktualisiert die settings.json mit den optimalen Strategien.
    
    Args:
        optimal_configs: Liste von Config-Dateinamen (z.B. ["config_SOLUSDTUSDT_15m.json"])
        settings_path: Pfad zur settings.json
    """
    # Lade aktuelle settings
    with open(settings_path, 'r', encoding='utf-8') as f:
        settings = json.load(f)
    
    # Parse optimale Strategien
    optimal_strategies = []
    for config_file in optimal_configs:
        symbol, timeframe = parse_config_filename(config_file)
        if symbol and timeframe:
            optimal_strategies.append({
                'symbol': symbol,
                'timeframe': timeframe,
                'use_macd_filter': False,
                'active': True
            })
    
    if not optimal_strategies:
        print("❌ Konnte keine Strategien aus den Config-Dateien parsen.")
        return False
    
    # Backup erstellen
    backup_path = settings_path + '.backup'
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2)
    print(f"✔ Backup erstellt: {backup_path}")
    
    # Ersetze active_strategies mit den optimalen
    old_count = len(settings['live_trading_settings']['active_strategies'])
    settings['live_trading_settings']['active_strategies'] = optimal_strategies
    settings['live_trading_settings']['use_auto_optimizer_results'] = True
    
    # Speichere aktualisierte settings
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2)
    
    print("\n" + "="*60)
    print("✅ SETTINGS.JSON ERFOLGREICH AKTUALISIERT")
    print("="*60)
    print(f"Alte Anzahl Strategien: {old_count}")
    print(f"Neue Anzahl Strategien: {len(optimal_strategies)}")
    print("\nAktive Strategien:")
    for strat in optimal_strategies:
        print(f"  ✔ {strat['symbol']} {strat['timeframe']}")
    print("="*60)
    
    return True


def main():
    """
    Hauptfunktion - erwartet Config-Dateinamen als Argumente.
    """
    if len(sys.argv) < 2:
        print("❌ Fehler: Keine Config-Dateien angegeben.")
        print("Usage: python update_settings_from_optimizer.py config1.json config2.json ...")
        sys.exit(1)
    
    # Hole Config-Dateinamen aus Argumenten
    optimal_configs = sys.argv[1:]
    
    print("\n" + "="*60)
    print("AKTUALISIERE SETTINGS.JSON MIT OPTIMALEN STRATEGIEN")
    print("="*60)
    print(f"Anzahl optimale Strategien: {len(optimal_configs)}")
    for config in optimal_configs:
        print(f"  - {config}")
    
    # Finde settings.json (im Projekt-Root)
    script_dir = Path(__file__).parent
    settings_path = script_dir / 'settings.json'
    
    if not settings_path.exists():
        print(f"❌ Konnte settings.json nicht finden: {settings_path}")
        sys.exit(1)
    
    # Aktualisiere settings
    success = update_settings_with_optimal_strategies(optimal_configs, str(settings_path))
    
    if success:
        print("\n💡 HINWEIS: Du kannst die Änderungen rückgängig machen mit:")
        print(f"   cp {settings_path}.backup {settings_path}")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
