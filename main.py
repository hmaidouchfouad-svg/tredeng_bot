import os
import sys
import pandas as pd
import requests
import yfinance as yf


def send_telegram_alert(message):
  """Sends an alert directly to Telegram using environment variables."""
  token = os.environ.get("TELEGRAM_TOKEN")
  chat_id = os.environ.get("TELEGRAM_CHAT_ID")

  if not token or not chat_id:
    print(
        "[-] Telegram configuration missing: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID"
        " not found."
    )
    return

  url = f"https://api.telegram.org/bot{token}/sendMessage"
  payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}

  try:
    response = requests.post(url, json=payload, timeout=10)
    if response.status_code == 200:
      print("[+] Telegram alert sent successfully.")
    else:
      print(f"[-] Failed to send Telegram alert: {response.text}")
  except Exception as e:
    print(f"[-] Error connecting to Telegram: {e}")


def run_institutional_quant_bot():
  print(
      "[*] Fetching Gold (GC=F) 5-minute data and running institutional"
      " quantitative analysis..."
  )

  # 1. Fetch 5-minute data for the last 5 days
  df = yf.download(
      "GC=F", period="5d", interval="5m", progress=False, auto_adjust=True
  )

  if df.empty:
    print("[-] Error: No market data retrieved.")
    return

  # Flatten MultiIndex columns if necessary
  if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_0

  # 2. Exclude the live/unclosed candle to avoid latency artifacts
  df = df.iloc[:-1]

  if len(df) < 30:
    print("[-] Error: Insufficient data points for statistical calculation.")
    return

  # 3. Calculate Volume Z-Score (20-period rolling window)
  window = 20
  df["Vol_Mean"] = df["Volume"].rolling(window=window).mean()
  df["Vol_Std"] = df["Volume"].rolling(window=window).std()
  df["Volume_ZScore"] = (df["Volume"] - df["Vol_Mean"]) / df["Vol_Std"]

  # 4. Calculate Estimated Delta Proxy within the candle
  candle_range = df["High"] - df["Low"]
  df["Pressure"] = (
      (2 * df["Close"] - df["High"] - df["Low"]) / candle_range
  ).fillna(0)
  df["Estimated_Delta"] = df["Volume"] * df["Pressure"]

  # 5. Cumulative Delta Flow (10-period rolling window)
  df["Cumulative_Delta"] = df["Estimated_Delta"].rolling(window=10).sum()

  # 6. State Persistence (trend check over last 3 closed candles)
  df["Trend_Persistence"] = (df["Close"] > df["Close"].shift(1)).rolling(
      window=3
  ).sum()

  # Get the latest fully closed candle metrics
  latest = df.iloc[-1]
  current_price = float(latest["Close"])
  z_score = float(latest["Volume_ZScore"])
  cum_delta = float(latest["Cumulative_Delta"])
  persistence = int(latest["Trend_Persistence"])

  print(f"[*] Latest Closed Gold Price: {current_price:.2f}")
  print(f"[*] Volume Z-Score: {z_score:.2f}")
  print(f"[*] Cumulative Delta: {cum_delta:.2f}")
  print(f"[*] Trend Persistence: {persistence}")

  # 7. Rigorous Decision Logic Gate
  alert_msg = ""

  if z_score > 2.5:
    # Bullish Institutional Accumulation / Continuation
    if cum_delta > 0 and persistence >= 2:
      alert_msg = (
          "🟢 *[Confirmed Bullish Institutional Footprint]*\n\n"
          f"• Asset: `Gold (GC=F)`\n"
          f"• Closed Price: `{current_price:.2f}`\n"
          f"• Volume Z-Score: `{z_score:.2f}`\n"
          f"• Cumulative Delta: Strong Bullish (`{cum_delta:.2f}`)\n\n"
          "💡 *Decision:* Institutional buying pressure confirmed. True"
          " trend continuation."
      )
      print("[+] " + alert_msg)
      send_telegram_alert(alert_msg)

    # Bearish Institutional Distribution / Continuation
    elif cum_delta < 0 and persistence <= 1:
      alert_msg = (
          "🔴 *[Confirmed Bearish Institutional Footprint]*\n\n"
          f"• Asset: `Gold (GC=F)`\n"
          f"• Closed Price: `{current_price:.2f}`\n"
          f"• Volume Z-Score: `{z_score:.2f}`\n"
          f"• Cumulative Delta: Strong Bearish (`{cum_delta:.2f}`)\n\n"
          "💡 *Decision:* Institutional selling pressure confirmed. True"
          " downward continuation."
      )
      print("[+] " + alert_msg)
      send_telegram_alert(alert_msg)

    else:
      print(
          "[!] Warning: High volume detected, but cumulative delta/persistence"
          " do not align (Likely Liquidity Trap / Fakeout). Signal ignored."
      )
  else:
    print("[-] Market is in a quiet regime. No institutional footprint.")


if __name__ == "__main__":
  run_institutional_quant_bot()
