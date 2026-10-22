import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
import time
from datetime import datetime

# --- CONFIGURATION ---
TELEGRAM_TOKEN = "8742576163:AAHnB7KUzcO9dnjlqgQhDajT2TOkc8Bx6bo"
CHAT_ID = "7432584346"
SYMBOL = "GC=F" # Yahoo Finance ticker for Gold

class GoldMasterUltra:
    def __init__(self):
        print("[INFO] Gold Master Ultra (Yahoo Finance Edition) Initialized.")
        print("[INFO] Monitoring Gold (GC=F) using LSMA, VFI, and Money Flow.")

    def send_telegram(self, msg):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}"
            requests.get(url, timeout=5)
        except Exception as e:
            print(f"[ERROR] Telegram failed: {e}")

    def run_engine(self):
        print("--- MONITORING STARTED (YAHOO FINANCE MODE) ---")
        self.send_telegram("🚀 Gold AI Bot is ONLINE (Yahoo Finance Mode)")

        while True:
            # 1. Fetching M5 data from Yahoo Finance safely
            try:
                df = yf.download(tickers=SYMBOL, period="5d", interval="5m", progress=False)
                
                if df is not None and not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    df = df.reset_index()
                    df.rename(columns={
                        'Datetime': 'time',
                        'Date': 'time',
                        'Open': 'open',
                        'High': 'high',
                        'Low': 'low',
                        'Close': 'close',
                        'Volume': 'tick_volume'
                    }, inplace=True)
                    df.columns = [str(c).lower() for c in df.columns]
                    if 'tick_volume' not in df.columns and 'volume' in df.columns:
                        df['tick_volume'] = df['volume']
                else:
                    print("[WARNING] Empty data received, retrying in 60 seconds...")
                    time.sleep(60)
                    continue
            except Exception as e:
                print(f"[ERROR] Fetching data failed: {e}")
                time.sleep(60)
                continue

            if not df.empty and len(df) > 100:
                
                # --- TECHNICAL ANALYSIS (ALL INTERNAL) ---
                try:
                    # A. Trend: LSMA (Linear Regression Moving Average)
                    df['lsma'] = ta.linreg(df['close'], length=73)
                    
                    # B. Volume Force: VFI (Using Tick Volume for stability)
                    vfi_res = ta.pvo(df['tick_volume'], fast=12, slow=26)
                    if isinstance(vfi_res, pd.DataFrame):
                        df['vfi'] = vfi_res.iloc[:, 0]
                    else:
                        df['vfi'] = vfi_res
                    
                    # C. Money Flow: MFI (Replacement for GLD confirmation)
                    df['mfi'] = ta.mfi(df['high'], df['low'], df['close'], df['tick_volume'], length=14)

                    # Get Current and Previous Values
                    last = df.iloc[-1]
                    prev = df.iloc[-2]
                    
                    price = last['close']
                    vfi = last['vfi']
                    mfi = last['mfi']
                    lsma = last['lsma']

                    # Console Status Output
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    print(f"[{timestamp}] GOLD: {price:.2f} | VFI: {vfi:.2f} | MFI: {mfi:.1f} | LSMA: {lsma:.2f}")

                    # --- SMART SIGNAL LOGIC ---
                    if price > lsma and vfi > 0 and mfi > 50:
                        if prev['close'] <= prev['lsma'] or prev['vfi'] <= 0:
                            msg = (f"🚀 GOLD BUY SIGNAL\n"
                                   f"Price: {price:.2f}\n"
                                   f"VFI: {vfi:.2f} (Positive)\n"
                                   f"MFI: {mfi:.1f} (Money In)")
                            print(">>> ALERT: BUY SIGNAL SENT")
                            self.send_telegram(msg)
                            time.sleep(300) # Wait 5 minutes to avoid duplicate alerts

                    elif price < lsma and vfi < 0 and mfi < 50:
                        if prev['close'] >= prev['lsma'] or prev['vfi'] >= 0:
                            msg = (f"📉 GOLD SELL SIGNAL\n"
                                   f"Price: {price:.2f}\n"
                                   f"VFI: {vfi:.2f} (Negative)\n"
                                   f"MFI: {mfi:.1f} (Money Out)")
                            print(">>> ALERT: SELL SIGNAL SENT")
                            self.send_telegram(msg)
                            time.sleep(300)
                except Exception as ta_err:
                    print(f"[ERROR] Technical analysis calculation error: {ta_err}")

            # Safe sleep interval of 60 seconds to protect CPU limit completely
            time.sleep(60)

if __name__ == "__main__":
    bot = GoldMasterUltra()
    bot.run_engine()
