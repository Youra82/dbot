# src/dbot/utils/exchange.py
"""
Exchange Wrapper für CCXT - speziell für DBot
"""
import ccxt
import time
import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


class Exchange:
    """
    Exchange Wrapper für Bitget Futures Trading
    Optimiert für High-Frequency Scalping
    """
    
    SUPPORTED_TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d']
    
    def __init__(self, exchange_id: str = 'bitget', api_key: str = '', 
                 api_secret: str = '', password: str = ''):
        """Initialisiere Exchange Connection"""
        self.exchange_id = exchange_id
        
        try:
            self.exchange = getattr(ccxt, exchange_id)({
                'apiKey': api_key,
                'secret': api_secret,
                'password': password,
                'options': {
                    'defaultType': 'swap',
                },
                'enableRateLimit': True,
                'rateLimit': 100,  # 100ms between requests
            })
            
            # Load markets
            self.markets = self._with_retry(self.exchange.load_markets, max_retries=3)
            logger.info(f"✅ {exchange_id.upper()} Exchange erfolgreich initialisiert")
            
        except Exception as e:
            logger.error(f"❌ Exchange Initialisierung fehlgeschlagen: {e}")
            raise
    
    def _with_retry(self, func, *args, max_retries: int = 5, base_sleep: float = 0.5, **kwargs):
        """Retry logic mit exponential backoff"""
        attempt = 0
        while attempt < max_retries:
            try:
                return func(*args, **kwargs)
            except (ccxt.DDoSProtection, ccxt.RateLimitExceeded) as e:
                attempt += 1
                if attempt >= max_retries:
                    raise
                sleep_time = base_sleep * (2 ** (attempt - 1))
                logger.warning(f"⚠️  Rate limit hit (attempt {attempt}/{max_retries}). Retry in {sleep_time:.1f}s")
                time.sleep(sleep_time)
            except Exception as e:
                logger.error(f"❌ Fehler in API Call: {e}")
                raise
    
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> List:
        """Hole OHLCV Daten"""
        try:
            if timeframe not in self.SUPPORTED_TIMEFRAMES:
                raise ValueError(f"Timeframe {timeframe} nicht unterstützt")
            
            effective_limit = min(limit, 1000)
            data = self._with_retry(
                self.exchange.fetch_ohlcv,
                symbol,
                timeframe,
                limit=effective_limit
            )
            return data if data else []
            
        except Exception as e:
            logger.error(f"❌ fetch_ohlcv Error: {e}")
            return []
    
    def fetch_ticker(self, symbol: str) -> Optional[Dict]:
        """Hole aktuellen Ticker"""
        try:
            return self._with_retry(self.exchange.fetch_ticker, symbol)
        except Exception as e:
            logger.error(f"❌ fetch_ticker Error: {e}")
            return None
    
    def get_balance(self, currency: str = 'USDT') -> float:
        """Hole verfügbares Guthaben"""
        try:
            balance = self._with_retry(self.exchange.fetch_balance)
            
            if currency in balance:
                if 'free' in balance[currency]:
                    return float(balance[currency]['free'])
                elif 'available' in balance[currency]:
                    return float(balance[currency]['available'])
                elif 'total' in balance[currency]:
                    return float(balance[currency]['total'])
            
            return 0.0
            
        except Exception as e:
            logger.error(f"❌ get_balance Error: {e}")
            return 0.0
    
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Setze Leverage für Symbol"""
        try:
            self._with_retry(self.exchange.set_leverage, leverage, symbol)
            logger.info(f"✅ Leverage für {symbol} auf {leverage}x gesetzt")
            return True
        except Exception as e:
            if 'not changed' in str(e).lower():
                return True
            logger.warning(f"⚠️  set_leverage Warning: {e}")
            return False
    
    def set_margin_mode(self, symbol: str, mode: str = 'isolated') -> bool:
        """Setze Margin Mode"""
        try:
            self._with_retry(self.exchange.set_margin_mode, mode, symbol)
            logger.info(f"✅ Margin Mode für {symbol} auf {mode} gesetzt")
            return True
        except Exception as e:
            if 'same' in str(e).lower():
                return True
            logger.warning(f"⚠️  set_margin_mode Warning: {e}")
            return False
    
    def create_market_order(self, symbol: str, side: str, amount: float, 
                           reduce_only: bool = False) -> Optional[Dict]:
        """
        Erstelle Market Order
        
        Args:
            symbol: Trading Pair
            side: 'buy' oder 'sell'
            amount: Order Größe
            reduce_only: Nur zum Schließen von Positionen
        """
        try:
            # Round amount to precision
            rounded_amount = float(self.exchange.amount_to_precision(symbol, amount))
            
            params = {}
            if reduce_only:
                params['reduceOnly'] = True
            
            order = self._with_retry(
                self.exchange.create_order,
                symbol,
                'market',
                side,
                rounded_amount,
                params=params
            )
            
            logger.info(f"✅ Market Order: {side.upper()} {rounded_amount} {symbol}")
            return order
            
        except Exception as e:
            logger.error(f"❌ create_market_order Error: {e}")
            return None
    
    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """Hole offene Positionen"""
        try:
            if symbol:
                positions = self._with_retry(self.exchange.fetch_positions, [symbol])
            else:
                positions = self._with_retry(self.exchange.fetch_positions)
            
            # Filter nur offene Positionen
            open_positions = [
                p for p in positions 
                if p.get('contracts', 0.0) > 0.0 or abs(p.get('contractSize', 0.0)) > 0.0
            ]
            
            return open_positions
            
        except Exception as e:
            logger.error(f"❌ get_open_positions Error: {e}")
            return []
    
    def cancel_all_orders(self, symbol: str) -> bool:
        """Storniere alle offenen Orders"""
        try:
            self._with_retry(self.exchange.cancel_all_orders, symbol)
            logger.info(f"✅ Alle Orders für {symbol} storniert")
            return True
        except Exception as e:
            logger.warning(f"⚠️  cancel_all_orders Warning: {e}")
            return False
    
    def place_stop_loss_order(self, symbol: str, side: str, amount: float, 
                             trigger_price: float, reduce_only: bool = True) -> Optional[Dict]:
        """
        Erstelle Stop Loss Order auf Bitget
        
        Args:
            symbol: Trading Pair
            side: 'buy' oder 'sell'
            amount: Order Größe
            trigger_price: Trigger Price (SL Level)
            reduce_only: Nur zum Schließen von Positionen
        """
        try:
            rounded_price = float(self.exchange.price_to_precision(symbol, trigger_price))
            rounded_amount = float(self.exchange.amount_to_precision(symbol, amount))
            
            params = {
                'triggerPrice': rounded_price,
                'stopPrice': rounded_price,
            }
            
            if reduce_only:
                params['reduceOnly'] = True
            
            order = self._with_retry(
                self.exchange.create_order,
                symbol,
                'market',
                side,
                rounded_amount,
                None,
                params=params
            )
            
            logger.info(f"✅ Stop Loss Order erstellt: {side.upper()} {rounded_amount} @ {rounded_price}")
            return order
            
        except Exception as e:
            logger.error(f"❌ place_stop_loss_order Error: {e}")
            return None
    
    def place_trailing_stop_order(self, symbol: str, side: str, amount: float,
                                 callback_rate: float, reduce_only: bool = True) -> Optional[Dict]:
        """
        Erstelle Trailing Stop Order auf Bitget (nativer Exchange Trailing)
        
        Args:
            symbol: Trading Pair
            side: 'buy' oder 'sell'
            amount: Order Größe
            callback_rate: Callback Rate (z.B. 0.5 für 0.5% Trailing)
            reduce_only: Nur zum Schließen von Positionen
        """
        try:
            rounded_amount = float(self.exchange.amount_to_precision(symbol, amount))
            
            params = {
                'stopPrice': callback_rate,  # Bitget nutzt callback_rate für Trailing
                'trailingStopRate': callback_rate,  # Alternative Bezeichnung
            }
            
            if reduce_only:
                params['reduceOnly'] = True
            
            # Bitget Trailing Stop Orders
            order = self._with_retry(
                self.exchange.create_order,
                symbol,
                'market',
                side,
                rounded_amount,
                None,
                params=params
            )
            
            logger.info(f"✅ Trailing Stop Order erstellt: {side.upper()} {rounded_amount} @ {callback_rate*100:.2f}% Trail")
            return order
            
        except Exception as e:
            logger.error(f"❌ place_trailing_stop_order Error: {e}")
            return None
    
    def fetch_open_trigger_orders(self, symbol: str) -> List[Dict]:
        """Hole alle offenen Trigger/Stop Orders"""
        try:
            orders = self._with_retry(
                self.exchange.fetch_orders,
                symbol,
                params={'stop': True}
            )
            return orders if orders else []
        except Exception as e:
            logger.error(f"❌ fetch_open_trigger_orders Error: {e}")
            return []
    
    def cancel_trigger_order(self, order_id: str, symbol: str) -> bool:
        """Storniere eine Trigger Order"""
        try:
            self._with_retry(
                self.exchange.cancel_order,
                order_id,
                symbol,
                params={'stop': True}
            )
            logger.info(f"✅ Trigger Order {order_id} storniert")
            return True
        except Exception as e:
            logger.warning(f"⚠️  cancel_trigger_order Warning: {e}")
            return False
