from datetime import datetime
import os
import pandas as pd
import pandas_ta as ta
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
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}"
    res = requests.get(url, timeout=10)
    print(f"[INFO] Telegram status code: {res.status_code}")
  except Exception as e:
    print(f"[ERROR] Telegram failed: {e}")


def run_engine():
  print("--- RUNNING TRADING BOT CYCLE ---")
  try:
    df = yf.download(
        tickers=SYMBOL, period="5d", interval="5m", progress=False
    )
    if df is None or df.empty:
      print("[WARNING] No data fetched from Yahoo Finance.")
      return

    if isinstance(df.columns, pd.MultiIndex):
      df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]

    if "volume" in df.columns and "tick_volume" not in df.columns:
      df["tick_volume"] = df["volume"]

    # حساب المؤشرات
    df["lsma"] = ta.linreg(df["close"], length=73)

    mfi_val = ta.mfi(
        df["high"], df["low"], df["close"], df["tick_volume"], length=14
    )
    df["mfi"] = (
        mfi_val.iloc[:, 0] if isinstance(mfi_val, pd.DataFrame) else mfi_val
    )

    df["vfi"] = df["close"].pct_change() * df["tick_volume"]

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = float(last["close"])
    lsma = float(last["lsma"])
    mfi = float(last["mfi"]) if pd.notnull(last["mfi"]) else 50.0
    vfi = float(last["vfi"]) if pd.notnull(last["vfi"]) else 0.0

    timestamp = datetime.now().strftime("%H:%M:%S")
    print(
        f"[{timestamp}] Price: {price:.2f} | LSMA: {lsma:.2f} | MFI: {mfi:.1f}"
    )

    # تجربة إرسال رسالة تأكيد النجاح للتجرِبة الأولى
    status_msg = (
        f"✅ Bot is Active!\nSymbol: GOLD (GC=F)\nPrice: {price:.2f}\nLSMA:"
        f" {lsma:.2f}\nMFI: {mfi:.1f}"
    )

    if price > lsma and mfi > 50:
      msg = f"🚀 GOLD BUY SIGNAL\nPrice: {price:.2f}\nMFI: {mfi:.1f}"
      send_telegram(msg)
    elif price < lsma and mfi < 50:
      msg = f"📉 GOLD SELL SIGNAL\nPrice: {price:.2f}\nMFI: {mfi:.1f}"
      send_telegram(msg)
    else:
      # صيفط رسالة اختبار باش تتأكد باللي التلغرام خدام
      send_telegram(status_msg)

  except Exception as e:
    print(f"[ERROR] Engine failure: {e}")


if __name__ == "__main__":
  run_engine()
