# /root/dbot/src/dbot/strategy/trade_logic.py
import pandas as pd
import numpy as np

def get_physics_signal(processed_data: pd.DataFrame, current_candle: pd.Series, params: dict, market_bias=None):
    """
    Physik-inspirierte Trading-Logik mit 3 Haupt-Setups:
    
    1. VWAP + Energie-Setup
       - Preis weit vom VWAP entfernt
       - Momentum flacht ab
       - Volumen-Spike am Extrem
       - Mean-Reversion zum VWAP
    
    2. Impuls → Pullback → Fortsetzung
       - Starker Impuls (große Kerzen + Volumen)
       - Pullback 38-50% des Impulses
       - Momentum dreht wieder in Impuls-Richtung
       - Einstieg bei Bestätigung
    
    3. Volatilitäts-Expansion (Phasenübergang)
       - Mehrtägige enge Range (ATR extrem niedrig)
       - Plötzlicher Range-Bruch mit Volumen
       - Target: 2-3× Range-Höhe
    
    MTF-Filter: Die übergeordnete Timeframe muss aligned sein (1D für Richtung)
    """
    
    # Sicherheitscheck
    if processed_data is None or processed_data.empty or len(processed_data) < 60:
        return None, None
    
    # Parameter laden
    strategy_params = params.get('strategy', {})
    enable_vwap_setup = strategy_params.get('enable_vwap_setup', True)
    enable_impulse_pullback = strategy_params.get('enable_impulse_pullback', True)
    enable_volatility_expansion = strategy_params.get('enable_volatility_expansion', True)
    
    # Mindestabstand vom VWAP für Mean-Reversion (in %)
    vwap_mean_reversion_threshold = strategy_params.get('vwap_mean_reversion_threshold', 2.0)
    
    # Minimum Momentum-Schwelle
    momentum_threshold = strategy_params.get('momentum_threshold', 0.5)
    
    # Wir brauchen die letzten beiden abgeschlossenen Zeilen
    if len(processed_data) < 3:
        return None, None
    
    last_row = processed_data.iloc[-1]
    prev_row = processed_data.iloc[-2]
    
    # Aktuelle Werte
    close = last_row['close']
    high = last_row['high']
    low = last_row['low']
    vwap = last_row.get('vwap')
    atr = last_row.get('atr')
    momentum = last_row.get('momentum')
    momentum_accel = last_row.get('momentum_acceleration')
    volume_ratio = last_row.get('volume_ratio')
    has_energy = last_row.get('has_energy', False)
    regime = last_row.get('regime', 'UNKNOWN')
    vwap_distance_pct = last_row.get('vwap_distance_pct')
    ema_fast = last_row.get('ema_fast')
    ema_slow = last_row.get('ema_slow')
    
    # Vorherige Werte
    prev_momentum = prev_row.get('momentum')
    prev_momentum_accel = prev_row.get('momentum_acceleration')
    
    # --- Prüfung auf Gültigkeit der Indikatoren ---
    required_fields = ['vwap', 'atr', 'momentum', 'volume_ratio', 'regime', 'ema_fast', 'ema_slow']
    if any(pd.isna(last_row.get(field)) for field in required_fields):
        return None, None
    
    signal_side = None
    signal_price = close
    
    # ============================================================
    # SETUP 1: VWAP + ENERGIE (Mean-Reversion)
    # ============================================================
    if enable_vwap_setup and has_energy:
        # Preis ist weit über VWAP, Momentum flacht ab → SHORT
        if (vwap_distance_pct > vwap_mean_reversion_threshold and 
            momentum < prev_momentum and 
            momentum_accel < 0 and
            volume_ratio > 1.5):  # Starkes Volumen am Extrem
            
            # Nur wenn nicht im starken Aufwärtstrend
            if regime != 'TREND' or ema_fast <= ema_slow:
                return "sell", signal_price
        
        # Preis ist weit unter VWAP, Momentum flacht ab → LONG
        elif (vwap_distance_pct < -vwap_mean_reversion_threshold and 
              momentum > prev_momentum and 
              momentum_accel > 0 and
              volume_ratio > 1.5):
            
            # Nur wenn nicht im starken Abwärtstrend
            if regime != 'TREND' or ema_fast >= ema_slow:
                return "buy", signal_price
    
    # ============================================================
    # SETUP 2: IMPULS → PULLBACK → FORTSETZUNG
    # ============================================================
    if enable_impulse_pullback:
        # Prüfe ob Impuls-Pullback-Setup erkannt wurde (aus physics_engine)
        impulse_pullback_flag = last_row.get('impulse_pullback_setup', False)
        
        if impulse_pullback_flag:
            # Bullisches Setup
            if ema_fast > ema_slow and momentum > momentum_threshold:
                # Zusätzliche Bestätigung: Preis schließt über EMA-Fast
                if close > ema_fast:
                    return "buy", signal_price
            
            # Bearisches Setup
            elif ema_fast < ema_slow and momentum < -momentum_threshold:
                # Preis schließt unter EMA-Fast
                if close < ema_fast:
                    return "sell", signal_price
    
    # ============================================================
    # SETUP 3: VOLATILITÄTS-EXPANSION
    # ============================================================
    if enable_volatility_expansion:
        # Prüfe ob Volatilitäts-Expansion erkannt wurde
        vol_expansion_flag = last_row.get('volatility_expansion_setup', False)
        
        if vol_expansion_flag:
            # Richtung basierend auf Breakout-Richtung
            if close > prev_row['high']:  # Upside Breakout
                if ema_fast >= ema_slow:  # Aligned mit Trend
                    return "buy", signal_price
            
            elif close < prev_row['low']:  # Downside Breakout
                if ema_fast <= ema_slow:
                    return "sell", signal_price
    
    # ============================================================
    # MTF-FILTER (Übergeordnete Timeframe)
    # ============================================================
    # Wenn market_bias gesetzt ist (von höherer TF), nur in diese Richtung traden
    if market_bias and signal_side:
        if market_bias == "bullish" and signal_side == "sell":
            return None, None
        elif market_bias == "bearish" and signal_side == "buy":
            return None, None
    
    # Kein Signal gefunden
    return signal_side, signal_price


