# /root/dbot/src/dbot/strategy/physics_engine.py
import pandas as pd
import numpy as np
import ta

class PhysicsEngine:
    """
    Physik-inspiriertes Trading-Framework basierend auf:
    - Signal vs. Rauschen (Filter, VWAP)
    - Momentum & Ableitungen (Geschwindigkeit/Beschleunigung)
    - Trägheit (Trends setzen sich fort)
    - Energie & Dissipation (Volumen = Energie)
    - Grenzflächen & Barrieren (VWAP, Support/Resistance)
    - Regime-Erkennung (Trend vs. Range)
    """
    def __init__(self, settings: dict):
        # ATR-Einstellungen
        self.atr_period = settings.get('atr_period', 14)
        self.atr_multiplier_trend = settings.get('atr_multiplier_trend', 1.5)
        
        # Momentum-Einstellungen
        self.momentum_period = settings.get('momentum_period', 10)
        self.momentum_sma_period = settings.get('momentum_sma_period', 3)
        
        # Volumen-Filter (Energie)
        self.volume_ma_period = settings.get('volume_ma_period', 20)
        self.volume_threshold = settings.get('volume_threshold', 1.2)  # 120% vom Durchschnitt
        
        # Regime-Erkennung
        self.regime_atr_threshold = settings.get('regime_atr_threshold', 0.02)  # 2% für Trend
        self.ema_fast = settings.get('ema_fast', 20)
        self.ema_slow = settings.get('ema_slow', 50)
        
        # Range-Erkennung
        self.range_lookback = settings.get('range_lookback', 20)
        self.range_overlap_threshold = settings.get('range_overlap_threshold', 0.7)
    
    def process_dataframe(self, df: pd.DataFrame):
        """
        Fügt alle Physik-Indikatoren zum DataFrame hinzu
        """
        if df.empty or len(df) < max(self.ema_slow, self.volume_ma_period, self.range_lookback) + 5:
            return df
        
        df = df.copy()
        
        # ========== VWAP (Gleichgewichtszustand) ==========
        df['vwap'] = self._calculate_vwap(df)
        
        # ========== ATR (Volatilität/Energie) ==========
        atr_indicator = ta.volatility.AverageTrueRange(
            high=df['high'], 
            low=df['low'], 
            close=df['close'], 
            window=self.atr_period
        )
        df['atr'] = atr_indicator.average_true_range()
        df['atr_pct'] = df['atr'] / df['close']  # Normalisiert
        
        # ========== Momentum (1. Ableitung = Geschwindigkeit) ==========
        df['momentum'] = df['close'].pct_change(periods=self.momentum_period) * 100
        df['momentum_sma'] = df['momentum'].rolling(window=self.momentum_sma_period).mean()
        
        # ========== Momentum-Änderung (2. Ableitung = Beschleunigung) ==========
        df['momentum_acceleration'] = df['momentum'].diff()
        
        # ========== Volumen-Energie-Filter ==========
        df['volume_ma'] = df['volume'].rolling(window=self.volume_ma_period).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        df['has_energy'] = df['volume_ratio'] >= self.volume_threshold
        
        # ========== EMA für Trend-Richtung ==========
        df['ema_fast'] = ta.trend.EMAIndicator(df['close'], window=self.ema_fast).ema_indicator()
        df['ema_slow'] = ta.trend.EMAIndicator(df['close'], window=self.ema_slow).ema_indicator()
        
        # ========== Regime-Klassifikation ==========
        df = self._classify_regime(df)
        
        # ========== Barrieren (VWAP-Distanz) ==========
        df['vwap_distance_pct'] = ((df['close'] - df['vwap']) / df['vwap']) * 100
        
        # ========== Impuls-Detektion (große Kerzen) ==========
        df['candle_range'] = df['high'] - df['low']
        df['candle_range_ma'] = df['candle_range'].rolling(window=20).mean()
        df['is_impulse'] = df['candle_range'] > (df['candle_range_ma'] * 1.5)
        
        return df
    
    def _calculate_vwap(self, df: pd.DataFrame):
        """
        VWAP = Gleichgewichtspreis (Volume Weighted Average Price)
        Resettet am Start jedes Tages (für Intraday) oder kontinuierlich für längere TFs
        """
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        
        # Für Intraday (15m, 1h): Reset bei neuem Tag
        # Für 4h+: Kontinuierlich über Zeitfenster
        if 'timestamp' in df.columns:
            df_with_date = df.copy()
            df_with_date['date'] = pd.to_datetime(df_with_date['timestamp']).dt.date
            
            # Gruppierte VWAP-Berechnung pro Tag
            df_with_date['tp_volume'] = typical_price * df['volume']
            df_with_date['vwap'] = (
                df_with_date.groupby('date')['tp_volume'].cumsum() / 
                df_with_date.groupby('date')['volume'].cumsum()
            )
            return df_with_date['vwap']
        else:
            # Einfache kumulative VWAP
            return (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
    
    def _classify_regime(self, df: pd.DataFrame):
        """
        Regime-Klassifikation:
        - TREND: ATR steigend, EMA-Alignment, gerichtete Bewegung
        - RANGE: ATR fallend, Preis überlappend, keine klare Richtung
        - VOLATILE: ATR extrem hoch, chaotisch
        """
        df['regime'] = 'UNKNOWN'
        
        # ATR-Trend (steigende Energie = Trend, fallende = Range)
        df['atr_sma'] = df['atr'].rolling(window=10).mean()
        df['atr_rising'] = df['atr'] > df['atr_sma'].shift(1)
        
        # EMA-Alignment (Trend-Indikator)
        df['ema_aligned_bull'] = (df['ema_fast'] > df['ema_slow']) & (df['close'] > df['ema_fast'])
        df['ema_aligned_bear'] = (df['ema_fast'] < df['ema_slow']) & (df['close'] < df['ema_fast'])
        
        # Range-Detektion: Überlappende Kerzen
        df['high_max'] = df['high'].rolling(window=self.range_lookback).max()
        df['low_min'] = df['low'].rolling(window=self.range_lookback).min()
        df['range_height'] = df['high_max'] - df['low_min']
        df['price_in_range'] = (
            (df['close'] < df['high_max'] * 1.01) & 
            (df['close'] > df['low_min'] * 0.99)
        )
        
        # Regime-Zuweisung
        for i in range(len(df)):
            if pd.isna(df.iloc[i]['atr_pct']):
                continue
            
            atr_pct = df.iloc[i]['atr_pct']
            atr_rising = df.iloc[i]['atr_rising']
            ema_bull = df.iloc[i]['ema_aligned_bull']
            ema_bear = df.iloc[i]['ema_aligned_bear']
            in_range = df.iloc[i]['price_in_range']
            
            # TREND-Regime
            if atr_pct > self.regime_atr_threshold and atr_rising and (ema_bull or ema_bear):
                df.at[df.index[i], 'regime'] = 'TREND'
            # RANGE-Regime
            elif atr_pct < self.regime_atr_threshold and in_range:
                df.at[df.index[i], 'regime'] = 'RANGE'
            # VOLATILE-Regime
            elif atr_pct > self.regime_atr_threshold * 2:
                df.at[df.index[i], 'regime'] = 'VOLATILE'
            else:
                df.at[df.index[i], 'regime'] = 'TRANSITION'
        
        return df
    
    def detect_impulse_pullback(self, df: pd.DataFrame, lookback: int = 10):
        """
        Erkennt Impuls → Pullback → Fortsetzungs-Muster
        
        Physik-Konzept: Trägheit
        - Starker Impuls (große Kerzen + Volumen)
        - Kurze Korrektur (Energie sammelt sich)
        - Pullback bleibt über 38-50% des Impulses
        - Fortsetzung mit erneutem Momentum
        """
        if len(df) < lookback + 5:
            return pd.Series([False] * len(df), index=df.index)
        
        signals = []
        
        for i in range(len(df)):
            if i < lookback + 2:
                signals.append(False)
                continue
            
            # Suche nach Impuls in den letzten lookback Kerzen
            recent = df.iloc[i-lookback:i]
            
            # Impuls-Kriterien
            has_impulse_candles = recent['is_impulse'].sum() >= 2
            had_high_volume = recent['volume_ratio'].max() > self.volume_threshold
            price_moved = abs(recent['close'].iloc[-1] - recent['close'].iloc[0]) / recent['close'].iloc[0] > 0.02
            
            # Aktueller Zustand: Pullback?
            current = df.iloc[i]
            impulse_high = recent['high'].max()
            impulse_low = recent['low'].min()
            impulse_range = impulse_high - impulse_low
            
            # Pullback in bullischem Kontext
            if price_moved and has_impulse_candles:
                if recent['close'].iloc[-1] > recent['close'].iloc[0]:  # Bullisch
                    # Pullback von 38-62% des Impulses
                    pullback_level = impulse_high - (impulse_range * 0.5)
                    if impulse_low <= current['close'] <= pullback_level:
                        # Momentum dreht wieder nach oben
                        if current['momentum_acceleration'] > 0:
                            signals.append(True)
                            continue
        
                # Bearischer Pullback
                else:
                    pullback_level = impulse_low + (impulse_range * 0.5)
                    if pullback_level <= current['close'] <= impulse_high:
                        if current['momentum_acceleration'] < 0:
                            signals.append(True)
                            continue
            
            signals.append(False)
        
        return pd.Series(signals, index=df.index, name='impulse_pullback_setup')
    
    def detect_volatility_expansion(self, df: pd.DataFrame, range_periods: int = 20):
        """
        Erkennt Volatilitäts-Expansion (Phasenübergang)
        
        Physik: Energieverlust → Instabilität → Explosion
        - Mehrtägige enge Range (ATR extrem niedrig)
        - Plötzlicher Range-Bruch mit Volumen
        - Target: 2-3× Range-Höhe
        """
        if len(df) < range_periods + 5:
            return pd.Series([False] * len(df), index=df.index)
        
        signals = []
        
        for i in range(len(df)):
            if i < range_periods + 2:
                signals.append(False)
                continue
            
            recent = df.iloc[i-range_periods:i]
            current = df.iloc[i]
            
            # Range-Kriterien
            atr_min = recent['atr_pct'].min()
            atr_current = current['atr_pct']
            range_height = recent['range_height'].iloc[-1]
            
            # ATR war extrem niedrig, jetzt plötzlich Expansion
            if atr_min < self.regime_atr_threshold * 0.5:  # Sehr enge Range
                # Breakout mit Volumen
                if (atr_current > atr_min * 2 and 
                    current['volume_ratio'] > self.volume_threshold and
                    current['is_impulse']):
                    signals.append(True)
                    continue
            
            signals.append(False)
        
        return pd.Series(signals, index=df.index, name='volatility_expansion_setup')
