# -*- coding: utf-8 -*-
"""
=================================================================================
  THE BEAST V2.0 - Institutional / Smart Money Concepts (SMC) Engine (GitHub Actions)
=================================================================================
  Target        : Gold (GC=F via yfinance)
  Stack         : yfinance + pandas + scikit-learn
  Core          : RandomForest (direction) + LinearRegression (micro-trend) + Divergence
=================================================================================
"""

import time
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import sys
import yfinance as yf

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LinearRegression

# =============================================================================
# CONFIG (OPTIMIZED FOR HIGH WIN-RATE & REGULAR DAILY SIGNALS)
# =============================================================================
TELEGRAM_TOKEN = "8462317233:AAENwGgJ4puoKhQSAWR0Dg3f5nCsPPqncUk"
CHAT_ID = "7432584346"
SYMBOL = "GC=F"                     # Gold Futures on yfinance

TF_ENTRY = "5m"                     # Execution timeframe set to 5m
BARS = 1200                         # bars pulled per timeframe

# --- AI / ENGINE ---
RF_ESTIMATORS = 500
RF_MAX_DEPTH = 20
RF_MIN_SAMPLES_LEAF = 3
MIN_TRAIN_SAMPLES = 250
MIN_BARS_TO_TRADE = 300

# --- BALANCED HIGH-ACCURACY GATES ---
RF_BUY_THRESHOLD = 0.55             # Optimal probability threshold for Buy
RF_SELL_THRESHOLD = 0.55            # Optimal probability threshold for Sell
MIN_CONFLUENCE = 3                  # Balanced Confluence (Exactly 3/6 required)

# --- SMC GEOMETRY ---
SWING_LEFT = 2                      # fractal strength (bars)
SWING_RIGHT = 2
OB_LOOKAHEAD = 5                    # bars allowed for displacement leg
OB_DISP_ATR = 0.8                   # displacement threshold (x ATR)
PD_LOOKBACK = 150                   # dealing-range window
LIQ_LOOKBACK = 12                   # bars defining the resting liquidity pool
LIQ_MIN_WICK_ATR = 0.10             # minimum excursion to count as a sweep
FVG_TOUCH_ATR = 0.35                # "inside / hugging" a gap tolerance
FEATURE_FALLBACK = 8.0              # value used when no live FVG/OB exists

# --- RISK MANAGEMENT ---
SL_ATR_MULT = 1.8                   # ATR-based stop
SL_MAX_ATR_MULT = 3.0               # hard cap
SL_STRUCT_BUFFER_ATR = 0.35         # buffer beyond the protective swing
TP1_R = 1.5                         # first target in R
TP2_MIN_R = 2.5                     # minimum runner target in R

# --- SESSIONS (UTC hours) ---
SESSION_OFFSET_HOURS = 0
ENABLE_LONDON = True
ENABLE_NEWYORK = True
ENABLE_OVERLAP = True
BLACKOUT_UTC = [(21, 23), (0, 1)]


