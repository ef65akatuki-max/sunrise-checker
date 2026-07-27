import os
import re
import time
import threading
import datetime
import json
from flask import Flask, request, abort
import requests

app = Flask(__name__)

# LINEの環境変数（Render側で設定したものを使用、なければ直書き値を使用）
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "A5c1f7dd4e3d3cc3277cb2d0ad125c0f")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

SUNRISE_STATIONS = [
    "東京", "横浜", "熱海", "沼津", "富士", "静岡", "浜松", 
    "豊橋", "名古屋", "岐阜", "大阪", "三ノ宮", "姫路", 
    "岡山", "児島", "坂出", "高松", 
    "倉敷", "備中高梁", "新見", "米子", "安来", "松江", "宍道", "出雲市"
]

TARGET_ROOMS = [
    "A寝台シングルデラックス",
    "B寝台シングル",
    "B寝台ソロ",
    "B寝台サンライズツイン",
    "B寝台シングルツイン"
]

def parse_line_message(text):
    is_monitor = "監視" in text
    is_extra = "臨時" in text
    
    date_match = re.search(r'(\d{1,2})月(\d{1,2})日', text)
    if not date_match:
        return None

    month = int(date_match.group(1))
    day = int(date_match.group(2))
    current_year = datetime.datetime.now().year
    target_date = datetime.date(current_year, month, day)

    train_name = "サンライズ瀬戸"
    if "出雲" in text:
        train_name = "サンライズ出雲91号" if (is_extra and "上り" in text) or "91" in text else (
                     "サンライズ出雲92号" if (is_extra and "下り" in text) or "92" in text else (
                     "サンライズ出雲(臨時)" if is_extra else "サンライズ出雲"))
    elif "瀬戸" in text:
        train_name = "サンライズ瀬戸(臨時)" if is_extra else "サンライズ瀬戸"

    found_stations = []
    for word in text.replace("→", " ").replace("から", " ").replace("まで", " ").split():
        clean_word = re.sub(r'[^\w]', '', word)
        for st in SUNRISE_STATIONS:
            if st in clean_word and st not in found_stations:
                found_stations.append(st)

    direction = "上り" if "上り" in text else ("下り" if "下り" in text else None)

    if len(found_stations) >= 2:
        dep_station = found_stations[0]
        arr_station = found_stations[1]
    else:
        if not direction:
            direction = "上り"
        if direction == "上り":
            dep_station = "出雲市" if "出雲" in train_name else "高松"
            arr_station = "東京"
        else:
            dep_station = "東京"
            arr_station = "出雲市" if "出雲" in train_name else "高松"

    return {
        "is_monitor": is_monitor,
        "is_extra": is_extra,
        "train_name": train_name,
        "date": target_date.strftime("%Y-%m-%d"),
        "dep": dep_station,
        "arr": arr_station
    }

# LINEに返信を送る関数
def send_line_reply(reply_token, message_text):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("Error: LINE_CHANNEL_ACCESS_TOKEN is not set.")
        return

    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": message_text
            }
        ]
    }
    requests.post(url, headers=headers, data=json.dumps(payload))

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
            user_text = event['message'].get('text', '')
            parsed = parse_line_message(user_text)
            
            if parsed and reply_token:
                # 返信メッセージの作成
                reply_msg = (
                    f"【満席 / 監視を開始します】\n"
                    f"現在、ご指定の条件は満席です。\n"
                    f"このまま裏で定期照会を行い、空席が出たら即座にお知らせします！\n\n"
                    f"■ 監視条件\n"
                    f"・列車名: {parsed['train_name']}\n"
                    f"・乗車日: {parsed['date']}\n"
                    f"・区間: {parsed['dep']} ➔ {parsed['arr']}"
                )
                
                # LINEへ即座に返信
                send_line_reply(reply_token, reply_msg)
                
                # ※ここに実際の空席巡回ロジック（threading等）を呼び出す処理が入ります
            
    return 'OK', 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
