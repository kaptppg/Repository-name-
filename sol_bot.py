# sol_bot.py - SOL 極致策略（Render 版）
import yfinance as yf
import pandas as pd
import numpy as np
from pybit.unified_trading import HTTP
from datetime import datetime
import requests
import os

# ═══════════════════════════════════════════════════════════════
# 設定（從環境變數讀取，更安全）
# ═══════════════════════════════════════════════════════════════

BYBIT_API_KEY = os.environ.get("BYBIT_API_KEY", "你的API_KEY")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "你的SECRET_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

SYMBOL = "SOLUSDT"
LEVERAGE = 2
POSITION_RATIO = 0.3

TREND_THRESHOLD = 5
ADX_MIN = 10
ATR_MAX = 0.20

# ═══════════════════════════════════════════════════════════════
# 策略函數（精簡版）
# ═══════════════════════════════════════════════════════════════

def calculate_adx(df, period=14):
    high, low, close = df['High'], df['Low'], df['Close']
    plus_dm = high.diff().clip(lower=0)
    minus_dm = low.diff().abs().clip(lower=0)
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx, atr

def get_sol_signal():
    try:
        sol = yf.download('SOL-USD', period='5d', interval='1h', progress=False)
        if len(sol) < 50:
            return None
        if isinstance(sol.columns, pd.MultiIndex):
            sol.columns = sol.columns.get_level_values(0)
        
        sol['ema10'] = sol['Close'].ewm(span=10).mean()
        sol['ema21'] = sol['Close'].ewm(span=21).mean()
        sol['ema50'] = sol['Close'].ewm(span=50).mean()
        sol['mom3'] = sol['Close'].pct_change(3)
        sol['mom10'] = sol['Close'].pct_change(10)
        
        adx_series, atr_series = calculate_adx(sol)
        sol['adx'] = adx_series
        sol['atr'] = atr_series
        sol['atr_ratio'] = sol['atr'] / sol['Close']
        
        sol['trend_score'] = (
            (sol['ema10'] > sol['ema21']) * 40 +
            (sol['Close'] > sol['ema50']) * 30 +
            (sol['mom3'] > 0) * 20 +
            (sol['mom10'] > 0) * 10
        ) - 50
        
        latest = sol.iloc[-1]
        
        long_signal = (latest['trend_score'] > TREND_THRESHOLD) and \
                      (latest['adx'] > ADX_MIN) and \
                      (latest['atr_ratio'] < ATR_MAX)
        short_signal = (latest['trend_score'] < -TREND_THRESHOLD) and \
                       (latest['adx'] > ADX_MIN) and \
                       (latest['atr_ratio'] < ATR_MAX)
        
        return {
            'price': float(latest['Close']),
            'trend_score': float(latest['trend_score']),
            'adx': float(latest['adx']),
            'atr_ratio': float(latest['atr_ratio']),
            'signal': 'BUY' if long_signal else ('SELL' if short_signal else None),
            'signal_text': '📈 做多' if long_signal else ('📉 做空' if short_signal else '⏸️ 觀望')
        }
    except Exception as e:
        print(f"錯誤: {e}")
        return None

def send_telegram(msg):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
        except:
            pass

def place_order(side):
    """下單到 Bybit"""
    try:
        session = HTTP(demo=True, api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET)
        
        # 獲取餘額
        resp = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        balance = float(resp['result']['list'][0]['coin'][0]['walletBalance'])
        
        # 計算數量
        price_resp = session.get_tickers(category="linear", symbol=SYMBOL)
        price = float(price_resp['result']['list'][0]['lastPrice'])
        
        order_usdt = balance * POSITION_RATIO
        qty = round(order_usdt / price, 2)
        
        # 下單
        resp = session.place_order(
            category="linear",
            symbol=SYMBOL,
            side=side,
            orderType="Market",
            qty=str(qty),
            positionIdx=0,
        )
        
        if resp['retCode'] == 0:
            return True, f"✅ 下單成功: {side} {qty} SOL @ ${price:.2f}"
        else:
            return False, f"❌ 下單失敗: {resp['retMsg']}"
    except Exception as e:
        return False, f"❌ 錯誤: {e}"

# ═══════════════════════════════════════════════════════════════
# 主程式
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 檢查 SOL 信號...")
    
    result = get_sol_signal()
    
    if result:
        msg = f"""
📊 SOL 策略信號
━━━━━━━━━━━━━━━━━
價格: ${result['price']:.2f}
趨勢分數: {result['trend_score']:.0f}
ADX: {result['adx']:.1f}
ATR比率: {result['atr_ratio']:.1%}
信號: {result['signal_text']}
━━━━━━━━━━━━━━━━━
        """
        print(msg)
        send_telegram(msg)
        
        if result['signal']:
            success, order_msg = place_order(result['signal'])
            print(order_msg)
            send_telegram(order_msg)
    else:
        print("❌ 無法獲取信號")
