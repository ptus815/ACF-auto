# -*- coding: utf-8 -*-
import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config.json"

ONEDRIVE_URL = os.getenv(
    "ONEDRIVE_URL",
    "https://onedrive.live.com/?id=%2Fpersonal%2F57cdf784c4e3e87b%2FDocuments%2F%E6%96%B0%F0%9F%94%9E&listurl=%2Fpersonal%2F57cdf784c4e3e87b%2FDocuments",
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text("utf-8"))
        except Exception:
            pass

    return {
        "url": ONEDRIVE_URL,
        "cookie": "",
    }


def save_config(data):
    CONFIG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_badger_auth(cookie_text):
    m = re.search(r"(?:^|;\s*)BadgerAuth=([^;]+)", cookie_text or "")
    return m.group(1) if m else ""


def build_full_cookie_string(cookies):
    items = []

    for c in cookies:
        name = c.get("name", "")
        value = c.get("value", "")

        if not name:
            continue

        items.append(f"{name}={value}")

    return "; ".join(items)


def get_all_cookies_by_cdp(context, page):
    try:
        cdp = context.new_cdp_session(page)
        result = cdp.send("Network.getAllCookies")
        cookies = result.get("cookies", [])
        if cookies:
            return cookies
    except Exception:
        pass

    return context.cookies()


def fetch_full_cookie():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1365, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            ignore_https_errors=True,
        )

        page = context.new_page()

        page.goto(ONEDRIVE_URL, wait_until="domcontentloaded", timeout=60000)

        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass

        time.sleep(10)

        final_url = page.url

        cookies = get_all_cookies_by_cdp(context, page)
        cookie_text = build_full_cookie_string(cookies)

        browser.close()

        if not cookie_text:
            raise RuntimeError("没有抓到任何 Cookie。")

        if "BadgerAuth=" not in cookie_text:
            raise RuntimeError("已经抓到 Cookie，但没有 BadgerAuth。可能 GitHub 无登录环境无法生成授权态。")

        return final_url, cookie_text


def main():
    cfg = load_config()

    final_url, full_cookie = fetch_full_cookie()

    if "id=" in final_url or "redeem=" in final_url:
        cfg["url"] = final_url
    else:
        cfg["url"] = cfg.get("url") or ONEDRIVE_URL

    cfg["cookie"] = full_cookie

    save_config(cfg)

    print("OK: config.json 已更新完整 CK")
    print("URL:", cfg["url"])
    print("Cookie length:", len(full_cookie))
    print("BadgerAuth:", "YES" if extract_badger_auth(full_cookie) else "NO")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", str(e))
        sys.exit(1)
