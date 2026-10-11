import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

TARGET_DATE = "2026-10-29"
START_URL = (
    "https://pcc.youparking.com.tw/"
    "parkingreserve/#/reservedindex/1"
)
ARTIFACTS = Path("diagnostics")


def send_notification():
    sender = os.environ["EMAIL_USER"].strip()
    password = "".join(
        os.environ["EMAIL_APP_PASSWORD"].split()
    )
    recipients = [
        value.strip()
        for value in os.environ["EMAIL_TO"].split(",")
        if value.strip()
    ]

    if not sender or not password or not recipients:
        raise RuntimeError("寄信設定不完整，請檢查 Secrets。")

    checked_at = datetime.now(
        ZoneInfo("Asia/Taipei")
    ).strftime("%Y-%m-%d %H:%M:%S")

    message = EmailMessage()
    message["Subject"] = (
        f"P4 名額提醒：{TARGET_DATE} 出現登記按鈕"
    )
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(
        f"查詢時間：{checked_at}（台灣時間）\n\n"
        f"桃園機場 P4 優惠停車平台的 {TARGET_DATE} "
        "出現可點擊的「登記」按鈕。\n\n"
        "請立即開啟網站確認並自行登記：\n"
        f"{START_URL}\n\n"
        "名額可能隨時被登記，請以網站即時狀態為準。\n"
        "優惠登記不代表保留地下室車位。\n"
    )

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

    print("通知信已寄送。")


def main():
    print("程式版本：v2－點擊同意文字")

    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    if today >= datetime.fromisoformat(TARGET_DATE).date():
        print("已到目標日期，停止查詢。")
        return

    ARTIFACTS.mkdir(exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1280, "height": 900},
            locale="zh-TW",
            timezone_id="Asia/Taipei",
        )
        page.set_default_timeout(30000)

        try:
            print("正在開啟 P4 優惠停車平台。")
            page.goto(
                START_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            consent = page.get_by_role(
                "checkbox",
                name="本人已詳閱且同意上述須知規定",
                exact=True,
            )
            consent.wait_for(state="visible", timeout=60000)

            # 等待目前存在的遮罩消失。
            overlays = page.locator(".v-overlay--active")
            for index in range(overlays.count()):
                overlays.nth(index).wait_for(
                    state="hidden",
                    timeout=60000,
                )

            # 點擊文字標籤，避開勾選框上的視覺效果。
            print("準備點擊同意文字。")
            if not consent.is_checked():
                page.get_by_text(
                    "本人已詳閱且同意上述須知規定",
                    exact=True,
                ).click()

            if not consent.is_checked():
                raise RuntimeError(
                    "點擊同意文字後仍未勾選。"
                )

            print("已成功勾選同意。")

            page.get_by_role(
                "button",
                name="前往登記",
                exact=True,
            ).click()

            print("正在等待日期列表。")
            page.get_by_text(
                "P4停車場 - 剩餘車位數",
                exact=True,
            ).wait_for(state="visible", timeout=60000)

            row = page.locator("tr").filter(
                has_text=TARGET_DATE
            )
            row.first.wait_for(
                state="visible",
                timeout=60000,
            )

            if row.count() != 1:
                raise RuntimeError(
                    "目標日期列不唯一，停止判斷。"
                )

            status = row.inner_text()
            print(f"目標日期狀態：{status}")

            register = row.get_by_role(
                "button",
                name="登記",
                exact=True,
            )

            if "已滿" in status:
                print("目前已滿，不寄送通知。")
            elif (
                register.count() == 1
                and register.is_visible()
                and register.is_enabled()
            ):
                send_notification()
            else:
                raise RuntimeError(
                    "日期狀態無法辨識，"
                    "不能當作已滿或有名額。"
                )

        except Exception:
            print(f"失敗時所在頁面：{page.url}")
            print(
                "查詢失敗，請查看錯誤紀錄與診斷截圖。"
            )
            raise
        finally:
            try:
                page.screenshot(
                    path=str(ARTIFACTS / "page.png"),
                    full_page=True,
                    timeout=15000,
                )
            except Exception:
                print("本次無法儲存診斷截圖。")
            browser.close()


if __name__ == "__main__":
    main()
