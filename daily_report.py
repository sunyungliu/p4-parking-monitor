import json
import os
import smtplib
import ssl
import subprocess
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
TARGET_DATE = "2026-10-29"
REPO = os.environ["GITHUB_REPOSITORY"]


def github_api(endpoint):
    result = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def send_email(body, abnormal):
    sender = os.environ["EMAIL_USER"].strip()
    password = "".join(
        os.environ["EMAIL_APP_PASSWORD"].split()
    )
    recipients = [
        address.strip()
        for address in os.environ["EMAIL_TO"].split(",")
        if address.strip()
    ]

    if not sender or not password or not recipients:
        raise RuntimeError("請檢查 Email Secrets。")

    message = EmailMessage()
    prefix = "需注意" if abnormal else "正常"
    message["Subject"] = f"P4 監控日報｜{prefix}"
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465,
        context=ssl.create_default_context(),
        timeout=30,
    ) as server:
        server.login(sender, password)
        refused = server.send_message(
            message,
            from_addr=sender,
            to_addrs=recipients,
        )
        if refused:
            raise RuntimeError("部分收件人未被接受。")

    print("監控日報已寄送。")


def main():
    now = datetime.now(timezone.utc)
    if now.astimezone(TAIPEI).date().isoformat() >= TARGET_DATE:
        print("已到目標日期，不再寄送日報。")
        return

    since = now - timedelta(hours=24)
    since_text = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    base = f"repos/{REPO}/actions/workflows/monitor.yml"

    # 逐頁取得過去 24 小時啟動的紀錄。
    runs = []
    page = 1
    while True:
        data = github_api(
            f"{base}/runs?per_page=100&page={page}"
            f"&created=%3E%3D{since_text}"
        )
        batch = data["workflow_runs"]
        runs.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    success = sum(r["conclusion"] == "success" for r in runs)
    failed = sum(
        r["conclusion"] in ("failure", "timed_out")
        for r in runs
    )
    other = len(runs) - success - failed

    latest = github_api(
        f"{base}/runs?status=success&per_page=1"
    )["workflow_runs"]

    abnormal = True
    last_time = "沒有成功紀錄"
    age_text = "無法計算"
    date_status = "無法確認"
    latest_url = f"https://github.com/{REPO}/actions"

    if latest:
        run = latest[0]
        latest_url = run["html_url"]

        # 讀取成功執行的文字紀錄，確認真的查到日期。
        logs = subprocess.run(
            [
                "gh", "run", "view", str(run["id"]),
                "--repo", REPO, "--log",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )

        text = logs.stdout
        verified = (
            logs.returncode == 0
            and "目標日期狀態：" in text
            and TARGET_DATE in text
            and (
                "目前已滿，不寄送通知。" in text
                or "通知信已寄送。" in text
            )
        )

        if verified:
            finished = parse_time(run["updated_at"])
            minutes = max(
                0, int((now - finished).total_seconds() / 60)
            )
            last_time = finished.astimezone(TAIPEI).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            age_text = f"約 {minutes} 分鐘"
            abnormal = minutes > 30

            if "目前已滿，不寄送通知。" in text:
                date_status = "已滿（最近成功查詢的結果）"
            else:
                date_status = "可登記，且已寄送名額通知"

        else:
            date_status = (
                "有成功執行紀錄，但無法從日誌驗證查詢結果"
            )

    health = (
        "需注意：超過 30 分鐘未成功查詢，或無法驗證紀錄。"
        if abnormal
        else "正常：最近 30 分鐘內有成功查詢。"
    )

    body = (
        "桃園機場 P4 優惠停車監控日報\n\n"
        f"報告時間：{now.astimezone(TAIPEI):%Y-%m-%d %H:%M:%S}\n"
        "以上時間皆為台灣時間。\n\n"
        f"監控狀態：{health}\n"
        f"最近驗證成功的執行完成時間：{last_time}\n"
        f"距離該次完成：{age_text}\n"
        f"10/29 狀態：{date_status}\n\n"
        "過去 24 小時啟動的執行紀錄：\n"
        f"總次數：{len(runs)}\n"
        f"執行成功：{success}\n"
        f"失敗或逾時：{failed}\n"
        f"其他（執行中、排隊、取消等）：{other}\n\n"
        "成功與失敗次數包含手動測試。\n"
        "最近完成時間略晚於實際網站查詢時間。\n"
        "日期狀態是歷史查詢結果，請以網站即時狀態為準。\n"
        "GitHub 排程可能延遲或略過執行。\n\n"
        f"查看執行紀錄：{latest_url}\n"
    )

    send_email(body, abnormal)


if __name__ == "__main__":
    main()
