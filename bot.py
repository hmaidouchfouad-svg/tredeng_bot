# -*- coding: utf-8 -*-
"""
=================================================================================
  THE BEAST V8.0 - APEX INSTITUTIONAL CLOB & SMART MONEY PREDATOR ENGINE
=================================================================================
  Target        : Spot Gold (XAU/USD via Twelve Data API)
  Core          : Advanced Market Maker Trap Detector + High-Precision Telegram Alert
=================================================================================
"""

import os
import time
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import sys

from sklearn.ensemble import RandomForestClassifier

# =============================================================================
# SECURE CONFIGURATION
# =============================================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8462317233:AAENwGgJ4puoKhQSAWR0Dg3f5nCsPPqncUk")
CHAT_ID = os.environ.get("CHAT_ID", "7432584346")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "d9dc7faf9e5c4b7398831c15e4eef06e")

SYMBOL = "XAU/USD"                  # Twelve Data format for Spot Gold
INTERVAL = "5min"                   # 5m Timeframe

# --- APEX INSTITUTIONAL & RISK PARAMETERS ---
RF_ESTIMATORS = 800
MIN_TRAIN_SAMPLES = 250
MIN_BARS_TO_TRADE = 300

SL_ATR_MULT = 1.3
TP1_R = 2.2
TP2_MIN_R = 4.0
MIN_AI_CONFIDENCE = 0.68            # نسبة ثقة صارمة جداً لتقليل الإشارات الكاذبة


def fetch_candles_twelve_data(symbol, interval):
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize=1200&apikey={TWELVE_DATA_API_KEY}"
        res = requests.get(url, timeout=10)
        data = res.json()
        
        if "values" not in data:
            print(f"[TWELVE DATA ERROR] {data}")
            return None
            
        df = pd.DataFrame(data["values"])
        
        df = df.rename(columns={
            'datetime': 'time_str',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'tick_volume'
        })
        
        df = df.iloc[::-1].reset_index(drop=True)
        
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].astype(float)
            
        if 'tick_volume' in df.columns:
            df['tick_volume'] = pd.to_numeric(df['tick_volume'], errors='coerce').fillna(1.0)
        else:
            df['tick_volume'] = 1.0
            
        df['time'] = pd.to_datetime(df['time_str']).astype('int64') // 10**9
        df = df[['time', 'open', 'high', 'low', 'close', 'tick_volume']]
        return df
    except Exception as e:
        print(f"[FETCH ERROR] {e}")
        return None


def wilder_atr(df, length=14):
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


# =============================================================================
# APEX SMART MONEY & CLOB MICRO-STRUCTURE FEATURES ENGINE
# =============================================================================
FEATURES = [
    "poc_distance", 
    "volume_commitment", 
    "institutional_breakout", 
    "price_velocity", 
    "order_flow_imbalance", 
    "liquidity_sweep_intensity"
]

def build_apex_features(df):
    df = df.reset_index(drop=True)
    
    df["atr"] = wilder_atr(df, 14).fillna(1.0)
    
    # Volume Profile & Point of Control (POC)
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    rolling_vol = df["tick_volume"].rolling(40).sum() + 1e-9
    rolling_vol_price = (typical_price * df["tick_volume"]).rolling(40).sum()
    df["rolling_poc"] = rolling_vol_price / rolling_vol
    df["poc_distance"] = (df["close"] - df["rolling_poc"]) / df["atr"]
    
    # Volume Commitment & Order Flow Imbalance
    vol_avg = df["tick_volume"].rolling(20).mean() + 1e-9
    df["volume_commitment"] = df["tick_volume"] / vol_avg
    
    body = df["close"] - df["open"]
    total_range = (df["high"] - df["low"]).replace(0, 1e-9)
    df["order_flow_imbalance"] = body / total_range
    
    # Institutional Breakouts & Stop Hunt Metrics
    high_20 = df["high"].rolling(20).max().shift(1)
    low_20 = df["low"].rolling(20).min().shift(1)
    
    breakout_up = (df["close"] > high_20) & (df["volume_commitment"] > 2.0)
    breakout_down = (df["close"] < low_20) & (df["volume_commitment"] > 2.0)
    df["institutional_breakout"] = np.where(breakout_up, 1.0, np.where(breakout_down, -1.0, 0.0))
    
    df["price_velocity"] = (df["close"] - df["close"].shift(2)) / df["atr"]
    
    # Liquidity Sweep Intensity (Wick vs Body ratio)
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    df["liquidity_sweep_intensity"] = (upper_wick - lower_wick) / df["atr"]
    
    # Advanced Target Mapping for Machine Learning
    fwd_return = df["close"].shift(-3) - df["close"]
    df["target"] = (fwd_return > 0.35 * df["atr"]).astype(float)
    
    return df.dropna(subset=FEATURES + ["target"]).reset_index(drop=True)


class RiskManager:
    @staticmethod
    def plan(side, price, atr, digits=2):
        if side in ["BUY_TRAP_REVERSAL", "BUY_EXPANSION"]:
            sl = price - SL_ATR_MULT * atr
            risk = max(price - sl, 0.1 * atr)
            tp1 = price + risk * TP1_R
            tp2 = price + risk * TP2_MIN_R
        else:
            sl = price + SL_ATR_MULT * atr
            risk = max(sl - price, 0.1 * atr)
            tp1 = price - risk * TP1_R
            tp2 = price - risk * TP2_MIN_R

        return {
            "sl": round(sl, digits),
            "tp1": round(tp1, digits),
            "tp2": round(tp2, digits),
        }


