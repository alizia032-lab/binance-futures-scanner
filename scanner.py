import os
import time
import requests

BASE = "https://fapi.binance.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def get_json(path, params=None):
    r = requests.get(BASE + path, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def ema(values, period):
    k = 2 / (period + 1)
    e = values[0]
    out = [e]
    for v in values[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out

def scan_symbol(symbol):
    # 4H candles
    k4 = get_json("/fapi/v1/klines", {
        "symbol": symbol,
        "interval": "4h",
        "limit": 80
    })

    # 15M candles
    k15 = get_json("/fapi/v1/klines", {
        "symbol": symbol,
        "interval": "15m",
        "limit": 80
    })

    if len(k4) < 60 or len(k15) < 30:
        return None

    # Ignore currently open candle
    c4 = k4[:-1]
    c15 = k15[:-1]

    close4 = [float(x[4]) for x in c4]
    close15 = [float(x[4]) for x in c15]

    ema20_4 = ema(close4, 20)[-1]
    ema50_4 = ema(close4, 50)[-1]
    last4 = close4[-1]

    # 4H trend
    bullish4 = last4 > ema20_4 > ema50_4
    bearish4 = last4 < ema20_4 < ema50_4

    if not bullish4 and not bearish4:
        return None

    # Last two CLOSED 15m candles
    prev = c15[-2]
    last = c15[-1]

    prev_open = float(prev[1])
    prev_high = float(prev[2])
    prev_low = float(prev[3])
    prev_close = float(prev[4])

    last_open = float(last[1])
    last_high = float(last[2])
    last_low = float(last[3])
    last_close = float(last[4])

    volumes = [float(x[5]) for x in c15[-21:-1]]
    avg_vol = sum(volumes) / len(volumes)
    last_vol = float(last[5])

    # Recent 20-candle resistance/support
    prior_high = max(float(x[2]) for x in c15[-22:-2])
    prior_low = min(float(x[3]) for x in c15[-22:-2])

    # LONG: breakout followed by successful retest
    long_breakout = prev_close > prior_high
    long_retest = (
        last_low <= prior_high * 1.003 and
        last_close > prior_high and
        last_close > last_open
    )

    # SHORT: breakdown followed by successful retest
    short_breakdown = prev_close < prior_low
    short_retest = (
        last_high >= prior_low * 0.997 and
        last_close < prior_low and
        last_close < last_open
    )

    volume_confirmed = last_vol >= avg_vol * 1.30

    if bullish4 and long_breakout and long_retest and volume_confirmed:
        entry = last_close
        sl = prior_high * 0.994
        risk = entry - sl

        if risk <= 0:
            return None

        return {
            "symbol": symbol,
            "side": "LONG",
            "entry": entry,
            "sl": sl,
            "tp1": entry + risk * 1.5,
            "tp2": entry + risk * 2.5,
            "score": 9
        }

    if bearish4 and short_breakdown and short_retest and volume_confirmed:
        entry = last_close
        sl = prior_low * 1.006
        risk = sl - entry

        if risk <= 0:
            return None

        return {
            "symbol": symbol,
            "side": "SHORT",
            "entry": entry,
            "sl": sl,
            "tp1": entry - risk * 1.5,
            "tp2": entry - risk * 2.5,
            "score": 9
        }

    return None

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials missing.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=15
    )

def main():
    info = get_json("/fapi/v1/exchangeInfo")

    symbols = []

    for s in info["symbols"]:
        if (
            s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
            and s["contractType"] == "PERPETUAL"
        ):
            symbols.append(s["symbol"])

    print(f"Scanning {len(symbols)} Binance Futures pairs...")

    setups = []

    for symbol in symbols:
        try:
            result = scan_symbol(symbol)

            if result:
                setups.append(result)
                print("SETUP:", result)

        except Exception as e:
            print(f"{symbol}: {e}")

        time.sleep(0.08)

    if not setups:
            print("NO CONFIRMED SETUPS")
            send_telegram("🔎 Binance Scanner: No confirmed setup right now.")
    if setups:
    for s in setups:
        message = (
            f"🚨 CONFIRMED {s['side']}\n"
            f"Pair: {s['symbol']}\n"
            f"Entry: {s['entry']}\n"
            f"SL: {s['sl']}\n"
            f"TP1: {s['tp1']}\n"
            f"TP2: {s['tp2']}\n"
            f"Score: {s['score']}/10"
        )
        send_telegram(message)
