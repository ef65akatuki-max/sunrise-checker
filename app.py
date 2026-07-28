import os
import re
import datetime
import json
import asyncio
import time
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request
import requests
from playwright.async_api import async_playwright

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

# ─── メール送信設定 ───
MAIL_USER = "ef65akatuki@gmail.com"
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")

# 空席検知時に通知を送るメールアドレスのリスト
MAIL_RECIPIENTS_ALERT = ["ef65akatuki@gmail.com", "as1567@sel.co.jp"]
# 定期生存確認を送るメールアドレス
MAIL_RECIPIENT_ALIVE = "ef65akatuki@gmail.com"

SUNRISE_STATIONS = [
    "東京", "横浜", "熱海", "沼津", "富士", "静岡", "浜松", 
    "豊橋", "名古屋", "岐阜", "大阪", "三ノ宮", "姫路", 
    "岡山", "児島", "坂出", "高松", 
    "倉敷", "備中高梁", "新見", "米子", "安来", "松江", "宍道", "出雲市"
]

monitoring_jobs = []

def parse_line_message(text):
    date_match = re.search(r'(\d{1,2})[月/](\d{1,2})日?', text)
    if not date_match:
        return None

    month = int(date_match.group(1))
    day = int(date_match.group(2))
    current_year = datetime.datetime.now().year
    target_date = datetime.date(current_year, month, day)

    if "瀬戸" in text:
        train_name = "サンライズ瀬戸"
    else:
        train_name = "サンライズ出雲"

    found_stations = []
    for st in SUNRISE_STATIONS:
        if st in text:
            pos = text.find(st)
            found_stations.append((pos, st))
    
    found_stations.sort(key=lambda x: x[0])
    ordered_stations = [st for pos, st in found_stations]

    if len(ordered_stations) >= 2:
        dep_station = ordered_stations[0]
        arr_station = ordered_stations[-1]
    else:
        if "上り" in text or ("岡山" in text and "東京" in text and text.find("岡山") < text.find("東京")):
            if len(ordered_stations) == 1:
                dep_station = ordered_stations[0]
                arr_station = "東京"
            else:
                dep_station = "出雲市" if "出雲" in train_name else "高松"
                arr_station = "東京"
        else:
            if len(ordered_stations) == 1:
                dep_station = ordered_stations[0]
                arr_station = "出雲市" if "出雲" in train_name else "高松"
            else:
                dep_station = "東京"
                arr_station = "出雲市" if "出雲" in train_name else "高松"

    return {
        "train_name": train_name,
        "date": target_date,
        "dep": dep_station,
        "arr": arr_station,
        "raw_text": text
    }

def send_single_email(to_email, subject, body):
    if not MAIL_PASSWORD:
        print("Error: MAIL_PASSWORD is not set.")
        return
    try:
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = MAIL_USER
        msg['To'] = to_email
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(MAIL_USER, MAIL_PASSWORD)
        server.sendmail(MAIL_USER, to_email, msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Failed to send email: {e}")

def send_alert_email(subject, body):
    if not MAIL_PASSWORD:
        print("Error: MAIL_PASSWORD is not set.")
        return
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(MAIL_USER, MAIL_PASSWORD)

        for recipient in MAIL_RECIPIENTS_ALERT:
            msg = MIMEMultipart()
            msg['Subject'] = subject
            msg['From'] = MAIL_USER
            msg['To'] = recipient
            msg.attach(MIMEText(body, 'plain'))
            server.sendmail(MAIL_USER, recipient, msg.as_string())

        server.quit()
    except Exception as e:
        print(f"Failed to send alert email: {e}")

# ─── Playwright による安定化・リトライ付き空席チェック ───
async def check_e5489_seats(parsed):
    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"]
                )
                page = await browser.new_page()
                
                # e5489の検索トップへアクセス
                await page.goto("https://www.e5489.jr-odekake.net/e5489/cspg/SSTrainSearchCommonEmptyTopStartActionInit.do", timeout=30000)
                
                # 駅名フォームに直接入力
                await page.fill('input[name="depStnName"]', parsed["dep"])
                await page.fill('input[name="arrStnName"]', parsed["arr"])
                
                # 日付情報がある場合はフォームまたは隠し要素へ反映させるか、サブミットを実行
                # ここで確実に検索ボタンを押下
                await page.click('input[type="submit"]')
                
                # 描画とネットワークの落ち着きを待つ
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(4)
                
                content = await page.content()
                await browser.close()

                # 判定キーワードの拡張（○、△に加え「残席」「わずか」「残り」「空席」を網羅）
                seat_keywords = ["○", "△", "残席", "わずか", "残り", "空席"]
                found_keyword = next((kw for kw in seat_keywords if kw in content), None)

                if found_keyword:
                    return True, f"空席あり（検出キーワード: {found_keyword}）"
                else:
                    return False, "満席"

        except Exception as e:
            print(f"e5489 scraping error (attempt {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES - 1:
                return False, "エラーまたは満席"
            await asyncio.sleep(2)
            
    return False, "エラーまたは満席"

def send_line_reply(reply_token, message_text):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": message_text}]
    }
    requests.post(url, headers=headers, data=json.dumps(payload))

