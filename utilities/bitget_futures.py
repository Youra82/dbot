# utilities/bitget_futures.py

import ccxt
import pandas as pd
from datetime import datetime, timezone

class BitgetFutures():
    def __init__(self):
        """Initialisiert eine öffentliche Verbindung zu Bitget ohne API-Keys."""
        try:
            self.session = ccxt.bitget({
                'options': {'defaultType': 'future'}
            })
            self.session.load_markets()
        except Exception as e:
            raise Exception(f"Fehler bei der Verbindung zu ccxt.bitget: {e}")

    def fetch_historical_ohlcv(self, symbol: str, timeframe: str, start_date_str: str, end_date_str: str) -> pd.DataFrame:
        """Lädt historische Kerzendaten für einen bestimmten Zeitraum herunter."""
        start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
        
        all_ohlcv = []
        limit = 1000 # Bitget's Limit pro Anfrage

        while start_ts < end_ts:
            try:
                ohlcv = self.session.fetch_ohlcv(symbol, timeframe, since=start_ts, limit=limit)
                if not ohlcv:
                    break
                all_ohlcv.extend(ohlcv)
                last_timestamp = ohlcv[-1][0]
                start_ts = last_timestamp + (self.session.parse_timeframe(timeframe) * 1000)
            except Exception as e:
                raise Exception(f"Fehler beim Abrufen der OHLCV-Daten für {symbol}: {e}")
        
        if not all_ohlcv:
            return pd.DataFrame()

        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        
        # Duplikate entfernen und nach Index sortieren
        df = df[~df.index.duplicated(keep='first')]
        df.sort_index(inplace=True)
        
        return df
