# src/dbot/strategy/scalper_engine.py
"""
Aggressive Scalping Engine für DBot
Ultra-short timeframe Momentum Trading
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any
import time


class ScalperEngine:
    """
    High-Frequency Momentum Scalper Engine
    
    Strategie:
    - Erkennt schnelle Momentum-Breakouts
    - Nutzt EMA-Crossovers + RSI + Volume-Spikes
    - Ultra-short Timeframes (1m, 5m)
    - Schnelle Ein-/Ausstiege (TP 2-5%, SL 1%)
    - 5-10x Leverage für maximale Rendite
    """
    
    def __init__(self, exchange, symbol: str, timeframe: str, settings: dict, 
                 notifier=None, use_momentum_filter: bool = True):
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.settings = settings
        self.notifier = notifier
        self.use_momentum_filter = use_momentum_filter
        
        # Trading Parameters
        self.trading_params = settings['trading_parameters']
        self.strategy_config = settings['strategy_config']
        
        # Position Tracking
        self.current_position = None
        self.entry_price = None
        self.stop_loss = None
        self.take_profit = None
        self.position_id = None
        
        print(f"✅ ScalperEngine initialisiert für {symbol} {timeframe}")
        print(f"   Leverage: {self.trading_params['leverage']}x")
        print(f"   Risk per Trade: {self.trading_params['risk_per_trade_percent']}%")
        print(f"   TP: {self.trading_params['take_profit_percent']}% | SL: {self.trading_params['stop_loss_percent']}%")
    
    def execute_trading_cycle(self):
        """Hauptloop des Trading-Zyklus"""
        try:
            # 1. Hole aktuelle Marktdaten
            df = self.fetch_and_prepare_data()
            
            if df is None or len(df) < 50:
                print("⚠️  Nicht genug Daten vorhanden")
                return
            
            # 2. Berechne Indikatoren
            df = self.calculate_indicators(df)
            
            # 3. Prüfe offene Positionen
            open_positions = self.exchange.get_open_positions(self.symbol)
            
            if open_positions:
                # Position Management
                self.manage_position(df, open_positions[0])
            else:
                # Signal-Erkennung
                signal = self.get_trading_signal(df)
                
                if signal == "LONG":
                    self.open_long_position(df)
                elif signal == "SHORT":
                    self.open_short_position(df)
            
        except Exception as e:
            print(f"❌ Fehler in execute_trading_cycle: {e}")
            raise
    
    def fetch_and_prepare_data(self) -> Optional[pd.DataFrame]:
        """Hole OHLCV-Daten von der Exchange"""
        try:
            # Hole die letzten 100 Kerzen
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=100)
            
            if not ohlcv:
                return None
            
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            return df
            
        except Exception as e:
            print(f"❌ Fehler beim Datenabruf: {e}")
            return None
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Berechne technische Indikatoren"""
        
        # EMA Fast & Slow
        df['ema_fast'] = df['close'].ewm(span=self.strategy_config['ema_fast'], adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=self.strategy_config['ema_slow'], adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.strategy_config['rsi_period']).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.strategy_config['rsi_period']).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # ATR (Volatility)
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['atr'] = true_range.rolling(window=self.strategy_config['atr_period']).mean()
        
        # Volume MA
        df['volume_ma'] = df['volume'].rolling(window=self.strategy_config['volume_ma_period']).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # Momentum
        df['momentum'] = ((df['close'] - df['close'].shift(10)) / df['close'].shift(10)) * 100
        
        # Breakout Levels
        lookback = self.strategy_config['breakout_lookback']
        df['resistance'] = df['high'].rolling(window=lookback).max()
        df['support'] = df['low'].rolling(window=lookback).min()
        
        return df
    
    def get_trading_signal(self, df: pd.DataFrame) -> str:
        """
        Erkenne Trading-Signale
        
        LONG Signal:
        - EMA Fast > EMA Slow (Uptrend)
        - RSI > 50 (Momentum)
        - Preis bricht über Resistance
        - Volume-Spike (> 1.5x MA)
        - Optional: Momentum > Threshold
        
        SHORT Signal:
        - EMA Fast < EMA Slow (Downtrend)
        - RSI < 50 (Momentum)
        - Preis bricht unter Support
        - Volume-Spike (> 1.5x MA)
        """
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Check offene Positionen Limit
        open_positions = self.exchange.get_open_positions()
        if len(open_positions) >= self.trading_params['max_open_positions']:
            return "FLAT"
        
        # Volatility Filter
        min_volatility = latest['atr'] * self.trading_params['min_volatility_atr_multiplier']
        if latest['atr'] < min_volatility:
            return "FLAT"
        
        # Volume Filter
        if latest['volume_ratio'] < self.trading_params['volume_spike_multiplier']:
            return "FLAT"
        
        # LONG Signal
        long_conditions = [
            latest['ema_fast'] > latest['ema_slow'],  # Uptrend
            latest['rsi'] > 50 and latest['rsi'] < self.strategy_config['rsi_overbought'],  # Momentum
            latest['close'] > prev['resistance'],  # Breakout
            latest['volume_ratio'] > self.trading_params['volume_spike_multiplier']  # Volume
        ]
        
        if self.use_momentum_filter:
            long_conditions.append(latest['momentum'] > self.trading_params['momentum_threshold'])
        
        if all(long_conditions):
            print(f"🟢 LONG Signal erkannt!")
            print(f"   EMA Fast: {latest['ema_fast']:.2f} | EMA Slow: {latest['ema_slow']:.2f}")
            print(f"   RSI: {latest['rsi']:.2f}")
            print(f"   Price: {latest['close']:.2f} | Resistance: {prev['resistance']:.2f}")
            print(f"   Volume Ratio: {latest['volume_ratio']:.2f}x")
            return "LONG"
        
        # SHORT Signal
        short_conditions = [
            latest['ema_fast'] < latest['ema_slow'],  # Downtrend
            latest['rsi'] < 50 and latest['rsi'] > self.strategy_config['rsi_oversold'],  # Momentum
            latest['close'] < prev['support'],  # Breakdown
            latest['volume_ratio'] > self.trading_params['volume_spike_multiplier']  # Volume
        ]
        
        if self.use_momentum_filter:
            short_conditions.append(latest['momentum'] < -self.trading_params['momentum_threshold'])
        
        if all(short_conditions):
            print(f"🔴 SHORT Signal erkannt!")
            print(f"   EMA Fast: {latest['ema_fast']:.2f} | EMA Slow: {latest['ema_slow']:.2f}")
            print(f"   RSI: {latest['rsi']:.2f}")
            print(f"   Price: {latest['close']:.2f} | Support: {prev['support']:.2f}")
            print(f"   Volume Ratio: {latest['volume_ratio']:.2f}x")
            return "SHORT"
        
        return "FLAT"
    
    def open_long_position(self, df: pd.DataFrame):
        """Öffne LONG Position"""
        try:
            current_price = df.iloc[-1]['close']
            
            # Berechne Position Size
            balance = self.exchange.get_balance('USDT')
            risk_amount = balance * (self.trading_params['risk_per_trade_percent'] / 100)
            leverage = self.trading_params['leverage']
            
            # Position Size = Risk / SL Distance * Leverage
            sl_percent = self.trading_params['stop_loss_percent'] / 100
            position_value = (risk_amount / sl_percent) * leverage
            amount = position_value / current_price
            
            # Set Leverage
            self.exchange.set_leverage(self.symbol, leverage)
            
            # Open Position
            order = self.exchange.create_market_order(
                symbol=self.symbol,
                side='buy',
                amount=amount
            )
            
            if order:
                self.entry_price = current_price
                self.stop_loss = current_price * (1 - sl_percent)
                self.take_profit = current_price * (1 + self.trading_params['take_profit_percent'] / 100)
                self.current_position = 'LONG'
                
                print(f"✅ LONG Position eröffnet:")
                print(f"   Entry: {self.entry_price:.2f}")
                print(f"   Amount: {amount:.4f}")
                print(f"   SL: {self.stop_loss:.2f} (-{self.trading_params['stop_loss_percent']}%)")
                print(f"   TP: {self.take_profit:.2f} (+{self.trading_params['take_profit_percent']}%)")
                print(f"   Leverage: {leverage}x")
                
                if self.notifier:
                    self.notifier.send_trade_signal(
                        symbol=self.symbol,
                        signal_type="LONG",
                        entry=self.entry_price,
                        sl=self.stop_loss,
                        tp=self.take_profit,
                        leverage=leverage
                    )
        
        except Exception as e:
            print(f"❌ Fehler beim Öffnen der LONG Position: {e}")
    
    def open_short_position(self, df: pd.DataFrame):
        """Öffne SHORT Position"""
        try:
            current_price = df.iloc[-1]['close']
            
            # Berechne Position Size
            balance = self.exchange.get_balance('USDT')
            risk_amount = balance * (self.trading_params['risk_per_trade_percent'] / 100)
            leverage = self.trading_params['leverage']
            
            # Position Size = Risk / SL Distance * Leverage
            sl_percent = self.trading_params['stop_loss_percent'] / 100
            position_value = (risk_amount / sl_percent) * leverage
            amount = position_value / current_price
            
            # Set Leverage
            self.exchange.set_leverage(self.symbol, leverage)
            
            # Open Position
            order = self.exchange.create_market_order(
                symbol=self.symbol,
                side='sell',
                amount=amount
            )
            
            if order:
                self.entry_price = current_price
                self.stop_loss = current_price * (1 + sl_percent)
                self.take_profit = current_price * (1 - self.trading_params['take_profit_percent'] / 100)
                self.current_position = 'SHORT'
                
                print(f"✅ SHORT Position eröffnet:")
                print(f"   Entry: {self.entry_price:.2f}")
                print(f"   Amount: {amount:.4f}")
                print(f"   SL: {self.stop_loss:.2f} (+{self.trading_params['stop_loss_percent']}%)")
                print(f"   TP: {self.take_profit:.2f} (-{self.trading_params['take_profit_percent']}%)")
                print(f"   Leverage: {leverage}x")
                
                if self.notifier:
                    self.notifier.send_trade_signal(
                        symbol=self.symbol,
                        signal_type="SHORT",
                        entry=self.entry_price,
                        sl=self.stop_loss,
                        tp=self.take_profit,
                        leverage=leverage
                    )
        
        except Exception as e:
            print(f"❌ Fehler beim Öffnen der SHORT Position: {e}")
    
    def manage_position(self, df: pd.DataFrame, position: dict):
        """Manage offene Position (SL/TP/Trailing)"""
        try:
            current_price = df.iloc[-1]['close']
            side = position['side']
            unrealized_pnl_percent = position.get('percentage', 0)
            
            # Trailing Stop Logic
            activation_rr = self.trading_params['trailing_stop_activation_rr']
            trailing_distance = self.trading_params['trailing_stop_distance_percent'] / 100
            
            if side == 'long':
                # Check TP
                if current_price >= self.take_profit:
                    print(f"🎯 Take Profit erreicht! Schließe LONG Position")
                    self.close_position(position)
                    return
                
                # Check SL
                if current_price <= self.stop_loss:
                    print(f"🛑 Stop Loss erreicht! Schließe LONG Position")
                    self.close_position(position)
                    return
                
                # Trailing Stop
                if unrealized_pnl_percent >= (activation_rr * self.trading_params['stop_loss_percent']):
                    new_sl = current_price * (1 - trailing_distance)
                    if new_sl > self.stop_loss:
                        self.stop_loss = new_sl
                        print(f"📈 Trailing Stop aktiviert: Neuer SL = {self.stop_loss:.2f}")
            
            elif side == 'short':
                # Check TP
                if current_price <= self.take_profit:
                    print(f"🎯 Take Profit erreicht! Schließe SHORT Position")
                    self.close_position(position)
                    return
                
                # Check SL
                if current_price >= self.stop_loss:
                    print(f"🛑 Stop Loss erreicht! Schließe SHORT Position")
                    self.close_position(position)
                    return
                
                # Trailing Stop
                if unrealized_pnl_percent >= (activation_rr * self.trading_params['stop_loss_percent']):
                    new_sl = current_price * (1 + trailing_distance)
                    if new_sl < self.stop_loss:
                        self.stop_loss = new_sl
                        print(f"📉 Trailing Stop aktiviert: Neuer SL = {self.stop_loss:.2f}")
            
            # Status Update
            print(f"📊 Position: {side.upper()} | PnL: {unrealized_pnl_percent:.2f}% | Price: {current_price:.2f}")
        
        except Exception as e:
            print(f"❌ Fehler im Position Management: {e}")
    
    def close_position(self, position: dict):
        """Schließe Position"""
        try:
            side = 'sell' if position['side'] == 'long' else 'buy'
            amount = abs(position['contracts'])
            
            order = self.exchange.create_market_order(
                symbol=self.symbol,
                side=side,
                amount=amount,
                reduce_only=True
            )
            
            if order:
                pnl = position.get('unrealizedPnl', 0)
                pnl_percent = position.get('percentage', 0)
                
                print(f"✅ Position geschlossen:")
                print(f"   Side: {position['side'].upper()}")
                print(f"   PnL: {pnl:.2f} USDT ({pnl_percent:.2f}%)")
                
                if self.notifier:
                    self.notifier.send_trade_close(
                        symbol=self.symbol,
                        side=position['side'],
                        pnl=pnl,
                        pnl_percent=pnl_percent
                    )
                
                # Reset
                self.current_position = None
                self.entry_price = None
                self.stop_loss = None
                self.take_profit = None
        
        except Exception as e:
            print(f"❌ Fehler beim Schließen der Position: {e}")