def send_line_push(user_id, message_text):
    if not LINE_CHANNEL_ACCESS_TOKEN or not user_id:
        return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message_text}]
    }
    requests.post(url, headers=headers, data=json.dumps(payload))

def monitor_loop():
    while True:
        try:
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{current_time}] Checking {len(monitoring_jobs)} monitoring jobs...")

            job_summaries = []
            for job in list(monitoring_jobs):
                parsed = job["parsed"]
                user_id = job["user_id"]
                date_str = parsed["date"].strftime("%Y-%m-%d")
                
                job_summaries.append(f"・{parsed['train_name']} ({date_str} / {parsed['dep']} → {parsed['arr']})")
                
                has_seat, detail = asyncio.run(check_e5489_seats(parsed))
                
                if has_seat:
                    alert_msg = (
                        f"【🎉 空席検知！！】\n"
                        f"監視中の列車に空席が出ました！今すぐ予約してください！\n\n"
                        f"■ 列車情報\n"
                        f"・列車名: {parsed['train_name']}\n"
                        f"・乗車日: {date_str}\n"
                        f"・区間: {parsed['dep']} ➔ {parsed['arr']}\n"
                        f"・状態: {detail}"
                    )
                    send_line_push(user_id, alert_msg)
                    send_alert_email(f"【空席検知】{parsed['train_name']} {date_str}", alert_msg)
                    monitoring_jobs.remove(job)

            if monitoring_jobs:
                jobs_text = "\n".join(job_summaries)
                send_single_email(
                    MAIL_RECIPIENT_ALIVE,
                    "【サンライズ監視中】5分定期チェック報告",
                    f"サンライズ空席監視システムは正常に稼働中です。\n\n現在監視中の条件:\n{jobs_text}\n\n確認時刻: {current_time}"
                )
        except Exception as e:
            print(f"Monitor loop error: {e}")
            
        time.sleep(300)

@app.route("/", methods=['GET'])
def index():
    return "Sunrise Seat Monitor is Running!"

@app.route("/callback", methods=['POST'])
def callback():
    body = request.get_json()
    events = body.get('events', [])
    
    for event in events:
        if event.get('type') == 'message':
            reply_token = event.get('replyToken')
            user_id = event.get('source', {}).get('userId')
            user_text = event['message'].get('text', '')
            parsed = parse_line_message(user_text)
            
            if parsed and reply_token:
                has_seat, detail = asyncio.run(check_e5489_seats(parsed))
                date_str = parsed["date"].strftime("%Y-%m-%d")
                
                if has_seat:
                    reply_msg = (
                        f"【空席あり！】\n"
                        f"現在、ご指定の条件で空席が見つかりました！\n"
                        f"状態: {detail}\n\n"
                        f"■ 対象列車\n"
                        f"・列車名: {parsed['train_name']}\n"
                        f"・乗車日: {date_str}\n"
                        f"・区間: {parsed['dep']} ➔ {parsed['arr']}\n\n"
                        f"お早めに e5489 からご予約ください！"
                    )
                    send_alert_email(f"【空席あり】{parsed['train_name']} {date_str}", reply_msg)
                else:
                    reply_msg = (
                        f"【満席 / 監視を開始します】\n"
                        f"現在満席です。5分おきに自動照会を行い、空席が出たらLINEとメールでお知らせします！\n\n"
                        f"■ 監視条件\n"
                        f"・列車名: {parsed['train_name']}\n"
                        f"・乗車日: {date_str}\n"
                        f"・区間: {parsed['dep']} ➔ {parsed['arr']}"
                    )
                    job_exists = any(j["parsed"]["raw_text"] == user_text and j["user_id"] == user_id for j in monitoring_jobs)
                    if not job_exists:
                        monitoring_jobs.append({"parsed": parsed, "user_id": user_id})
                
                send_line_reply(reply_token, reply_msg)
            
    return 'OK', 200

if __name__ == "__main__":
    t_monitor = threading.Thread(target=monitor_loop, daemon=True)
    t_monitor.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
