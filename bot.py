# -*- coding: utf-8 -*-
"""
=================================================================================
  THE BEAST V3.5 - INSTANT NOTIFICATION ENGINE (SECURE SECRETS EDITION)
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
import yfinance as yf

from sklearn.ensemble import RandomForestClassifier

# =============================================================================
# SECURE CONFIGURATION (Fetch from GitHub Secrets or Fallback)
# =============================================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8462317233:AAENwGgJ4puoKhQSAWR0Dg3f5nCsPPqncUk")
CHAT_ID = os.environ.get("CHAT_ID", "7432584346")
SYMBOL = "GC=F"                     # Gold Futures

TF_ENTRY = "5m"                     # 5m Timeframe
BARS = 1200                         

# --- AI & INSTITUTIONAL GATES ---
RF_ESTIMATORS = 500
MIN_TRAIN_SAMPLES = 200
MIN_BARS_TO_TRADE = 250

RF_BUY_THRESHOLD = 0.52             
RF_SELL_THRESHOLD = 0.52            
MIN_CONFLUENCE = 2                  

# --- RISK MANAGEMENT ---
SL_ATR_MULT = 1.6                   
TP1_R = 1.5                         
TP2_MIN_R = 2.5                     


def fetch_candles_yf(symbol, interval, period="5d"):
    try:
        df = yf.download(tickers=symbol, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            return None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.reset_index()
        time_col = 'Datetime' if 'Datetime' in df.columns else 'Date'
        
        df['time'] = (df[time_col].astype('int64') // 10**9).astype(int)
        df = df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'tick_volume'})
        df = df[['time', 'open', 'high', 'low', 'close', 'tick_volume']].copy()
        return df.sort_values('time').reset_index(drop=True)
    except Exception as e:
        print(f"[YFINANCE ERROR] {e}")
        return None


def wilder_atr(df, length=14):
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


FEATURES = ["log_ret", "bank_absorption_buy", "bank_absorption_sell", "delta_spike", "fvg_imbalance", "structure_flow"]

def build_bank_features(df):
    df = df.reset_index(drop=True)
    
    df["atr"] = wilder_atr(df, 14).fillna(1.0)
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1)).fillna(0.0)
    
    # MICRO-ABSORPTION
    price_span = (df["high"].rolling(3).max() - df["low"].rolling(3).min()) / df["atr"]
    vol_avg = df["tick_volume"].rolling(10).mean() + 1e-9
    vol_ratio = df["tick_volume"] / vol_avg
    
    is_absorbed = (price_span < 1.2) & (vol_ratio > 1.7)
    df["bank_absorption_buy"] = (is_absorbed & (df["close"] > df["open"])).astype(float)
    df["bank_absorption_sell"] = (is_absorbed & (df["close"] < df["open"])).astype(float)
    
    # DELTA SPIKE
    body = (df["close"] - df["open"]).abs()
    df["delta_spike"] = np.where((body > 1.5 * df["atr"]) & (vol_ratio > 1.8), np.sign(df["close"] - df["open"]), 0.0)
    
    # FVG IMBALANCE
    fvg_b = df["low"] > df["high"].shift(2)
    fvg_s = df["high"] < df["low"].shift(2)
    df["fvg_imbalance"] = np.where(fvg_b, 1.0, np.where(fvg_s, -1.0, 0.0))
    
    # INSTITUTIONAL STRUCTURE FLOW
    ma_fast = df["close"].rolling(8).mean()
    ma_slow = df["close"].rolling(30).mean()
    df["structure_flow"] = np.where(ma_fast > ma_slow, 1.0, -1.0)
    
    # AI TARGET
    fwd = df["close"].shift(-3)
    df["target"] = ((fwd - df["close"]) > 0.20 * df["atr"]).astype(float)
    
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
        print("--- [SYSTEM] THE BEAST V3.5 ONLINE ---")
        self.rf_model = RandomForestClassifier(n_estimators=RF_ESTIMATORS, random_state=42, n_jobs=-1)
        self.risk = RiskManager()

    def send_telegram(self, msg):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}&parse_mode=Markdown"
            res = requests.get(url, timeout=5)
            print(f"[TELEGRAM RESPONSE] Status: {res.status_code}")
        except Exception as e:
            print(f"[TELEGRAM ERROR] {e}")

    def run_cycle(self):
        df_m5 = fetch_candles_yf(SYMBOL, interval=TF_ENTRY, period="5d")

        if df_m5 is None or len(df_m5) < MIN_BARS_TO_TRADE:
            print("[WARN] Fetching fresh market data...")
            return

        merged = build_bank_features(df_m5)
        if len(merged) < MIN_TRAIN_SAMPLES:
            return

        latest = merged.iloc[-1]
        price = latest["close"]
        now_time = datetime.now(timezone.utc)

        # 1. ALWAYS SEND RUN NOTIFICATION AT STARTUP
        startup_msg = (
            f"⚡ *THE BEAST RUNNING...*\n"
            f"💰 *Gold:* `${price:.2f}` | ⏰ `{now_time.strftime('%H:%M:%S')} UTC`"
        )
        self.send_telegram(startup_msg)

        X = merged[FEATURES]
        y = merged["target"]
        self.rf_model.fit(X, y)

        atr = latest["atr"]
        X_curr = merged[FEATURES].iloc[[-1]]
        probs = self.rf_model.predict_proba(X_curr)[0]
        prob_buy = probs[1] if len(probs) > 1 else 0.5
        prob_sell = probs[0] if len(probs) > 1 else 0.5

        buy_conf = sum([
            latest["bank_absorption_buy"] > 0,
            latest["delta_spike"] > 0,
            latest["fvg_imbalance"] > 0,
            latest["structure_flow"] > 0
        ])

        sell_conf = sum([
            latest["bank_absorption_sell"] > 0,
            latest["delta_spike"] < 0,
            latest["fvg_imbalance"] < 0,
            latest["structure_flow"] < 0
        ])

        print(f"[{now_time.strftime('%H:%M:%S')}] GOLD: ${price:.2f} | BUY Prob: {prob_buy:.2f} (Conf: {buy_conf}) | SELL Prob: {prob_sell:.2f} (Conf: {sell_conf})")

        # 2. SEND TRADE SIGNAL IF CONDITIONS MATCH
        if prob_buy >= RF_BUY_THRESHOLD and buy_conf >= MIN_CONFLUENCE:
            p = self.risk.plan("BUY", price, atr)
            msg = (
                f"🚀 *AI BANK ABSORPTION BUY (XAUUSD)*\n\n"
                f"📈 *Entry:* `{price:.2f}`\n"
                f"🛑 *Stop Loss:* `{p['sl']:.2f}`\n"
                f"🎯 *Target 1:* `{p['tp1']:.2f}`\n"
                f"🏆 *Target 2:* `{p['tp2']:.2f}`\n\n"
                f"🤖 *AI Confidence:* `{prob_buy:.2f}`\n"
                f"⚡ *Bank Footprint:* `{buy_conf}/4`"
            )
            print(msg)
            self.send_telegram(msg)

        elif prob_sell >= RF_SELL_THRESHOLD and sell_conf >= MIN_CONFLUENCE:
            p = self.risk.plan("SELL", price, atr)
            msg = (
                f"🔻 *AI BANK ABSORPTION SELL (XAUUSD)*\n\n"
                f"📉 *Entry:* `{price:.2f}`\n"
                f"🛑 *Stop Loss:* `{p['sl']:.2f}`\n"
                f"🎯 *Target 1:* `{p['tp1']:.2f}`\n"
                f"🏆 *Target 2:* `{p['tp2']:.2f}`\n\n"
                f"🤖 *AI Confidence:* `{prob_sell:.2f}`\n"
                f"⚡ *Bank Footprint:* `{sell_conf}/4`"
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
