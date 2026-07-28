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

MAIL_RECIPIENTS_ALERT = ["ef65akatuki@gmail.com", "as1567@sel.co.jp"]
MAIL_RECIPIENT_ALIVE = "ef65akatuki@gmail.com"

# ─── sunrise.rutice.net 準拠のデータ定義 ───
ST_NAME_LIST_NO = {
    '東京': '%93%8C%8B%9E',
    '横浜': '%89%A1%95l',
    '熱海': '%94M%8AC',
    '沼津': '%8F%C0%92%C3',
    '富士': '%95x%8Em',
    '静岡': '%90%C3%89%AA',
    '浜松': '%95l%8F%BC',
    '大阪': '%91%E5%8D%E3',
    '三ノ宮': '%8EO%83m%8B%7B',
    '姫路': '%95P%98H',
    '岡山': '%89%AA%8ER',
    '児島': '%8E%99%93%87',
    '坂出': '%8D%E2%8Fo',
    '高松': '%8D%82%8F%BC%81i%8D%81%90%EC%8C%A7%81j',
    '多度津': '%91%BD%93x%92%C3',
    '善通寺': '%91P%92%CA%8E%9B',
    '琴平': '%8B%D5%95%BD',
    '倉敷': '%91q%95~',
    '備中高梁': '%94%F5%92%86%8D%82%97%C0',
    '新見': '%90V%8C%A9',
    '米子': '%95%C4%8Eq',
    '安来': '%88%C0%97%88',
    '松江': '%8F%BC%8D%5D',
    '宍道': '%8E%B3%93%B9',
    '出雲市': '%8Fo%89_%8Es'
}

FACILITY_IDS = {
    'seto': {
        '未指定': '%BB%BE%C4%20%20000',
        '普通車ノビノビ座席': '%BB%BE%C4%20%20000',
        'シングルデラックス': '%BB%BE%C4%20%20000',
        'シングルツイン': '%BB%BE%C4%20%20000',
        'シングル': '%BB%BE%C4%BC%20000',
        'ソロ': '%BB%BE%C4%BF%20000',
        'サンライズツイン': '%BB%BE%C4%BB%20000'
    },
    'izumo': {
        '未指定': '%BB%B2%BD%D3%20%20000',
        '普通車ノビノビ座席': '%BB%B2%BD%D3%20000',
        'シングルデラックス': '%BB%B2%BD%D3%20000',
        'シングルツイン': '%BB%B2%BD%D3%20000',
        'シングル': '%BB%B2%BD%D3%BC000',
        'ソロ': '%BB%B2%BD%D3%BF000',
        'サンライズツイン': '%BB%B2%BD%D3%BB000'
    }
}

# 発車時刻の目安（rutice.net の定義に合わせる）
TRAIN_TIMES = {
    "サンライズ瀬戸": {"dep_time": "21:26", "type_key": "seto"},
    "サンライズ出雲": {"dep_time": "21:26", "type_key": "izumo"}
}

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

    # 駅名の抽出
    found_stations = []
    for st in ST_NAME_LIST_NO.keys():
        if st in text:
            pos = text.find(st)
            found_stations.append((pos, st))
    
    found_stations.sort(key=lambda x: x[0])
    ordered_stations = [st for pos, st in found_stations]

    if len(ordered_stations) >= 2:
        dep_station = ordered_stations[0]
        arr_station = ordered_stations[-1]
    else:
        if "上り" in text:
            dep_station = "岡山" # デフォルト例
            arr_station = "東京"
        else:
            dep_station = "東京"
            arr_station = "岡山"

    return {
        "train_name": train_name,
        "date": target_date,
        "dep": dep_station,
        "arr": arr_station,
        "raw_text": text
    }

def send_single_email(to_email, subject, body):
    if not MAIL_PASSWORD:
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

# ─── sunrise.rutice.net のURL構築ロジックによる直接照会 ───
async def check_e5489_seats(parsed):
    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        try:
            train_info = TRAIN_TIMES.get(parsed["train_name"], TRAIN_TIMES["サンライズ出雲"])
            t_key = train_info["type_key"]
            dep_time = train_info["dep_time"] # "21:26"
            
            encoded_depart = ST_NAME_LIST_NO.get(parsed["dep"], '%93%8C%8B%9E')
            encoded_arrive = ST_NAME_LIST_NO.get(parsed["arr"], '%89%AA%8ER')
            facility_id = FACILITY_IDS[t_key]['未指定']
            
            date_str = parsed["date"].strftime("%Y%m%d")
            
            # rutice.net と同じ SP版/PC版 共通の組み立てURLベース
            action = 'https://e5489.jr-odekake.net/e5489/cssp/CBDayTimeArriveSelRsvMyDiaSP?'
            
            param = (
                f"inputDepartStName={encoded_depart}"
                f"&inputArriveStName={encoded_arrive}"
                f"&inputType=0"
                f"&inputDate={date_str}"
                f"&inputHour={dep_time.split(':')[0]}"
                f"&inputMinute={dep_time.split(':')[1]}"
                f"&inputUniqueDepartSt=1"
                f"&inputUniqueArriveSt=1"
                f"&inputSearchType=1"
                f"&inputTransferDepartStName1={encoded_depart}"
                f"&inputTransferArriveStName1={encoded_arrive}"
                f"&inputTransferDepartStUnique1=1"
                f"&inputTransferArriveStUnique1=1"
                f"&inputTransferTrainType1=0001"
                f"&inputSpecificTrainType1=2"
                f"&inputSpecificBriefTrainKana1={facility_id}"
                f"&SequenceType=0"
            )
            target_url = action + param

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"]
                )
                page = await browser.new_page()
                
                # 構築した完全なURLに直接アクセス
                await page.goto(target_url, timeout=30000)
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(3)
                
                content = await page.content()
                await browser.close()

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
        if event.get('type'] == 'message':
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
