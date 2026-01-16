import pandas as pd
import numpy as np
import tensorflow as tf
import joblib
import logging
import ta
import os

logger = logging.getLogger(__name__)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))


def create_ann_features(df):
    bollinger = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
    df['bb_width'] = bollinger.bollinger_wband()
    df['bb_pband'] = bollinger.bollinger_pband()
    df['bb_hband'] = bollinger.bollinger_hband()
    df['bb_lband'] = bollinger.bollinger_lband()
    
    if 'volume' in df.columns and df['volume'].sum() > 0:
        df['obv'] = ta.volume.on_balance_volume(close=df['close'], volume=df['volume'])
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        df['mfi'] = ta.volume.money_flow_index(df['high'], df['low'], df['close'], df['volume'], window=14)
        df['cmf'] = ta.volume.chaikin_money_flow(df['high'], df['low'], df['close'], df['volume'], window=20)
        df['vwap'] = ta.volume.volume_weighted_average_price(df['high'], df['low'], df['close'], df['volume'], window=14)
    else:
        df['obv'] = 0
        df['volume_sma'] = 0
        df['volume_ratio'] = 1
        df['mfi'] = 50
        df['cmf'] = 0
        df['vwap'] = df['close']
    
    df['rsi'] = ta.momentum.rsi(df['close'], window=14)
    macd = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9)
    df['macd_diff'] = macd.macd_diff()
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    atr_indicator = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14)
    df['atr'] = atr_indicator.average_true_range()
    df['atr_normalized'] = (df['atr'] / df['close']) * 100
    df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'], window=14)
    df['adx_pos'] = ta.trend.adx_pos(df['high'], df['low'], df['close'], window=14)
    df['adx_neg'] = ta.trend.adx_neg(df['high'], df['low'], df['close'], window=14)
    df['ema20'] = ta.trend.ema_indicator(df['close'], window=20)
    df['ema50'] = ta.trend.ema_indicator(df['close'], window=50)
    df['ema200'] = ta.trend.ema_indicator(df['close'], window=200)
    df['price_to_ema20'] = (df['close'] - df['ema20']) / df['ema20']
    df['price_to_ema50'] = (df['close'] - df['ema50']) / df['ema50']
    df['stoch_k'] = ta.momentum.stoch(df['high'], df['low'], df['close'], window=14, smooth_window=3)
    df['stoch_d'] = ta.momentum.stoch_signal(df['high'], df['low'], df['close'], window=14, smooth_window=3)
    df['williams_r'] = ta.momentum.williams_r(df['high'], df['low'], df['close'], lbp=14)
    df['roc'] = ta.momentum.roc(df['close'], window=12)
    df['cci'] = ta.trend.cci(df['high'], df['low'], df['close'], window=20)
    df['keltner_channel_hband'] = ta.volatility.keltner_channel_hband(df['high'], df['low'], df['close'], window=20)
    df['keltner_channel_lband'] = ta.volatility.keltner_channel_lband(df['high'], df['low'], df['close'], window=20)
    df['donchian_channel_hband'] = ta.volatility.donchian_channel_hband(df['high'], df['low'], df['close'], window=20)
    df['donchian_channel_lband'] = ta.volatility.donchian_channel_lband(df['high'], df['low'], df['close'], window=20)
    df['resistance'] = df['high'].rolling(window=20).max()
    df['support'] = df['low'].rolling(window=20).min()
    df['price_to_resistance'] = (df['resistance'] - df['close']) / df['close']
    df['price_to_support'] = (df['close'] - df['support']) / df['close']
    df['high_low_range'] = (df['high'] - df['low']) / df['close']
    df['close_to_high'] = (df['high'] - df['close']) / (df['high'] - df['low'] + 0.0001)
    df['close_to_low'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 0.0001)
    df['day_of_week'] = df.index.dayofweek
    df['hour_of_day'] = df.index.hour if hasattr(df.index, 'hour') else 0
    df['returns_lag1'] = df['close'].pct_change().shift(1)
    df['returns_lag2'] = df['close'].pct_change().shift(2)
    df['returns_lag3'] = df['close'].pct_change().shift(3)
    df['hist_volatility'] = df['close'].pct_change().rolling(window=20).std() * np.sqrt(252)
    return df


