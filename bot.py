import websocket
import threading
import json
import time
import schedule
import datetime
import pytz
import os
from dotenv import load_dotenv
import requests
import re
from collections import defaultdict

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DERIV_APP_ID = os.getenv("DERIV_APP_ID")
BOT_IMAGE_URL = os.getenv("IMAGE_URL")
UNDER6_BOT_PATH = os.getenv("UNDER6_BOT_PATH")
OVER3_BOT_PATH = os.getenv("OVER3_BOT_PATH")

MARKET_NAMES = {
    "R_10": "Volatility 10 Index",
    "R_25": "Volatility 25 Index",
    "R_50": "Volatility 50 Index",
    "R_75": "Volatility 75 Index",
    "R_100": "Volatility 100 Index"
}

SYNTHETIC_SYMBOLS = list(MARKET_NAMES.keys())
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
TICK_COUNT = 5000
SIGNAL_VALID_MINUTES = 5

cached_signal = None

def escape_markdown(text):
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\\-])', r'\\\1', str(text))

def send_telegram_message(message, image_url=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto" if image_url else f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "parse_mode": "MarkdownV2"
    }
    if image_url:
        payload["photo"] = image_url
        payload["caption"] = message
    else:
        payload["text"] = message
    try:
        response = requests.post(url, json=payload)
        return response.json().get("result", {}).get("message_id")
    except:
        return None

def send_telegram_document(caption, filepath):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        with open(filepath, 'rb') as f:
            files = {'document': f}
            payload = {
                "chat_id": CHAT_ID,
                "caption": caption,
                "parse_mode": "MarkdownV2"
            }
            response = requests.post(url, data=payload, files=files)
            return response.json().get("result", {}).get("message_id")
    except:
        return None

def delete_telegram_message(message_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
    payload = {
        "chat_id": CHAT_ID,
        "message_id": message_id
    }
    try:
        requests.post(url, json=payload)
    except:
        pass

def analyze_ticks(ticks):
    under6_counts = defaultdict(int)
    over3_counts = defaultdict(int)

    for i in range(1, len(ticks)):
        current = ticks[i]
        previous = ticks[i - 1]
        if current < 6:
            under6_counts[previous] += 1
        if current > 3:
            over3_counts[previous] += 1

    best_under6 = max(under6_counts.items(), key=lambda x: x[1], default=(None, 0))
    best_over3 = max(over3_counts.items(), key=lambda x: x[1], default=(None, 0))

    total_under6 = sum(under6_counts.values())
    total_over3 = sum(over3_counts.values())

    under6_prob = (best_under6[1] / total_under6) * 100 if total_under6 else 0
    over3_prob = (best_over3[1] / total_over3) * 100 if total_over3 else 0

    if under6_prob > over3_prob:
        return ("UNDER 6", best_under6[0], under6_prob)
    return ("OVER 3", best_over3[0], over3_prob)

def get_tick_history(symbol, count=TICK_COUNT):
    result = []

    def on_message(ws, message):
        try:
            data = json.loads(message)
            if data.get("msg_type") == "history":
                prices = data["history"]["prices"]
                for p in prices:
                    try:
                        result.append(int(str(p)[-1]))
                    except:
                        continue
                ws.close()
        except:
            ws.close()

    def on_open(ws):
        payload = {
            "ticks_history": symbol,
            "count": count,
            "end": "latest",
            "style": "ticks"
        }
        ws.send(json.dumps(payload))

    ws = websocket.WebSocketApp(
        DERIV_WS_URL,
        on_open=on_open,
        on_message=on_message
    )
    t = threading.Thread(target=ws.run_forever)
    t.daemon = True
    t.start()

    timeout = 20
    start = time.time()
    while len(result) < count and (time.time() - start < timeout):
        time.sleep(1)
    return result

def generate_signal_message(data):
    valid_until = (datetime.datetime.now(pytz.timezone("Africa/Nairobi")) + datetime.timedelta(minutes=SIGNAL_VALID_MINUTES)).strftime("%I:%M %p")
    bot_used = "Over 3 Signal Bot" if data['trade_type'] == "OVER 3" else "Under 6 Signal Bot"
    return f"""
📌 *BINARYTOOL TRADING SIGNALS*

✅ *Market:* {escape_markdown(MARKET_NAMES.get(data['symbol'], data['symbol']))}
🎯 *Trade Type:* {escape_markdown(data['trade_type'])}
🤖 *Bot Used:* {escape_markdown(bot_used)}
🔢 *Entry Point:* {escape_markdown(data['entry_point'])}
📊 *Probability:* {escape_markdown(f"{data['probability']:.2f}%")}
⏱️ *Tick Duration:* 1

📅 *Valid Until:* {escape_markdown(valid_until)} \\(5 minutes\\)

⚠️ *Note:* Apply good risk management\\.
""".strip()

def analyze_and_cache_signal():
    global cached_signal
    best = None
    for symbol in SYNTHETIC_SYMBOLS:
        ticks = get_tick_history(symbol)
        if not ticks:
            continue
        try:
            trade_type, entry_point, prob = analyze_ticks(ticks)
            if not best or prob > best["probability"]:
                best = {
                    "symbol": symbol,
                    "trade_type": trade_type,
                    "entry_point": entry_point,
                    "probability": prob
                }
        except:
            continue
    cached_signal = best

def send_reminder():
    if not cached_signal:
        msg_id = send_telegram_message("⏰ *Reminder:* Signal in 2 minutes\\! Load your bot\\! [app\\.binarytool\\.site](https://app.binarytool.site)")
    else:
        caption = "⏰ *Reminder:* Signal in 2 minutes\\! Load your bot at )"
        filepath = UNDER6_BOT_PATH if cached_signal["trade_type"] == "UNDER 6" else OVER3_BOT_PATH
        msg_id = send_telegram_document(caption, filepath)

    if msg_id:
        threading.Timer(50 * 60, delete_telegram_message, args=[msg_id]).start()

def send_smart_signal():
    if not cached_signal:
        send_telegram_message("⚠️ *Signal Generation Failed*: No valid signal available")
        return

    msg = generate_signal_message(cached_signal)
    msg_id = send_telegram_message(msg, image_url=BOT_IMAGE_URL)

    if msg_id:
        threading.Timer(50 * 60, delete_telegram_message, args=[msg_id]).start()

def setup_scheduler():
    for h in range(24):
        signal_time = f"{h:02d}:00"
        reminder_time = f"{h:02d}:58"  # 2 minutes before the signal

        schedule.every().day.at(reminder_time).do(analyze_and_cache_signal)
        schedule.every().day.at(reminder_time).do(send_reminder)
        schedule.every().day.at(signal_time).do(send_smart_signal)

def run_scheduler():
    while True:
        try:
            schedule.run_pending()
        except:
            pass
        time.sleep(1)

if __name__ == "__main__":
    try:
        websocket.create_connection(DERIV_WS_URL, timeout=10).close()
    except:
        send_telegram_message("🔴 *Startup Error*: Could not connect to Deriv API")
        exit(1)

    analyze_and_cache_signal()
    setup_scheduler()
    run_scheduler()
