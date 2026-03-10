import websocket
import json
import time
import threading
import requests
import argparse
import csv
import os
from datetime import datetime
from collections import deque
import numpy as np
from scipy import stats

# ===================== CONFIG =====================
TELEGRAM_TOKEN = os.getenv("7044109545:AAF_2u9_HqVGZzFIubnIWCQ3dFm7MyQfmWw")
CHAT_ID = os.getenv("5773032750")
WSS_URL = os.getenv("wss://1xlite-07241.pro/games-frame/sockets/crash?ref=1&gr=1559&whence=114&fcountry=66&appGuid=games-web-host-b2c-web-v3&lng=en&v=1.5&access_token=eyJhbGciOiJFUzI1NiIsImtpZCI6IjEiLCJ0eXAiOiJKV1QifQ.eyJzdWIiOiI1MC8xMTU2MTM3NzUxIiwicGlkIjoiMSIsImp0aSI6IjAvMjMwY2EyZWE2MTljMTNmYWNmODNkOGQxM2FmYzYzNmQ0MTBlZWY4Yzg1Y2FiMTY4MWExNTM2ZTllYTc0YzFhYSIsImFwcCI6Ik5BIiwic2lkIjoiMDE5Y2Q2OWUtZmU2OS03Y2M5LTlhMTUtODViNjVhNzJmMTA1IiwiaW5uZXIiOiJ0cnVlIiwid3QiOiJ0cnVlIiwibmJmIjoxNzczMTI3MjY5LCJleHAiOjE3NzMxNDE2NjksImlhdCI6MTc3MzEyNzI2OX0.1ha5o6rTHp4IcZVl4yq2L0bGwgrcULMccnKteotC4Y-70_1YHx-nRHZ6SOT9P34hO2syq8sb4RknqWtwgQab1g")
CSV_FILE = "crash_odds_PRO.csv"

SHORT_RUN_DURATION = 480   # 8 دقايق للـ Actions
PING_INTERVAL = 25

class CrashPredictor:
    def __init__(self):
        self.crash_history = deque(maxlen=200)
        self.streaks = {'low': 0, 'mid': 0, 'high': 0}

    def add_crash(self, val):
        try:
            v = float(val)
            if v >= 1.0:
                self.crash_history.append(v)
                self.update_streaks(v)
                print(f"Added crash: {v:.2f}x  |  History: {len(self.crash_history)}")
        except:
            pass

    def update_streaks(self, val):
        self.streaks = {'low': 0, 'mid': 0, 'high': 0}
        for v in list(self.crash_history)[-10:]:
            if v < 2.0:   self.streaks['low'] += 1
            elif v < 5.0: self.streaks['mid'] += 1
            else:         self.streaks['high'] += 1

    def predict(self):
        if len(self.crash_history) < 15:
            return "⏳ WAIT", 0.4, 0.0

        recent = list(self.crash_history)[-30:]
        x = np.arange(len(recent))

        predictions = []
        try:
            slope, intercept, r_value, _, _ = stats.linregress(x, recent)
            lin_pred = max(1.1, intercept + slope * (len(recent) + 1))
            predictions.append(lin_pred * (0.7 + r_value**2 * 0.3))
        except:
            pass

        alpha = 0.3
        ema = recent[0]
        for v in recent[1:]:
            ema = alpha * v + (1 - alpha) * ema
        predictions.append(ema * 1.1)

        streak_boost = 1.0
        if self.streaks['low'] >= 5: streak_boost = 2.2
        elif self.streaks['low'] >= 3: streak_boost = 1.6
        elif self.streaks['high'] >= 4: streak_boost = 0.75

        final_pred = np.mean(predictions) * streak_boost if predictions else np.mean(recent)
        confidence = min(0.92, 0.4 + len(recent)/200 + abs(streak_boost-1)*0.3)

        if final_pred > 4.0 and confidence > 0.8:
            return "🚀 STRONG BUY", confidence, final_pred
        elif final_pred > 2.4 and confidence > 0.7:
            return "✅ BUY", confidence, final_pred
        else:
            return "⏳ WAIT", confidence, final_pred

predictor = CrashPredictor()

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=10)
        print("→ Telegram sent")
    except Exception as e:
        print(f"Telegram error: {e}")

def save_crash(crash_val):
    try:
        ts = datetime.now().isoformat()
        exists = os.path.exists(CSV_FILE)
        with open(CSV_FILE, 'a', newline='') as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(['timestamp', 'crash_point'])
            w.writerow([ts, f"{crash_val:.2f}"])
        print(f"Saved crash: {crash_val:.2f}")
    except Exception as e:
        print(f"CSV error: {e}")

def on_message(ws, message):
    try:
        data = json.loads(message)
        print("RAW:", message)   # ← شوف الـ logs في Actions عشان نعدل

        crash = None
        if isinstance(data, dict):
            crash = (
                data.get("crash") or
                data.get("crash_point") or
                data.get("crashed") or
                data.get("result", {}).get("crash_point") or
                data.get("result", {}).get("multiplier") or
                data.get("coef") or
                (data.get("arguments", [{}])[0].get("f") if "arguments" in data else None)
            )

        if crash is not None:
            try:
                val = float(crash)
                print(f"CRASH DETECTED → {val:.2f}x")
                save_crash(val)
                predictor.add_crash(val)

                signal, conf, pred = predictor.predict()

                msg = f"""
<b>CRASH ROUND FINISHED</b>

Crash Point: <code>{val:.2f}x</code>
Signal for next: {signal}
Predicted target: <code>{pred:.2f}x</code>
Confidence: <code>{conf:.1%}</code>
Streaks (last 10): Low {predictor.streaks['low']} | Mid {predictor.streaks['mid']} | High {predictor.streaks['high']}
History entries: {len(predictor.crash_history)}
Time: {datetime.now().strftime('%H:%M:%S')} (Mansurah)
"""
                send_telegram(msg)

            except ValueError:
                print("Bad crash value:", crash)

    except json.JSONDecodeError:
        pass
    except Exception as e:
        print("Parse error:", e)

def on_open(ws):
    print("Connected to Crash WS")
    send_telegram("<b>🟢 Crash monitor started</b>\nWaiting for round ends...")

def on_error(ws, error):
    print("WS error:", error)

def on_close(ws, code, reason):
    print(f"WS closed: {code} {reason}")

def run(short_run=False):
    if not WSS_URL:
        print("WSS_URL not set")
        return

    ws = websocket.WebSocketApp(
        WSS_URL,
        on_message=on_message,
        on_open=on_open,
        on_error=on_error,
        on_close=on_close
    )

    t = threading.Thread(
        target=ws.run_forever,
        kwargs={"ping_interval": PING_INTERVAL, "ping_timeout": 10},
        daemon=True
    )
    t.start()

    if short_run:
        time.sleep(SHORT_RUN_DURATION)
        ws.close()
        print("Short run finished")
    else:
        while True:
            time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--short-run', action='store_true')
    args = parser.parse_args()

    # Load old crashes
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'r') as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                if len(row) >= 2:
                    try:
                        predictor.add_crash(float(row[1]))
                    except:
                        pass
        print(f"Loaded {len(predictor.crash_history)} old crashes")

    run(short_run=args.short_run)
