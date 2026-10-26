# -*- coding: utf-8 -*-
"""
=================================================================================
  THE BEAST V7.0 - TWELVE DATA LIVE SPOT & LOCKED POC ENGINE
=================================================================================
  Target        : Spot Gold (XAU/USD via Twelve Data API)
  Core          : Proven Telegram Method + Rolling POC & Volume Commitment
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
# SECURE CONFIGURATION (GitHub Secrets / Fallback to active tokens)
# =============================================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8462317233:AAENwGgJ4puoKhQSAWR0Dg3f5nCsPPqncUk")
CHAT_ID = os.environ.get("CHAT_ID", "7432584346")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "d9dc7faf9e5c4b7398831c15e4eef06e")

SYMBOL = "XAU/USD"                  # Twelve Data format for Spot Gold
INTERVAL = "5min"                   # 5m Timeframe

# --- INSTITUTIONAL AI PARAMETERS ---
RF_ESTIMATORS = 600
MIN_TRAIN_SAMPLES = 200
MIN_BARS_TO_TRADE = 250

RF_BUY_THRESHOLD = 0.55
RF_SELL_THRESHOLD = 0.55
MIN_CONFLUENCE = 2

# --- RISK ENGINE ---
SL_ATR_MULT = 1.4
TP1_R = 2.0
TP2_MIN_R = 3.5


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
# LOCKED INSTITUTIONAL POC & VOLUME NODE ENGINE
# =============================================================================
FEATURES = ["poc_distance", "volume_commitment", "institutional_breakout", "price_velocity"]

def build_locked_poc_features(df):
    df = df.reset_index(drop=True)
    
    df["atr"] = wilder_atr(df, 14).fillna(1.0)
    
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    rolling_vol = df["tick_volume"].rolling(40).sum() + 1e-9
    rolling_vol_price = (typical_price * df["tick_volume"]).rolling(40).sum()
    df["rolling_poc"] = rolling_vol_price / rolling_vol
    
    df["poc_distance"] = (df["close"] - df["rolling_poc"]) / df["atr"]
    
    vol_avg = df["tick_volume"].rolling(20).mean() + 1e-9
    df["volume_commitment"] = df["tick_volume"] / vol_avg
    
    high_20 = df["high"].rolling(20).max().shift(1)
    low_20 = df["low"].rolling(20).min().shift(1)
    
    breakout_up = (df["close"] > high_20) & (df["volume_commitment"] > 2.2)
    breakout_down = (df["close"] < low_20) & (df["volume_commitment"] > 2.2)
    
    df["institutional_breakout"] = np.where(breakout_up, 1.0, np.where(breakout_down, -1.0, 0.0))
    df["price_velocity"] = (df["close"] - df["close"].shift(2)) / df["atr"]
    
    fwd = df["close"].shift(-3)
    df["target"] = ((fwd - df["close"]) > 0.30 * df["atr"]).astype(float)
    
    return df.dropna(subset=FEATURES + ["target"]).reset_index(drop=True)


class RiskManager:
    @staticmethod
    def plan(side, price, atr, digits=2):
        if side == "BUY":
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


class TradingBeast:
    def __init__(self):
        print("--- [SYSTEM] THE BEAST V7.0 (PROVEN TELEGRAM METHOD) ONLINE ---")
        self.rf_model = RandomForestClassifier(n_estimators=RF_ESTIMATORS, random_state=42, n_jobs=-1)
        self.risk = RiskManager()

    # --- الطريقة المضمونة والمجربة لإرسال الرسائل عبر تيليجرام ---
    def send_telegram(self, msg):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}&parse_mode=Markdown"
            res = requests.get(url, timeout=5)
            print(f"[TELEGRAM STATUS] {res.status_code}")
        except Exception as e:
            print(f"[TELEGRAM ERROR] {e}")

    def run_cycle(self):
        # 1. إرسال رسالة فورية عند بداية تشغيل البوت لتأكيد الاتصال
        now_time = datetime.now(timezone.utc)
        startup_msg = (
            f"⚡ *THE BEAST V7.0 IS ONLINE*\n"
            f"⏰ *Time:* `{now_time.strftime('%H:%M:%S')} UTC`\n"
            f"📊 *Status:* Fetching live XAU/USD data..."
        )
        self.send_telegram(startup_msg)

        # 2. جلب الداتا الحية
        df_m5 = fetch_candles_twelve_data(SYMBOL, INTERVAL)

        if df_m5 is None or len(df_m5) < MIN_BARS_TO_TRADE:
            print("[WARN] Fetching live data from Twelve Data...")
            return

        merged = build_locked_poc_features(df_m5)
        if len(merged) < MIN_TRAIN_SAMPLES:
            return

        latest = merged.iloc[-1]
        price = latest["close"]

        # إرسال السعر الحالي للتأكد من أن جلب البيانات تم بنجاح
        price_msg = f"💰 *XAU/USD Live Spot:* `${price:.2f}`"
        self.send_telegram(price_msg)

        X = merged[FEATURES]
        y = merged["target"]
        self.rf_model.fit(X, y)

        atr = latest["atr"]
        X_curr = merged[FEATURES].iloc[[-1]]
        probs = self.rf_model.predict_proba(X_curr)[0]
        prob_buy = probs[1] if len(probs) > 1 else 0.5
        prob_sell = probs[0] if len(probs) > 1 else 0.5

        buy_conf = sum([
            latest["poc_distance"] > 0.5,
            latest["volume_commitment"] > 2.0,
            latest["institutional_breakout"] > 0,
            latest["price_velocity"] > 0.5
        ])

        sell_conf = sum([
            latest["poc_distance"] < -0.5,
            latest["volume_commitment"] > 2.0,
            latest["institutional_breakout"] < 0,
            latest["price_velocity"] < -0.5
        ])

        print(f"[{now_time.strftime('%H:%M:%S')}] XAU/USD: ${price:.2f} | BUY Prob: {prob_buy:.2f} (Conf: {buy_conf}) | SELL Prob: {prob_sell:.2f} (Conf: {sell_conf})")

        # 3. إرسال إشارة الصفقة الحقيقية فور تحقق الشروط
        if prob_buy >= RF_BUY_THRESHOLD and buy_conf >= MIN_CONFLUENCE:
            p = self.risk.plan("BUY", price, atr)
            msg = (
                f"🚀 *INSTITUTIONAL BUY SIGNAL (XAU/USD)*\n\n"
                f"📈 *Entry:* `{price:.2f}`\n"
                f"🛑 *Stop Loss:* `{p['sl']:.2f}`\n"
                f"🎯 *Target 1:* `{p['tp1']:.2f}`\n"
                f"🏆 *Target 2:* `{p['tp2']:.2f}`\n\n"
                f"🤖 *AI Confidence:* `{prob_buy:.2f}`\n"
                f"⚡ *Locked Confluence:* `{buy_conf}/4`"
            )
            print(msg)
            self.send_telegram(msg)

        elif prob_sell >= RF_SELL_THRESHOLD and sell_conf >= MIN_CONFLUENCE:
            p = self.risk.plan("SELL", price, atr)
            msg = (
                f"🔻 *INSTITUTIONAL SELL SIGNAL (XAU/USD)*\n\n"
                f"📉 *Entry:* `{price:.2f}`\n"
                f"🛑 *Stop Loss:* `{p['sl']:.2f}`\n"
                f"🎯 *Target 1:* `{p['tp1']:.2f}`\n"
                f"🏆 *Target 2:* `{p['tp2']:.2f}`\n\n"
                f"🤖 *AI Confidence:* `{prob_sell:.2f}`\n"
                f"⚡ *Locked Confluence:* `{sell_conf}/4`"
            )
            print(msg)
            self.send_telegram(msg)

    def start(self):
        try:
            self.run_cycle()
        except Exception as e:
            print(f"[ERROR] {e}")


if __name__ == "__main__":
    bot = TradingBeast()
    bot.start()