def get_stop_loss_take_profit(df: pd.DataFrame, signal_side: str, signal_price: float, params: dict):
    """
    Berechnet Stop-Loss und Take-Profit basierend auf ATR (Physik-Ansatz: Energie-Zonen)
    
    Stop-Loss: 1.2 × ATR unter/über Entry
    Take-Profit: 1.8-2.5 × ATR in Profit-Richtung
    
    Bei Volatilitäts-Expansion: Größere Targets (2-3× Range)
    """
    if df is None or df.empty:
        return None, None
    
    last_row = df.iloc[-1]
    atr = last_row.get('atr')
    
    if pd.isna(atr) or atr <= 0:
        return None, None
    
    strategy_params = params.get('strategy', {})
    sl_atr_multiplier = strategy_params.get('sl_atr_multiplier', 1.2)
    tp_atr_multiplier = strategy_params.get('tp_atr_multiplier', 1.8)
    
    # Größere Targets bei Volatilitäts-Expansion
    if last_row.get('volatility_expansion_setup', False):
        tp_atr_multiplier = strategy_params.get('tp_atr_multiplier_expansion', 2.5)
    
    if signal_side == "buy":
        stop_loss = signal_price - (atr * sl_atr_multiplier)
        take_profit = signal_price + (atr * tp_atr_multiplier)
    elif signal_side == "sell":
        stop_loss = signal_price + (atr * sl_atr_multiplier)
        take_profit = signal_price - (atr * tp_atr_multiplier)
    else:
        return None, None
    
    return stop_loss, take_profit


def should_close_position(df: pd.DataFrame, position_side: str, entry_price: float, params: dict):
    """
    Prüft ob eine Position geschlossen werden soll (Exit-Logik)
    
    Exit-Gründe:
    1. Regime-Wechsel (Trend → Range)
    2. Momentum-Umkehr (Beschleunigung dreht)
    3. VWAP-Kreuzung (bei Mean-Reversion Setups)
    4. Energie-Verlust (Volumen trocknet aus)
    """
    if df is None or df.empty or len(df) < 2:
        return False
    
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    
    close = last_row['close']
    regime = last_row.get('regime', 'UNKNOWN')
    momentum_accel = last_row.get('momentum_acceleration')
    prev_momentum_accel = prev_row.get('momentum_acceleration')
    vwap = last_row.get('vwap')
    has_energy = last_row.get('has_energy', True)
    
    strategy_params = params.get('strategy', {})
    exit_on_regime_change = strategy_params.get('exit_on_regime_change', True)
    exit_on_momentum_reversal = strategy_params.get('exit_on_momentum_reversal', True)
    exit_on_vwap_cross = strategy_params.get('exit_on_vwap_cross', False)
    exit_on_energy_loss = strategy_params.get('exit_on_energy_loss', True)
    
    # Exit-Grund 1: Regime-Wechsel zu RANGE
    if exit_on_regime_change and regime == 'RANGE':
        return True
    
    # Exit-Grund 2: Momentum-Umkehr (Beschleunigung wechselt Vorzeichen)
    if exit_on_momentum_reversal:
        if position_side == "buy" and momentum_accel < 0 < prev_momentum_accel:
            return True
        elif position_side == "sell" and momentum_accel > 0 > prev_momentum_accel:
            return True
    
    # Exit-Grund 3: VWAP-Kreuzung (für Mean-Reversion)
    if exit_on_vwap_cross and not pd.isna(vwap):
        if position_side == "buy" and close >= vwap and entry_price < vwap:
            return True
        elif position_side == "sell" and close <= vwap and entry_price > vwap:
            return True
    
    # Exit-Grund 4: Energie-Verlust
    if exit_on_energy_loss and not has_energy:
        # Nur aussteigen wenn wir im Profit sind
        if position_side == "buy" and close > entry_price:
            return True
        elif position_side == "sell" and close < entry_price:
            return True
    
    return False
