# dbot.py (Version 2 - mit Automatisierungs-Funktion)

import os
import argparse
from datetime import datetime, timedelta
from utilities.bitget_futures import BitgetFutures

DOWNLOAD_DIR = 'historical_data_download'

def get_validated_date(prompt: str) -> str:
    """Fragt den Benutzer nach einem Datum und validiert das JJJJ-MM-TT Format."""
    while True:
        date_str = input(prompt).strip()
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            return date_str
        except ValueError:
            print("! Ungültiges Datumsformat. Bitte das Format JJJJ-MM-TT verwenden.")

def get_validated_input(prompt: str) -> str:
    """Fragt den Benutzer nach einer Eingabe und stellt sicher, dass sie nicht leer ist."""
    while True:
        user_input = input(prompt).strip()
        if user_input:
            return user_input
        print("! Eingabe darf nicht leer sein. Bitte erneut versuchen.")

def run_download(start_date, end_date, timeframes, symbols):
    """Die Kernlogik des Downloads, jetzt in einer eigenen Funktion."""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print(f"Daten werden gespeichert in: ./{DOWNLOAD_DIR}/\n")
    
    try:
        bitget = BitgetFutures()
        print("\nVerbindung zu Bitget hergestellt...")
    except Exception as e:
        print(f"Fehler bei der Initialisierung der Bitget-Verbindung: {e}")
        return

    print("\nStarte den Download...\n" + "="*40)
    
    for symbol_short in symbols:
        symbol = f"{symbol_short.upper()}/USDT:USDT"
        for timeframe in timeframes:
            print(f"-> Verarbeite {symbol} im Zeitfenster {timeframe}...")
            try:
                data_df = bitget.fetch_historical_ohlcv(symbol, timeframe, start_date, end_date)
                if data_df is None or data_df.empty:
                    print(f"  --> Keine Daten für {symbol} ({timeframe}) gefunden. Überspringe.")
                    continue

                symbol_path_name = symbol.split('/')[0]
                output_dir = os.path.join(DOWNLOAD_DIR, symbol_path_name)
                os.makedirs(output_dir, exist_ok=True)
                output_file = os.path.join(output_dir, f"{timeframe}.csv")
                data_df.to_csv(output_file)
                print(f"  --> ERFOLG: {len(data_df)} Kerzen gespeichert in: {output_file}")
            except Exception as e:
                print(f"  --> FEHLER bei {symbol} ({timeframe}): {e}")
    
    print("="*40 + "\nAlle Downloads abgeschlossen.\n")

def main():
    """Steuert, ob das Skript interaktiv oder automatisiert läuft."""
    parser = argparse.ArgumentParser(description="Lade historische Kerzendaten von Bitget herunter.")
    parser.add_argument('--start', help="Startdatum im Format JJJJ-MM-TT")
    parser.add_argument('--end', help="Enddatum im Format JJJJ-MM-TT")
    parser.add_argument('--timeframes', help="Zeitfenster, getrennt durch Leerzeichen (z.B. '1h 4h')")
    parser.add_argument('--symbols', help="Handelspaare, getrennt durch Leerzeichen (z.B. 'BTC ETH')")
    parser.add_argument('--days', type=int, help="Anzahl der letzten Tage, die heruntergeladen werden sollen (überschreibt --start und --end)")
    
    args = parser.parse_args()

    if args.days and args.timeframes and args.symbols:
        # Wenn --days angegeben ist, berechne Start- und Enddatum automatisch
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
        timeframes = args.timeframes.split()
        symbols = args.symbols.split()
        run_download(start_date, end_date, timeframes, symbols)

    elif args.start and args.end and args.timeframes and args.symbols:
        # Wenn alle Argumente für den Automatikmodus da sind
        timeframes = args.timeframes.split()
        symbols = args.symbols.split()
        run_download(args.start, args.end, timeframes, symbols)
    else:
        # Interaktiver Modus
        print("\n--- Simple Bitget Historical Data Downloader (Interaktiver Modus) ---")
        start_date = get_validated_date("Startdatum eingeben (JJJJ-MM-TT): ")
        end_date = get_validated_date("Enddatum eingeben (JJJJ-MM-TT): ")
        timeframes_input = get_validated_input("Zeitfenster eingeben (z.B. '1h 4h'): ")
        symbols_input = get_validated_input("Handelspaare eingeben (z.B. 'BTC ETH'): ")
        run_download(start_date, end_date, timeframes_input.split(), symbols_input.split())

if __name__ == "__main__":
    main()
