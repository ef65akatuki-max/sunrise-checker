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
MAIL_USER = "ef65akatuki@gmail.com <mailto:ef65akatuki@gmail.com> "

MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "") # Render環境変数に設定

# 空席検知時に通知を送るメールアドレスのリスト
MAIL_RECIPIENTS_ALERT = ["ef65akatuki@gmail.com <mailto:ef65akatuki@gmail.com> ", "as1567@sel.co.jp <mailto:as1567@sel.co.jp> "]
# 定期生存確認を送るメールアドレス（ご指定により ef65akatuki@gmail.com <mailto:ef65akatuki@gmail.com>  のみ）
MAIL_RECIPIENT_ALIVE = "ef65akatuki@gmail.com <mailto:ef65akatuki@gmail.com> "
元のメッセージを表示
        server = smtplib.SMTP('smtp.gmail.com <http://smtp.gmail.com> ', 587)

        server.starttls()
        server.login(MAIL_USER, MAIL_PASSWORD)
        server.sendmail(MAIL_USER, to_email, msg.as_string())
        server.quit()
        print(f"Single email sent successfully to {to_email}")
    except Exception as e:
        print(f"Failed to send single email to {to_email}: {e}")

# ─── 複数宛先へのメール送信関数（空席検知用） ───
def send_alert_email(subject, body):
    if not MAIL_PASSWORD:
        print("Error: MAIL_PASSWORD (App Password) is not set.")
        return
    try:
        server = smtplib.SMTP('smtp.gmail.com <http://smtp.gmail.com> ', 587)
元のメッセージを表示
    requests.post <http://requests.post> (url, headers=headers, data=json.dumps(payload))


# ─── LINE プッシュ通知（Push Message） ───
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
    requests.post <http://requests.post> (url, headers=headers, data=json.dumps(payload))
元のメッセージを表示
            # 監視タスクが登録されている場合、ef65akatuki@gmail.com <mailto:ef65akatuki@gmail.com>  にのみ5分ごとの生存確認を送信