def prepare_data_for_ann(df, timeframe: str, verbose: bool = True):
    df_with_features = create_ann_features(df.copy())
    df_with_features.dropna(inplace=True)
    if df_with_features.empty:
        return pd.DataFrame(), pd.Series()

    if 'm' in timeframe:
        lookahead = 12
        volatility_multiplier = 2.5
    elif 'h' in timeframe:
        try:
            tf_num = int(timeframe.replace('h', ''))
            if tf_num == 1:
                lookahead = 8
                volatility_multiplier = 2.0
            elif tf_num <= 4:
                lookahead = 5
                volatility_multiplier = 1.75
            else:
                lookahead = 4
                volatility_multiplier = 1.75
        except ValueError:
            lookahead = 5
            volatility_multiplier = 1.75
    elif 'd' in timeframe:
        lookahead = 5
        volatility_multiplier = 1.5
    else:
        lookahead = 5
        volatility_multiplier = 2.0

    avg_atr_pct = df_with_features['atr_normalized'].mean()
    threshold = (avg_atr_pct * volatility_multiplier) / 100

    if verbose:
        print(f"INFO: Verwende adaptive Lernziele für {timeframe}: lookahead={lookahead}, threshold={threshold*100:.2f}% (dynamisch berechnet)")

    future_returns = df_with_features['close'].pct_change(periods=lookahead).shift(-lookahead)
    df_with_features['target'] = 0
    df_with_features.loc[future_returns > threshold, 'target'] = 1
    df_with_features.loc[future_returns < -threshold, 'target'] = -1
    df_with_features = df_with_features[df_with_features['target'] != 0].copy()
    df_with_features['target'] = df_with_features['target'].replace(-1, 0)

    feature_cols = [
        'bb_width', 'bb_pband', 'obv', 'rsi', 'macd_diff', 'macd',
        'atr_normalized', 'adx', 'adx_pos', 'adx_neg',
        'volume_ratio', 'mfi', 'cmf',
        'price_to_ema20', 'price_to_ema50',
        'stoch_k', 'stoch_d', 'williams_r', 'roc', 'cci',
        'price_to_resistance', 'price_to_support',
        'high_low_range', 'close_to_high', 'close_to_low',
        'day_of_week', 'hour_of_day',
        'returns_lag1', 'returns_lag2', 'returns_lag3', 'hist_volatility'
    ]

    X = df_with_features[feature_cols]
    y = df_with_features['target']

    return X, y


def build_and_train_model(X_train, y_train):
    model = tf.keras.models.Sequential([
        tf.keras.layers.Dense(256, activation='relu', input_shape=(X_train.shape[1],)),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(128, activation='relu'),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(64, activation='relu'),
        tf.keras.layers.Dropout(0.25),
        tf.keras.layers.Dense(32, activation='relu'),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(1, activation='sigmoid')
    ])
    optimizer = tf.keras.optimizers.Adam(learning_rate=0.0005)
    model.compile(optimizer=optimizer, loss='binary_crossentropy', metrics=['accuracy'])
    early_stopping = tf.keras.callbacks.EarlyStopping(
        monitor='val_loss', patience=15, restore_best_weights=True, verbose=1
    )
    reduce_lr = tf.keras.callbacks.ReduceLROnPlateau(
        monitor='val_loss', factor=0.5, patience=5, min_lr=0.00001, verbose=1
    )
    model.fit(
        X_train, y_train,
        validation_split=0.2,
        epochs=150,
        batch_size=32,
        callbacks=[early_stopping, reduce_lr],
        verbose=1
    )
    return model


def save_model_and_scaler(model, scaler, model_path, scaler_path):
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    model.save(model_path)
    joblib.dump(scaler, scaler_path)
    logging.info("Modell & Scaler gespeichert.")


def load_model_and_scaler(model_path, scaler_path):
    try:
        model = tf.keras.models.load_model(model_path)
        scaler = joblib.load(scaler_path)
        logging.info("Modell & Scaler geladen.")
        return model, scaler
    except Exception as e:
        logging.error(f"Fehler beim Laden von Modell/Scaler: {e}")
        return None, None
