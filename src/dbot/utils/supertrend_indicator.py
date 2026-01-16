import pandas as pd
import numpy as np
import ta

class SuperTrendLocal:
    """
    SuperTrend Indicator implementation.
    Reference: https://www.tradingview.com/script/hlfVjS8F-SuperTrend/
    """
    def __init__(self, high: pd.Series, low: pd.Series, close: pd.Series, window: int = 10, multiplier: float = 3.0, fillna: bool = False):
        self._high = high
        self._low = low
        self._close = close
        self._window = window
        self._multiplier = multiplier
        self._fillna = fillna
        self._run()

    def _run(self):
        atr_indicator = pd.Series(ta.volatility.average_true_range(self._high, self._low, self._close, window=self._window, fillna=self._fillna))
        hl2 = (self._high + self._low) / 2
        basic_upper_band = hl2 + self._multiplier * atr_indicator
        basic_lower_band = hl2 - self._multiplier * atr_indicator
        final_upper_band = np.zeros(len(self._close))
        final_lower_band = np.zeros(len(self._close))
        supertrend_series = np.zeros(len(self._close))
        supertrend_direction = np.zeros(len(self._close))
        first_valid_idx = atr_indicator.first_valid_index()
        if first_valid_idx is None:
            self.supertrend = pd.Series(np.nan, index=self._close.index)
            self.supertrend_direction = pd.Series(np.nan, index=self._close.index)
            return
        first_i = self._close.index.get_loc(first_valid_idx)
        final_upper_band[first_i] = basic_upper_band.iloc[first_i]
        final_lower_band[first_i] = basic_lower_band.iloc[first_i]
        supertrend_series[first_i] = final_upper_band[first_i]
        supertrend_direction[first_i] = -1.0
        for i in range(first_i + 1, len(self._close)):
            if basic_upper_band.iloc[i] < final_upper_band[i-1] or self._close.iloc[i-1] > final_upper_band[i-1]:
                final_upper_band[i] = basic_upper_band.iloc[i]
            else:
                final_upper_band[i] = final_upper_band[i-1]
            if basic_lower_band.iloc[i] > final_lower_band[i-1] or self._close.iloc[i-1] < final_lower_band[i-1]:
                final_lower_band[i] = basic_lower_band.iloc[i]
            else:
                final_lower_band[i] = final_lower_band[i-1]
            if supertrend_series[i-1] == final_upper_band[i-1]:
                if self._close.iloc[i] <= final_upper_band[i]:
                    supertrend_series[i] = final_upper_band[i]
                    supertrend_direction[i] = -1.0
                else:
                    supertrend_series[i] = final_lower_band[i]
                    supertrend_direction[i] = 1.0
            elif supertrend_series[i-1] == final_lower_band[i-1]:
                if self._close.iloc[i] >= final_lower_band[i]:
                    supertrend_series[i] = final_lower_band[i]
                    supertrend_direction[i] = 1.0
                else:
                    supertrend_series[i] = final_upper_band[i]
                    supertrend_direction[i] = -1.0
            elif self._close.iloc[i] > supertrend_series[i-1]:
                 supertrend_series[i] = final_lower_band[i]
                 supertrend_direction[i] = 1.0
            else:
                 supertrend_series[i] = final_upper_band[i]
                 supertrend_direction[i] = -1.0
        self.supertrend = pd.Series(supertrend_series, index=self._close.index)
        self.supertrend_direction = pd.Series(supertrend_direction, index=self._close.index)

    def get_supertrend_direction(self) -> pd.Series:
        return self.supertrend_direction