# =============================================================================
# DATA RETRIEVAL ENGINE (YFINANCE)
# =============================================================================
def fetch_candles_yf(symbol, interval, period="5d"):
    """Fetch market data directly from Yahoo Finance."""
    try:
        df = yf.download(tickers=symbol, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            return None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.reset_index()
        time_col = 'Datetime' if 'Datetime' in df.columns else 'Date'
        
        df['time'] = (df[time_col].astype('int64') // 10**9).astype(int)
        
        df = df.rename(columns={
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'tick_volume'
        })
        
        df = df[['time', 'open', 'high', 'low', 'close', 'tick_volume']].copy()
        df = df.sort_values('time').reset_index(drop=True)
        return df
    except Exception as e:
        print(f"[YFINANCE ERROR] {e}")
        return None


# =============================================================================
# NATIVE REPLACEMENTS FOR PANDAS_TA
# =============================================================================
def native_linreg(series, length=73):
    def calc(x):
        slope, intercept = np.polyfit(np.arange(length), x, 1)
        return slope * (length - 1) + intercept
    return series.rolling(window=length).apply(calc, raw=True)

def native_mfi(high, low, close, volume, length=14):
    tp = (high + low + close) / 3
    rmf = tp * volume
    pos_flow = rmf.where(tp > tp.shift(1), 0.0).rolling(window=length).sum()
    neg_flow = rmf.where(tp < tp.shift(1), 0.0).rolling(window=length).sum()
    mfi = 100 - (100 / (1 + (pos_flow / (neg_flow + 1e-9))))
    return mfi


# =============================================================================
# FEATURE REGISTRY
# =============================================================================
FEATURES = [
    "log_ret", "vel", "er", "mfi", "rv", "lsma", "lsma_slope",
    "fvg_b_dist", "fvg_b_touch", "fvg_s_dist", "fvg_s_touch",
    "ob_b_dist", "ob_b_touch", "ob_s_dist", "ob_s_touch",
    "sweep_low", "sweep_high", "sweep_low_ago", "sweep_high_ago",
    "struct", "bos_up_age", "bos_dn_age", "choch_age",
    "liq_up_dist", "liq_dn_dist", "pd_pos", "disp", "impulse3",
    "atr_ratio", "squeeze", "atr_pct",
    "kz_score", "mfi_bias",
    "div_bull", "div_bear"
]

SPARSE_FEATURES = [
    "fvg_b_dist", "fvg_s_dist", "ob_b_dist", "ob_s_dist",
    "liq_up_dist", "liq_dn_dist",
]
DENSE_FEATURES = [c for c in FEATURES if c not in SPARSE_FEATURES]

BIG_AGE = 999


# =============================================================================
# UTILITIES
# =============================================================================
def wilder_atr(df, length=14):
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()

def _first_true(mask, start, default):
    seg = np.flatnonzero(mask[start:])
    return int(start + seg[0]) if seg.size else default

def _next_le(arr, default):
    n = len(arr)
    out = np.full(n, default, dtype=int)
    stack = []
    for i in range(n - 1, -1, -1):
        v = arr[i]
        while stack and arr[stack[-1]] > v:
            out[stack.pop()] = i
        stack.append(i)
    return out

def _next_ge(arr, default):
    n = len(arr)
    out = np.full(n, default, dtype=int)
    stack = []
    for i in range(n - 1, -1, -1):
        v = arr[i]
        while stack and arr[stack[-1]] < v:
            out[stack.pop()] = i
        stack.append(i)
    return out

def _ages(flags, n):
    idx = np.arange(n)
    last = np.maximum.accumulate(np.where(flags, idx, -1))
    return np.where(last >= 0, idx - last, BIG_AGE).astype(float)

def _f(value, default=0.0):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return default if (v != v) else v

def utc_now():
    return datetime.now(timezone.utc)


# =============================================================================
# SESSION ENGINE
# =============================================================================
def session_state(ts_utc):
    dt = datetime.fromtimestamp(int(ts_utc), tz=timezone.utc)
    hour = (dt.hour + dt.minute / 60.0 + SESSION_OFFSET_HOURS) % 24

    for lo, hi in BLACKOUT_UTC:
        if (lo <= hour < hi) if lo < hi else (hour >= lo or hour < hi):
            return "BLACKOUT", 0.0, True

    if ENABLE_OVERLAP and 13.5 <= hour < 16.0:
        return "LONDON/NY OVERLAP", 2.0, False
    if ENABLE_LONDON and 7.0 <= hour < 10.0:
        return "LONDON KZ", 1.0, False
    if ENABLE_NEWYORK and 12.0 <= hour < 15.0:
        return "NEW YORK KZ", 1.0, False
    if 0.0 <= hour < 5.0:
        return "ASIAN RANGE", 0.0, False
    return "OFF-SESSION", 0.0, False


# =============================================================================
# SMC ENGINE
# =============================================================================
def build_smc_features(df):
    df = df.reset_index(drop=True)
    n = len(df)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    opn = df["open"].to_numpy(dtype=float)

    df["atr"] = wilder_atr(df, 14)
    atr = df["atr"].to_numpy(dtype=float)
    if np.isnan(atr).all():
        atr = np.full(n, 1e-6)
    atr = np.where(np.isnan(atr), np.nanmedian(atr), atr)
    atr = np.where(atr <= 0, 1e-6, atr)
    df["atr"] = atr

    df["lsma"] = native_linreg(df["close"], length=73)
    direction = (df["close"] - df["close"].shift(10)).abs()
    noise = (df["close"] - df["close"].shift(1)).abs().rolling(window=10).sum()
    df["er"] = (direction / (noise + 1e-6)).clip(lower=0.0, upper=1.0)
    df["mfi"] = native_mfi(df["high"], df["low"], df["close"], df["tick_volume"], length=14)
    df["rv"] = df["tick_volume"] / (df["tick_volume"].rolling(window=20).mean() + 1e-6)
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
    df["vel"] = df["log_ret"].diff()
    df["lsma_slope"] = (df["lsma"] - df["lsma"].shift(10)) / atr

    df["div_bull"] = ((df["low"] < df["low"].shift(4)) & (df["mfi"] > df["mfi"].shift(4))).astype(float)
    df["div_bear"] = ((df["high"] > df["high"].shift(4)) & (df["mfi"] < df["mfi"].shift(4))).astype(float)

    L, R = SWING_LEFT, SWING_RIGHT
    roll_h = pd.Series(high).rolling(L + R + 1).max().shift(-R)
    roll_l = pd.Series(low).rolling(L + R + 1).min().shift(-R)
    sh_raw = ((high >= roll_h.to_numpy()) & roll_h.notna().to_numpy())
    sl_raw = ((low <= roll_l.to_numpy()) & roll_l.notna().to_numpy())
    sh_raw = sh_raw & (high > np.roll(high, 1))
    sl_raw = sl_raw & (low < np.roll(low, 1))
    sh_raw[:1] = False
    sl_raw[:1] = False
    sh_c = np.roll(sh_raw, R)
    sl_c = np.roll(sl_raw, R)
    sh_c[:R] = False
    sl_c[:R] = False

    last_high = pd.Series(np.where(sh_c, high, np.nan)).ffill().to_numpy()
    last_low = pd.Series(np.where(sl_c, low, np.nan)).ffill().to_numpy()
    df["last_swing_high"] = last_high
    df["last_swing_low"] = last_low

    struct = np.zeros(n)
    bos_up = np.zeros(n, dtype=bool)
    bos_dn = np.zeros(n, dtype=bool)
    choch_up = np.zeros(n, dtype=bool)
    choch_dn = np.zeros(n, dtype=bool)
    up_armed = dn_armed = False
    up_lvl = dn_lvl = np.nan
    for i in range(n):
        if sh_c[i]:
            up_lvl, up_armed = high[i], True
        if sl_c[i]:
            dn_lvl, dn_armed = low[i], True
        prev = struct[i - 1] if i else 0
        if up_armed and not np.isnan(up_lvl) and close[i] > up_lvl:
            up_armed = False
            if prev > 0:
                bos_up[i] = True
            else:
                choch_up[i] = True
            struct[i] = 1
        elif dn_armed and not np.isnan(dn_lvl) and close[i] < dn_lvl:
            dn_armed = False
            if prev < 0:
                bos_dn[i] = True
            else:
                choch_dn[i] = True
            struct[i] = -1
        else:
            struct[i] = prev
    df["struct"] = struct
    df["bos_up_age"] = _ages(bos_up, n)
    df["bos_dn_age"] = _ages(bos_dn, n)
    df["choch_age"] = _ages(choch_up | choch_dn, n)

    fvg_bull = np.zeros(n, dtype=bool)
    fvg_bear = np.zeros(n, dtype=bool)
    fvg_bull[2:] = low[2:] > high[:-2]
    fvg_bear[2:] = high[2:] < low[:-2]

    fvg_b_dist = np.full(n, np.nan)
    fvg_s_dist = np.full(n, np.nan)
    fvg_b_touch = np.zeros(n)
    fvg_s_touch = np.zeros(n)

    fill_up = _next_le(low, n)
    fill_dn = _next_ge(high, n)
    for j in np.flatnonzero(fvg_bull):
        top, bottom = low[j], high[j - 2]
        sl = slice(j, max(int(fill_up[j]), j + 1))
        c = close[sl]
        inside = (c <= top) & (c >= bottom)
        above = c > top
        d = np.where(inside, 0.0, np.where(above, (c - top) / atr[sl], np.nan))
        fvg_b_dist[sl] = np.fmin(fvg_b_dist[sl], d)
        fvg_b_touch[sl] = np.fmax(fvg_b_touch[sl], (inside | (d <= FVG_TOUCH_ATR)).astype(float))

    for j in np.flatnonzero(fvg_bear):
        top, bottom = high[j], low[j - 2]
        sl = slice(j, max(int(fill_dn[j]), j + 1))
        c = close[sl]
        inside = (c >= top) & (c <= bottom)
        below = c < top
        d = np.where(inside, 0.0, np.where(below, (top - c) / atr[sl], np.nan))
        fvg_s_dist[sl] = np.fmin(fvg_s_dist[sl], d)
        fvg_s_touch[sl] = np.fmax(fvg_s_touch[sl], (inside | (d <= FVG_TOUCH_ATR)).astype(float))

    df["fvg_b_dist"] = fvg_b_dist
    df["fvg_s_dist"] = fvg_s_dist
    df["fvg_b_touch"] = fvg_b_touch
    df["fvg_s_touch"] = fvg_s_touch

    ob_b_dist = np.full(n, np.nan)
    ob_s_dist = np.full(n, np.nan)
    ob_b_touch = np.zeros(n)
    ob_s_touch = np.zeros(n)

    for i in range(n - 1):
        hi_i, lo_i = high[i], low[i]
        for k in range(i + 1, min(i + 1 + OB_LOOKAHEAD, n)):
            if close[i] < opn[i] and high[k] > hi_i and (high[k] - close[i]) > OB_DISP_ATR * atr[k]:
                end = _first_true((close > hi_i + 0.5 * atr) | (close < lo_i - 0.5 * atr), k + 1, n)
                sl = slice(k, end)
                c = close[sl]
                inside = (c <= hi_i) & (c >= lo_i)
                above = c > hi_i
                d = np.where(inside, 0.0, np.where(above, (c - hi_i) / atr[sl], np.nan))
                ob_b_dist[sl] = np.fmin(ob_b_dist[sl], d)
                ob_b_touch[sl] = np.fmax(ob_b_touch[sl], (inside | (d <= FVG_TOUCH_ATR)).astype(float))
                break
            if close[i] > opn[i] and low[k] < lo_i and (opn[i] - low[k]) > OB_DISP_ATR * atr[k]:
                end = _first_true((close < lo_i - 0.5 * atr) | (close > hi_i + 0.5 * atr), k + 1, n)
                sl = slice(k, end)
                c = close[sl]
                inside = (c >= lo_i) & (c <= hi_i)
                below = c < lo_i
                d = np.where(inside, 0.0, np.where(below, (lo_i - c) / atr[sl], np.nan))
                ob_s_dist[sl] = np.fmin(ob_s_dist[sl], d)
                ob_s_touch[sl] = np.fmax(ob_s_touch[sl], (inside | (d <= FVG_TOUCH_ATR)).astype(float))
                break

    df["ob_b_dist"] = ob_b_dist
    df["ob_s_dist"] = ob_s_dist
    df["ob_b_touch"] = ob_b_touch
    df["ob_s_touch"] = ob_s_touch

    pool_dn = pd.Series(low).rolling(LIQ_LOOKBACK).min().shift(1).to_numpy()
    pool_up = pd.Series(high).rolling(LIQ_LOOKBACK).max().shift(1).to_numpy()
    have_pool = ~np.isnan(pool_dn) & ~np.isnan(pool_up)
    sweep_low = have_pool & (low < pool_dn - LIQ_MIN_WICK_ATR * atr) & (close > pool_dn)
    sweep_high = have_pool & (high > pool_up + LIQ_MIN_WICK_ATR * atr) & (close < pool_up)
    df["sweep_low"] = sweep_low.astype(float)
    df["sweep_high"] = sweep_high.astype(float)
    df["sweep_low_ago"] = _ages(sweep_low, n)
    df["sweep_high_ago"] = _ages(sweep_high, n)

    df["liq_up_level"] = pool_up
    df["liq_dn_level"] = pool_dn
    df["liq_up_dist"] = (pool_up - close) / atr
    df["liq_dn_dist"] = (close - pool_dn) / atr

    dr_high = pd.Series(high).rolling(PD_LOOKBACK).max().to_numpy()
    dr_low = pd.Series(low).rolling(PD_LOOKBACK).min().to_numpy()
    span = np.where((dr_high - dr_low) > 0, dr_high - dr_low, np.nan)
    df["pd_pos"] = np.clip((close - dr_low) / span, 0.0, 1.0)

    df["disp"] = (df["close"] - df["open"]) / atr
    df["impulse3"] = (df["close"] - df["close"].shift(3)) / atr
    df["atr_sma"] = pd.Series(atr).rolling(50).mean()
    df["atr_ratio"] = atr / (df["atr_sma"] + 1e-9)
    mid = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std()
    bbw = (4.0 * std) / (mid + 1e-9)
    q20 = bbw.rolling(200, min_periods=50).quantile(0.20)
    df["squeeze"] = (bbw < q20).astype(float).fillna(0.0)
    df["atr_pct"] = atr / (df["close"] + 1e-9)

    times = df["time"].to_numpy()
    labels, kz, blackout = [], [], []
    for t in times:
        lab, score, blk = session_state(t)
        labels.append(lab)
        kz.append(score)
        blackout.append(blk)
    df["session"] = labels
    df["kz_score"] = kz
    df["mfi_bias"] = (df["mfi"].fillna(50.0) - 50.0) / 50.0
    df["blackout"] = np.asarray(blackout, dtype=float)

    fwd = df["close"].shift(-3)
    df["target"] = ((fwd - df["close"]) > 0.25 * atr).astype(float)
    df = df.iloc[:-3]
    df = df.replace([np.inf, -np.inf], np.nan)
    for col in SPARSE_FEATURES:
        df[col] = df[col].fillna(FEATURE_FALLBACK)
    df = df.dropna(subset=DENSE_FEATURES + ["target"]).reset_index(drop=True)
    df[DENSE_FEATURES] = df[DENSE_FEATURES].fillna(0.0)
    return df


# =============================================================================
# RISK MANAGER
# =============================================================================
class RiskManager:
    @staticmethod
    def plan(side, price, atr, row, digits=2):
        if side == "BUY":
            swing = _f(row.get("last_swing_low"), 0.0)
            sl = price - SL_ATR_MULT * atr
            if swing > 0:
                sl = min(sl, swing - SL_STRUCT_BUFFER_ATR * atr)
            sl = max(sl, price - SL_MAX_ATR_MULT * atr)
            risk = max(price - sl, 0.05 * atr)
            tp1 = price + risk * TP1_R
            liq = _f(row.get("liq_up_level"), 0.0)
            tp2 = liq if 0 < (liq - price) < risk * TP2_MIN_R else price + risk * TP2_MIN_R
        else:
            swing = _f(row.get("last_swing_high"), 0.0)
            sl = price + SL_ATR_MULT * atr
            if swing > 0:
                sl = max(sl, swing + SL_STRUCT_BUFFER_ATR * atr)
            sl = min(sl, price + SL_MAX_ATR_MULT * atr)
            risk = max(sl - price, 0.05 * atr)
            tp1 = price - risk * TP1_R
            liq = _f(row.get("liq_dn_level"), 0.0)
            tp2 = liq if 0 < (price - liq) < risk * TP2_MIN_R else price - risk * TP2_MIN_R

        px, sl_r, tp1_r, tp2_r = (round(v, digits) for v in (price, sl, tp1, tp2))
        risk_r = abs(px - sl_r) or risk
        return {
            "sl": sl_r,
            "tp1": tp1_r,
            "tp2": tp2_r,
            "risk": risk_r,
            "rr1": abs(tp1_r - px) / risk_r,
            "rr2": abs(tp2_r - px) / risk_r,
        }


# =============================================================================
# THE BEAST ENGINE (BALANCED FOR ACCURACY & SIGNALS)
# =============================================================================
class TradingBeast:
    def __init__(self):
        print("--- [SYSTEM] THE BEAST V2.0 INITIALIZED (ACCURATE DAILY SIGNALS) ---")
        self.rf_model = RandomForestClassifier(
            n_estimators=RF_ESTIMATORS,
            max_depth=RF_MAX_DEPTH,
            min_samples_leaf=RF_MIN_SAMPLES_LEAF,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        self.risk = RiskManager()
        self.digits = 2

    def send_telegram(self, msg):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}&parse_mode=Markdown"
            requests.get(url, timeout=5)
        except Exception as e:
            print(f"[TELEGRAM ERROR] {e}")

    def run_cycle(self):
        df_m5 = fetch_candles_yf(SYMBOL, interval=TF_ENTRY, period="5d")

        if df_m5 is None or len(df_m5) < MIN_BARS_TO_TRADE:
            print("[WARN] Waiting for sufficient M5 market data...")
            return

        merged = build_smc_features(df_m5)

        if len(merged) < MIN_TRAIN_SAMPLES:
            print("[WARN] Not enough training samples.")
            return

        X = merged[FEATURES]
        y = merged["target"]
        self.rf_model.fit(X, y)
        rf_classes = {cls: idx for idx, cls in enumerate(self.rf_model.classes_)}

        latest = merged.iloc[-2]
        price = latest["close"]
        atr = latest["atr"]

        X_curr = merged[FEATURES].iloc[[-2]]
        probs = self.rf_model.predict_proba(X_curr)[0]
        prob_buy = probs[rf_classes.get(1.0, 1)]
        prob_sell = probs[rf_classes.get(0.0, 0)]

        confluence_buy = sum([
            latest["struct"] > 0,
            latest["fvg_b_touch"] > 0,
            latest["ob_b_touch"] > 0,
            latest["sweep_low"] > 0,
            latest["pd_pos"] < 0.5,
            latest["div_bull"] > 0
        ])

        confluence_sell = sum([
            latest["struct"] < 0,
            latest["fvg_s_touch"] > 0,
            latest["ob_s_touch"] > 0,
            latest["sweep_high"] > 0,
            latest["pd_pos"] > 0.5,
            latest["div_bear"] > 0
        ])

        print(f"[{utc_now().strftime('%H:%M:%S')}] GOLD: ${price:.2f} | Buy Prob: {prob_buy:.2f} (Conf: {confluence_buy}) | Sell Prob: {prob_sell:.2f} (Conf: {confluence_sell})")

        if prob_buy >= RF_BUY_THRESHOLD and confluence_buy >= MIN_CONFLUENCE:
            p = self.risk.plan("BUY", price, atr, latest, digits=self.digits)
            msg = (
                f"🚀 *THE BEAST BUY SIGNAL (XAUUSD)*\n\n"
                f"📈 *Entry:* `{price}`\n"
                f"🛑 *Stop Loss:* `{p['sl']}`\n"
                f"🎯 *Target 1:* `{p['tp1']}`\n"
                f"🏆 *Target 2:* `{p['tp2']}`\n\n"
                f"🤖 *AI Confidence:* `{prob_buy:.2f}`\n"
                f"⚡ *SMC Confluence:* `{confluence_buy}/6`"
            )
            print(msg)
            self.send_telegram(msg)

        elif prob_sell >= RF_SELL_THRESHOLD and confluence_sell >= MIN_CONFLUENCE:
            p = self.risk.plan("SELL", price, atr, latest, digits=self.digits)
            msg = (
                f"🔻 *THE BEAST SELL SIGNAL (XAUUSD)*\n\n"
                f"📉 *Entry:* `{price}`\n"
                f"🛑 *Stop Loss:* `{p['sl']}`\n"
                f"🎯 *Target 1:* `{p['tp1']}`\n"
                f"🏆 *Target 2:* `{p['tp2']}`\n\n"
                f"🤖 *AI Confidence:* `{prob_sell:.2f}`\n"
                f"⚡ *SMC Confluence:* `{confluence_sell}/6`"
            )
            print(msg)
            self.send_telegram(msg)
        else:
            print("ℹ️ Setup in progress. Waiting for 3/6 confluence match.")

    def start(self):
        print("🚀 Executing high-accuracy single cycle...")
        try:
            self.run_cycle()
        except Exception as e:
            print(f"[RUNTIME ERROR] {e}")
            traceback.print_exc()
        print("🏁 Cycle completed.")


if __name__ == "__main__":
    bot = TradingBeast()
    bot.start()