class TradingBeastApex:
    def __init__(self):
        print("--- [SYSTEM] THE BEAST V8.0 - APEX PREDATOR ENGINE ONLINE ---")
        self.rf_model = RandomForestClassifier(
            n_estimators=RF_ESTIMATORS, 
            max_depth=12, 
            min_samples_split=10, 
            random_state=42, 
            n_jobs=-1
        )
        self.risk = RiskManager()

    def send_telegram(self, msg):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}&parse_mode=Markdown"
            res = requests.get(url, timeout=5)
            print(f"[TELEGRAM STATUS] {res.status_code}")
        except Exception as e:
            print(f"[TELEGRAM ERROR] {e}")

    def analyze_market_signal(self, df_m5):
        merged = build_apex_features(df_m5)
        if len(merged) < MIN_TRAIN_SAMPLES:
            return None

        # Train Apex RandomForest Classifier
        X = merged[FEATURES]
        y = merged["target"]
        self.rf_model.fit(X, y)

        latest = merged.iloc[-1]
        price = latest["close"]
        atr = latest["atr"]

        X_curr = merged[FEATURES].iloc[[-1]]
        probs = self.rf_model.predict_proba(X_curr)[0]
        prob_buy = probs[1] if len(probs) > 1 else 0.5
        prob_sell = probs[0] if len(probs) > 1 else 0.5

        # Micro-structure & Smart Money Trap Detection
        prev_high = df_m5['high'].iloc[-25:-1].max()
        prev_low = df_m5['low'].iloc[-25:-1].min()
        
        c = df_m5.iloc[-1]
        body = abs(c['close'] - c['open'])
        range_val = c['high'] - c['low'] if (c['high'] - c['low']) > 0 else 1e-9
        upper_wick = c['high'] - max(c['open'], c['close'])
        lower_wick = min(c['open'], c['close']) - c['low']
        vol_ratio = latest["volume_commitment"]

        # 1. Apex Stop Hunt / Liquidity Sweep Reversal (Market Maker Trap)
        if c['high'] > prev_high and upper_wick > (body * 1.4) and vol_ratio > 1.3 and prob_sell >= MIN_AI_CONFIDENCE:
            return {
                "type": "SELL_TRAP_REVERSAL", 
                "reason": "Apex Market Maker Stop Hunt at High (Liquidity Sweep & Reversal)", 
                "price": price, 
                "atr": atr, 
                "conf": prob_sell
            }
        elif c['low'] < prev_low and lower_wick > (body * 1.4) and vol_ratio > 1.3 and prob_buy >= MIN_AI_CONFIDENCE:
            return {
                "type": "BUY_TRAP_REVERSAL", 
                "reason": "Apex Market Maker Stop Hunt at Low (Liquidity Sweep & Reversal)", 
                "price": price, 
                "atr": atr, 
                "conf": prob_buy
            }

        # 2. Institutional True Expansion / Break of Structure (BOS)
        if c['close'] > prev_high and body > (upper_wick * 2.0) and vol_ratio > 1.9 and prob_buy >= MIN_AI_CONFIDENCE:
            return {
                "type": "BUY_EXPANSION", 
                "reason": "Institutional True Expansion (BOS & Order Flow Imbalance)", 
                "price": price, 
                "atr": atr, 
                "conf": prob_buy
            }
        elif c['close'] < prev_low and body > (lower_wick * 2.0) and vol_ratio > 1.9 and prob_sell >= MIN_AI_CONFIDENCE:
            return {
                "type": "SELL_EXPANSION", 
                "reason": "Institutional True Expansion (BOS & Order Flow Imbalance)", 
                "price": price, 
                "atr": atr, 
                "conf": prob_sell
            }

        return None

    def run_cycle(self):
        now_time = datetime.now(timezone.utc)
        print(f"[{now_time.strftime('%H:%M:%S')}] Apex Scanning XAU/USD feed via Twelve Data...")

        df_m5 = fetch_candles_twelve_data(SYMBOL, INTERVAL)
        if df_m5 is None or len(df_m5) < MIN_BARS_TO_TRADE:
            print("[WARN] Insufficient bars or waiting for Twelve Data feed...")
            return

        signal = self.analyze_market_signal(df_m5)
        if signal:
            p = self.risk.plan(signal["type"], signal["price"], signal["atr"])
            emoji = "🚀" if "BUY" in signal["type"] else "🔻"
            
            msg = (
                f"{emoji} *THE BEAST V8.0 - APEX SIGNAL (XAU/USD)*\n\n"
                f"⚡ *Strategy:* `{signal['type']}`\n"
                f"📌 *Intelligence:* {signal['reason']}\n"
                f"📈 *Entry Price:* `{signal['price']:.2f}`\n"
                f"🛑 *Stop Loss:* `{p['sl']:.2f}`\n"
                f"🎯 *Target 1:* `{p['tp1']:.2f}`\n"
                f"🏆 *Target 2:* `{p['tp2']:.2f}`\n\n"
                f"🤖 *Apex AI Confidence:* `{signal['conf']*100:.1f}%`\n"
                f"⏰ *Time (UTC):* `{datetime.now(timezone.utc).strftime('%H:%M:%S')}`"
            )
            print(msg)
            self.send_telegram(msg)

    def start(self):
        startup_msg = (
            f"⚡ *THE BEAST V8.0 APEX PREDATOR ONLINE*\n"
            f"🧠 *AI Engine:* Advanced Smart Money & CLOB Micro-Structure\n"
            f"🎯 *Target:* XAU/USD | *Mode:* Alert-Only Predator"
        )
        self.send_telegram(startup_msg)
        
        while True:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[ERROR] {e}")
            
            # فحص دقيق كل 60 ثانية لتتبع الشموع واقتناص الفرص فوراً
            time.sleep(60)


if __name__ == "__main__":
    bot = TradingBeastApex()
    bot.start()
