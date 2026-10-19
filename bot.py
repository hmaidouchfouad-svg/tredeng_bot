import os
import sys
import pandas as pd
import requests
import yfinance as yf


def send_telegram_alert(message):
  """Send alert directly to Telegram"""
  token = os.environ.get('TELEGRAM_TOKEN')
  chat_id = os.environ.get('TELEGRAM_CHAT_ID')

  if not token or not chat_id:
    print('[-] Telegram configuration missing.')
    return

  url = f'https://api.telegram.org/bot{token}/sendMessage'
  payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}

  try:
    response = requests.post(url, json=payload, timeout=10)
    if response.status_code == 200:
      print('[+] Alert sent to Telegram.')
  except Exception as e:
    print(f'[-] Error sending Telegram alert: {e}')


def run_institutional_quant_bot():
  # رسالة تأكيد البدء لتتأكد فوراً أن التليجرام متصل ويشتغل
  startup_msg = (
      '🚀 *[Institutional Bot Started]*\n\n'
      '• Asset: `Gold (GC=F)`\n'
      '• Status: Online and scanning market data...\n'
      '• Mode: Active institutional quantitative filters.'
  )
  send_telegram_alert(startup_msg)

  # 1. Fetch 5-minute Gold data
  df = yf.download(
      'GC=F', period='5d', interval='5m', progress=False, auto_adjust=True
  )

  if df.empty:
    print('[-] No data fetched from yfinance.')
    return

  if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

  # 2. Exclude the live/unclosed candle
  df = df.iloc[:-1]

  if len(df) < 30:
    print('[-] Not enough closed candles.')
    return

  # 3. Volume Z-Score calculation
  window = 20
  df['Vol_Mean'] = df['Volume'].rolling(window=window).mean()
  df['Vol_Std'] = df['Volume'].rolling(window=window).std()
  df['Volume_ZScore'] = (df['Volume'] - df['Vol_Mean']) / df['Vol_Std']

  # 4. Estimated Delta and Cumulative Delta Flow
  candle_range = df['High'] - df['Low']
  df['Pressure'] = (
      (2 * df['Close'] - df['High'] - df['Low']) / candle_range
  ).fillna(0)
  df['Estimated_Delta'] = df['Volume'] * df['Pressure']
  df['Cumulative_Delta'] = df['Estimated_Delta'].rolling(window=10).sum()

  # 5. Trend Persistence
  df['Trend_Persistence'] = (df['Close'] > df['Close'].shift(1)).rolling(
      window=3
  ).sum()

  # Read latest closed candle
  latest = df.iloc[-1]
  current_price = float(latest['Close'])
  z_score = float(latest['Volume_ZScore'])
  cum_delta = float(latest['Cumulative_Delta'])
  persistence = int(latest['Trend_Persistence'])

  print(
      f'[+] Analysis complete. Price: {current_price}, Z-Score: {z_score:.2f}'
  )

  # 6. Trade Decision Logic Gate
  if z_score > 2.5:
    # Bullish setup
    if cum_delta > 0 and persistence >= 2:
      msg = (
          '🟢 *[Bullish Institutional Signal]*\n\n'
          f'• Asset: `Gold (GC=F)`\n'
          f'• Price: `{current_price:.2f}`\n'
          f'• Z-Score: `{z_score:.2f}`\n'
          f'• Cumulative Delta: Bullish (`{cum_delta:.2f}`)\n\n'
          '💡 *Decision:* Confirmed institutional buying.'
      )
      send_telegram_alert(msg)

    # Bearish setup
    elif cum_delta < 0 and persistence <= 1:
      msg = (
          '🔴 *[Bearish Institutional Signal]*\n\n'
          f'• Asset: `Gold (GC=F)`\n'
          f'• Price: `{current_price:.2f}`\n'
          f'• Z-Score: `{z_score:.2f}`\n'
          f'• Cumulative Delta: Bearish (`{cum_delta:.2f}`)\n\n'
          '💡 *Decision:* Confirmed institutional selling pressure.'
      )
      send_telegram_alert(msg)


if __name__ == '__main__':
  run_institutional_quant_bot()
