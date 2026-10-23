# -*- coding: utf-8 -*-
"""
=================================================================================
  THE BEAST V7.0 - DIRECT TELEGRAM & LOCKED POC ENGINE
=================================================================================
  Target        : Spot Gold (XAU/USD via Twelve Data API)
  Core          : Immediate Telegram Notification + Locked POC Strategy
=================================================================================
"""

import os
import sys
import time
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

from sklearn.ensemble import RandomForestClassifier

# =============================================================================
# SECURE CONFIGURATION (GitHub Secrets)
# =============================================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "").strip()

SYMBOL = "XAU/USD"
INTERVAL = "5min"

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


def send_telegram_direct(message):
    """دالة إرسال فورية ومباشرة بدون تعقيد"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[ERROR] TELEGRAM_TOKEN or CHAT_ID is missing in GitHub Secrets!")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        res = requests.post(url, json=payload, timeout=10)
        print(f"[TELEGRAM LOG] Status Code: {res.status_code} | Response: {res.text}")
        return res.status_code == 200
    except Exception as e:
        print(f"[TELEGRAM EXCEPTION] {e}")
        return False


# -----------------------------------------------------------------------------
# 1. IMMEDIATE STARTUP PING (إرسال الرسالة فوراً عند تشغيل البوت)
# -----------------------------------------------------------------------------
now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
startup_alert = (
    f"⚡ *THE BEAST V7.0 IS NOW ACTIVE*\n"
    f"🌐 *Server Status:* Connected to GitHub Actions\n"
    f"⏰ *UTC Time:* `{now_utc}`\n"
    f"📊 *Status:* Fetching Live XAU/USD Data..."
)
print("[SYSTEM] Attempting to send immediate startup ping to Telegram...")
send_telegram_direct(startup_alert)


def fetch_candles_twelve_data(symbol, interval):
    try:
        if not TWELVE_DATA_API_KEY:
            print("[ERROR] TWELVE_DATA_API_KEY is missing!")
            return None

        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize=1200&apikey={TWELVE_DATA_API_KEY}"
        res = requests.get(url, timeout=12)
        data = res.json()
        
        if "values" not in data:
            print(f"[TWELVE DATA ERROR RESPONSE] {data}")
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
        return df[['time', 'open', 'high', 'low', 'close', 'tick_volume']]
    except Exception as e:
        print(f"[FETCH EXCEPTION] {e}")
        return None


def wilder_atr(df, length=14):
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


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
        print("--- [SYSTEM] THE BEAST V7.0 ENGINE STARTED ---")
        self.rf_model = RandomForestClassifier(n_estimators=RF_ESTIMATORS, random_state=42, n_jobs=-1)
        self.risk = RiskManager()

    def run_cycle(self):
        df_m5 = fetch_candles_twelve_data(SYMBOL, INTERVAL)

        if df_m5 is None or len(df_m5) < MIN_BARS_TO_TRADE:
            print("[WARN] Data fetch failed or insufficient bars.")
            return

        merged = build_locked_poc_features(df_m5)
        if len(merged) < MIN_TRAIN_SAMPLES:
            print("[WARN] Not enough merged samples for training.")
            return

        latest = merged.iloc[-1]
        price = latest["close"]
        now_time = datetime.now(timezone.utc)

        # -----------------------------------------------------------------
        # 2. DATA CONFIRMATION PING WITH LIVE PRICE (تأكيد جلب السعر الحي)
        # -----------------------------------------------------------------
        price_msg = (
            f"💰 *XAU/USD Live Spot:* `${price:.2f}`\n"
            f"📈 *POC Distance:* `{latest['poc_distance']:.2f}`\n"
            f"📊 *Volume Commitment:* `{latest['volume_commitment']:.2f}x`"
        )
        send_telegram_direct(price_msg)

        # AI TRAINING
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

        # -----------------------------------------------------------------
        # 3. TRADE SIGNAL NOTIFICATION (إرسال إشارة الصفقة فور تحقق الشروط)
        # -----------------------------------------------------------------
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
            send_telegram_direct(msg)

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
            send_telegram_direct(msg)


if __name__ == "__main__":
    bot = TradingBeast()
    bot.run_cycle()
