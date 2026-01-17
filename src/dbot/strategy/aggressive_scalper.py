"""
Aggressive Scalping Strategy für dbot
======================================
Hyper-aggressive Entry-Logik basierend auf:
- RSI Extremwerte (Überverkauft/Überkauft)
- EMA Kreuzung
- Volatility Expansion (ATR)
- Momentum (ROC)

Ziel: Maximale Trade-Häufigkeit für Scalping auf 1m/5m
"""

import pandas as pd
import numpy as np
import ta


def get_scalp_signal(df: pd.DataFrame, params: dict = None) -> tuple:
    """
    Aggressive Scalping Signal Generator
    
    Returns:
        (side, entry_price, confidence)
        side: 'buy', 'sell', or None
        entry_price: float (current close)
        confidence: float (0-1, für Position-Sizing)
    """
    if len(df) < 50:
        return None, None, 0.0
    
    df = df.copy()
    current = df.iloc[-1]
    close = current['close']
    
    # Default parameters
    rsi_period = params.get('rsi_period', 14) if params else 14
    rsi_oversold = params.get('rsi_oversold', 35) if params else 35
    rsi_overbought = params.get('rsi_overbought', 65) if params else 65
    ema_fast = params.get('ema_fast', 5) if params else 5
    ema_slow = params.get('ema_slow', 20) if params else 20
    
    # ===== INDIKATOR BERECHNUNG =====
    
    # 1. RSI
    rsi = ta.momentum.rsi(df['close'], window=rsi_period)
    current_rsi = rsi.iloc[-1]
    prev_rsi = rsi.iloc[-2] if len(rsi) > 1 else current_rsi
    
    # 2. EMA
    ema_fast_val = ta.trend.ema_indicator(df['close'], window=ema_fast)
    ema_slow_val = ta.trend.ema_indicator(df['close'], window=ema_slow)
    
    current_ema_fast = ema_fast_val.iloc[-1]
    current_ema_slow = ema_slow_val.iloc[-1]
    prev_ema_fast = ema_fast_val.iloc[-2] if len(ema_fast_val) > 1 else current_ema_fast
    prev_ema_slow = ema_slow_val.iloc[-2] if len(ema_slow_val) > 1 else current_ema_slow
    
    # 3. ATR (für Volatility)
    atr = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
    current_atr = atr.iloc[-1]
    atr_avg_50 = atr.rolling(50).mean().iloc[-1]
    atr_ratio = current_atr / (atr_avg_50 + 1e-6)
    
    # 4. ROC (Rate of Change) - Momentum
    roc = ta.momentum.roc(df['close'], window=5)
    current_roc = roc.iloc[-1]
    
    # 5. BBands für Extreme (nutze BollingerBands Klasse)
    bb_indicator = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
    bb_high = bb_indicator.bollinger_hband().iloc[-1]
    bb_low = bb_indicator.bollinger_lband().iloc[-1]
    bb_mid = bb_indicator.bollinger_mavg().iloc[-1]
    
    # ===== AGGRESSIVE BUY SIGNAL =====
    buy_signal = False
    buy_confidence = 0.0
    
    # Bedingung 1: RSI Oversold (unter 30, nicht unter 35)
    rsi_oversold_cross = (current_rsi <= 30) and (prev_rsi > 30)
    if rsi_oversold_cross:
        buy_signal = True
        buy_confidence += 0.4
    
    # Bedingung 2: EMA Fast über EMA Slow (Bullish Crossover)
    ema_bull_cross = (current_ema_fast > current_ema_slow) and (prev_ema_fast <= prev_ema_slow)
    if ema_bull_cross:
        buy_signal = True
        buy_confidence += 0.35
    
    # Bedingung 3: Positive Momentum (ROC > 0.2%)
    if current_roc > 0.2:  # > 0.2% ROC
        buy_confidence += 0.25
    
    # Bedingung 4: Price nahe BB Low (Recovery Signal)
    if close <= bb_low * 1.005:  # Sehr nah am Low Band
        buy_confidence += 0.15
    
    # Bedingung 5: RSI muss auch unter 50 sein (nicht nur Oversold)
    if current_rsi < 50:
        buy_confidence += 0.1
    
    # ===== AGGRESSIVE SELL SIGNAL =====
    sell_signal = False
    sell_confidence = 0.0
    
    # Bedingung 1: RSI Overbought (über 70, nicht über 65)
    rsi_overbought_cross = (current_rsi >= 70) and (prev_rsi < 70)
    if rsi_overbought_cross:
        sell_signal = True
        sell_confidence += 0.4
    
    # Bedingung 2: EMA Fast unter EMA Slow (Bearish Crossover)
    ema_bear_cross = (current_ema_fast < current_ema_slow) and (prev_ema_fast >= prev_ema_slow)
    if ema_bear_cross:
        sell_signal = True
        sell_confidence += 0.35
    
    # Bedingung 3: Negative Momentum (ROC < -0.2%)
    if current_roc < -0.2:  # < -0.2% ROC
        sell_confidence += 0.25
    
    # Bedingung 4: Price nahe BB High (Rejection Signal)
    if close >= bb_high * 0.995:  # Sehr nah am High Band
        sell_confidence += 0.15
    
    # Bedingung 5: RSI muss auch über 50 sein
    if current_rsi > 50:
        sell_confidence += 0.1
    
    # ===== SIGNAL PRIORITÄT =====
    
    # Nur ein Signal gleichzeitig
    if buy_signal and sell_signal:
        # Konfidenz-basierte Auswahl
        if buy_confidence > sell_confidence:
            return 'buy', close, min(buy_confidence, 1.0)
        else:
            return 'sell', close, min(sell_confidence, 1.0)
    
    # Mindestens 0.5 Konfidenz für Buy-Signal
    if buy_signal and buy_confidence >= 0.5:
        return 'buy', close, min(buy_confidence, 1.0)
    
    # Mindestens 0.5 Konfidenz für Sell-Signal
    if sell_signal and sell_confidence >= 0.5:
        return 'sell', close, min(sell_confidence, 1.0)
    
    # Kein Signal
    return None, None, 0.0


def calculate_sl_tp(entry_price: float, side: str, current_atr: float, 
                     params: dict = None) -> tuple:
    """
    Calculate Stop Loss und Take Profit für Scalping
    
    Returns:
        (stop_loss, take_profit)
    """
    if params is None:
        params = {}
    
    # Aggressive Scalping: kleine SL/TP
    sl_multiplier = params.get('sl_multiplier', 1.0)  # SL = ATR * 1.0
    tp_ratio = params.get('tp_ratio', 1.5)  # TP = SL * 1.5
    
    sl_distance = current_atr * sl_multiplier
    tp_distance = sl_distance * tp_ratio
    
    if side == 'buy':
        stop_loss = entry_price - sl_distance
        take_profit = entry_price + tp_distance
    else:  # sell
        stop_loss = entry_price + sl_distance
        take_profit = entry_price - tp_distance
    
    return stop_loss, take_profit
