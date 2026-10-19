import os
import sys
import pandas as pd
import requests
import yfinance as yf


def send_telegram_alert(message):
  """إرسال التنبيه مباشرة إلى Telegram"""
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
  # 1. جلب بيانات الذهب 5 دقائق
  df = yf.download(
      'GC=F', period='5d', interval='5m', progress=False, auto_adjust=True
  )

  if df.empty:
    print('[-] No data fetched from yfinance.')
    return

  if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

  # 2. استبعاد الشمعة الحية الجارية لتفادي أخطاء التأخير
  df = df.iloc[:-1]

  if len(df) < 30:
    print('[-] Not enough closed candles.')
    return

  # 3. حساب الفوليوم Z-Score
  window = 20
  df['Vol_Mean'] = df['Volume'].rolling(window=window).mean()
  df['Vol_Std'] = df['Volume'].rolling(window=window).std()
  df['Volume_ZScore'] = (df['Volume'] - df['Vol_Mean']) / df['Vol_Std']

  # 4. حساب الدلتا التقريبية والتدفق التراكمي
  candle_range = df['High'] - df['Low']
  df['Pressure'] = (
      (2 * df['Close'] - df['High'] - df['Low']) / candle_range
  ).fillna(0)
  df['Estimated_Delta'] = df['Volume'] * df['Pressure']
  df['Cumulative_Delta'] = df['Estimated_Delta'].rolling(window=10).sum()

  # 5. استمرارية الاتجاه (State Persistence)
  df['Trend_Persistence'] = (df['Close'] > df['Close'].shift(1)).rolling(
      window=3
  ).sum()

  # قراءة الشمعة المغلقة الأخيرة
  latest = df.iloc[-1]
  current_price = float(latest['Close'])
  z_score = float(latest['Volume_ZScore'])
  cum_delta = float(latest['Cumulative_Delta'])
  persistence = int(latest['Trend_Persistence'])

  print(
      f'[+] Analysis complete. Price: {current_price}, Z-Score: {z_score:.2f}'
  )

  # 6. فلترة الصفقات وإرسال التنبيه فقط عند وجود إشارة مؤكدة
  if z_score > 2.5:
    # صفقة شراء مؤكدة
    if cum_delta > 0 and persistence >= 2:
      msg = (
          '🟢 *[إشارة شراء مؤسساتية مؤكدة]*\n\n'
          f'• الأصل: `Gold (GC=F)`\n'
          f'• السعر: `{current_price:.2f}`\n'
          f'• Z-Score: `{z_score:.2f}`\n'
          f'• التدفق التراكمي: صاعد (`{cum_delta:.2f}`)\n\n'
          '💡 *القرار:* دخول حيتان حقيقي.'
      )
      send_telegram_alert(msg)

    # صفقة بيع مؤكدة
    elif cum_delta < 0 and persistence <= 1:
      msg = (
          '🔴 *[إشارة بيع مؤسساتية مؤكدة]*\n\n'
          f'• الأصل: `Gold (GC=F)`\n'
          f'• السعر: `{current_price:.2f}`\n'
          f'• Z-Score: `{z_score:.2f}`\n'
          f'• التدفق التراكمي: هابط (`{cum_delta:.2f}`)\n\n'
          '💡 *القرار:* ضغط بيعي مؤسساتي حقيقي.'
      )
      send_telegram_alert(msg)


if __name__ == '__main__':
  run_institutional_quant_bot()
