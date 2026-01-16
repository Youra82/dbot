# src/dbot/utils/telegram_notifier.py
"""
Telegram Notifications für DBot
"""
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram Bot für Trading Notifications"""
    
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Initialisiere Telegram Bot
        
        Args:
            bot_token: Telegram Bot Token
            chat_id: Telegram Chat ID
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)
        
        if not self.enabled:
            logger.warning("⚠️  Telegram Notifier deaktiviert (keine Credentials)")
    
    def send_message(self, message: str) -> bool:
        """Sende Telegram Nachricht"""
        if not self.enabled:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Telegram send_message Error: {e}")
            return False
    
    def send_trade_signal(self, symbol: str, signal_type: str, entry: float, 
                         sl: float, tp: float, leverage: int) -> bool:
        """Sende Trade Signal Notification"""
        emoji = "🟢" if signal_type == "LONG" else "🔴"
        
        message = f"""
{emoji} <b>DBot {signal_type} Signal</b>

📊 Symbol: {symbol}
💰 Entry: {entry:.2f}
🛑 Stop Loss: {sl:.2f}
🎯 Take Profit: {tp:.2f}
⚡ Leverage: {leverage}x

⏰ {self._get_timestamp()}
        """
        return self.send_message(message.strip())
    
    def send_trade_close(self, symbol: str, side: str, pnl: float, pnl_percent: float) -> bool:
        """Sende Trade Close Notification"""
        emoji = "✅" if pnl > 0 else "❌"
        
        message = f"""
{emoji} <b>Position geschlossen</b>

📊 Symbol: {symbol}
📍 Side: {side.upper()}
💵 PnL: {pnl:.2f} USDT ({pnl_percent:+.2f}%)

⏰ {self._get_timestamp()}
        """
        return self.send_message(message.strip())
    
    def send_error(self, error_message: str) -> bool:
        """Sende Error Notification"""
        message = f"""
⚠️ <b>DBot Error</b>

{error_message}

⏰ {self._get_timestamp()}
        """
        return self.send_message(message.strip())
    
    def _get_timestamp(self) -> str:
        """Hole aktuellen Zeitstempel"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
