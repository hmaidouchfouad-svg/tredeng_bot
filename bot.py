from datetime import datetime
import os
import numpy as np
import pandas as pd
import requests
import yfinance as yf

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SYMBOL = "GC=F"


def send_telegram(msg):
  if not TELEGRAM_TOKEN or not CHAT_ID:
    print("[ERROR] Telegram secrets missing!")
    return
  try:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg}
    res = requests.post(url, json=payload, timeout=10)
    print(f"[INFO] Telegram status code: {res.status_code}")
  except Exception as e:
    print(f"[ERROR] Telegram failed: {e}")


def calculate_lsma(series, window=73):
  """حساب LSMA (Least Squares Moving Average) بشكل مستقل"""
  if len(series) < window:
    return series.iloc[-1]

  y = series.tail(window).values
  x = np.arange(window)
  slope, intercept = np.polyfit(x, y, 1)
  return slope * (window - 1) + intercept


def calculate_mfi(df, window=14):
  """حساب MFI (Money Flow Index) بشكل مستقل"""
  typical_price = (df["high"] + df["low"] + df["close"]) / 3
  money_flow = typical_price * df["volume"]

  delta = typical_price.diff()
  pos_flow = np.where(delta > 0, money_flow, 0)
  neg_flow = np.where(delta < 0, money_flow, 0)

  pos_mf = pd.Series(pos_flow).rolling(window=window).sum()
  neg_mf = pd.Series(neg_flow).rolling(window=window).sum()

  mfr = pos_mf / (neg_mf + 1e-10)
  mfi = 100 - (100 / (1 + mfr))
  return mfi.iloc[-1] if not mfi.empty else 50.0


def run_engine():
  print("--- RUNNING TRADING BOT CYCLE ---")
  try:
    data = yf.Ticker(SYMBOL)
    df = data.history(period="5d", interval="5m")

    if df.empty:
      print("[WARNING] No data fetched from Yahoo Finance.")
      return

    df.columns = [str(c).lower() for c in df.columns]

    price = float(df["close"].iloc[-1])
    lsma = float(calculate_lsma(df["close"], window=73))
    mfi = float(calculate_mfi(df, window=14))

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"[{timestamp}] Price: {price:.2f} | LSMA: {lsma:.2f} | MFI: {mfi:.1f}"
    )

    # إرسال رسالة تجريبية لتأكيد العمل والاتصال
    status_msg = (
        f"🤖 Bot Working Successfully!\n"
        f"Symbol: GOLD (GC=F)\n"
        f"Price: {price:.2f}\n"
        f"LSMA: {lsma:.2f}\n"
        f"MFI: {mfi:.1f}\n"
        f"Time: {timestamp}"
    )

    if price > lsma and mfi > 50:
      msg = f"🚀 GOLD BUY SIGNAL\nPrice: {price:.2f}\nMFI: {mfi:.1f}"
      send_telegram(msg)
    elif price < lsma and mfi < 50:
      msg = f"📉 GOLD SELL SIGNAL\nPrice: {price:.2f}\nMFI: {mfi:.1f}"
      send_telegram(msg)
    else:
      # إرسال تقرير حالة في حالة التجربة
      send_telegram(status_msg)

  except Exception as e:
    print(f"[ERROR] Engine failure: {e}")


if __name__ == "__main__":
  run_engine()
