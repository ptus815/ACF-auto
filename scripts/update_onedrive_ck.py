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
    "https://1drv.ms/f/c/57cdf784c4e3e87b/IgDL7QwxSCgKRp94PYqiYImHAVy9WQBnJEnrtLidIeLHcww?e=wGZWjC",
)

SEED_COOKIE = os.getenv("ONEDRIVE_COOKIE", "").strip()

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


def parse_cookie_header(cookie_text):
    out = []

    for part in (cookie_text or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue

        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()

        if name:
            out.append((name, value))

    return out


def extract_badger_auth(cookie_text):
    m = re.search(r"(?:^|;\s*)BadgerAuth=([^;]+)", cookie_text or "")
    return m.group(1).strip() if m else ""


def add_seed_cookies(context):
    pairs = parse_cookie_header(SEED_COOKIE)

    if not pairs:
        print("WARN: ONEDRIVE_COOKIE 为空，无法注入初始 CK")
        return

    targets = (
        "https://onedrive.live.com/",
        "https://my.microsoftpersonalcontent.com/",
        "https://1drv.ms/",
        "https://login.live.com/",
        "https://login.microsoftonline.com/",
        "https://account.live.com/",
    )

    total = 0

    for target in targets:
        cookies = []

        for name, value in pairs:
            cookies.append({
                "name": name,
                "value": value,
                "url": target,
                "path": "/",
            })

        try:
            context.add_cookies(cookies)
            total += len(cookies)
        except Exception as e:
            print("WARN: Cookie 注入失败:", target, str(e))

    print("OK: 已注入初始 Cookie 条数:", total)


def get_all_cookies(context, page):
    try:
        cdp = context.new_cdp_session(page)
        result = cdp.send("Network.getAllCookies")
        cookies = result.get("cookies", [])
        if cookies:
            return cookies
    except Exception:
        pass

    return context.cookies()


def cookie_priority(cookie):
    domain = (cookie.get("domain") or "").lower()

    if "onedrive.live.com" in domain:
        return 0

    if "my.microsoftpersonalcontent.com" in domain:
        return 1

    if "live.com" in domain:
        return 2

    if "microsoft" in domain:
        return 3

    if "1drv.ms" in domain:
        return 4

    return 9


def build_cookie_string(cookies):
    result = []
    seen = set()

    for c in sorted(cookies, key=cookie_priority):
        name = c.get("name", "")
        value = c.get("value", "")

        if not name:
            continue

        if name in seen:
            continue

        seen.add(name)
        result.append(f"{name}={value}")

    return "; ".join(result)


def merge_cookie_text(new_cookie, seed_cookie):
    merged = {}
    order = []

    for text in (new_cookie, seed_cookie):
        for name, value in parse_cookie_header(text):
            if name not in merged:
                order.append(name)
            merged[name] = value

    return "; ".join(f"{name}={merged[name]}" for name in order)


def fetch_cookie():
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

        add_seed_cookies(context)

        page = context.new_page()

        page.goto(ONEDRIVE_URL, wait_until="domcontentloaded", timeout=60000)

        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass

        time.sleep(12)

        final_url = page.url
        cookies = get_all_cookies(context, page)
        cookie_text = build_cookie_string(cookies)

        browser.close()

        if not cookie_text:
            raise RuntimeError("没有抓到任何 Cookie")

        if "BadgerAuth=" not in cookie_text and "BadgerAuth=" in SEED_COOKIE:
            print("WARN: 新 Cookie 没有 BadgerAuth，使用 Secret 里的 BadgerAuth 合并补齐")
            cookie_text = merge_cookie_text(cookie_text, SEED_COOKIE)

        if "BadgerAuth=" not in cookie_text:
            names = ", ".join(sorted({c.get("name", "") for c in cookies if c.get("name")}))
            raise RuntimeError("仍然没有 BadgerAuth。当前 Cookie 名称: " + names)

        return final_url, cookie_text


def main():
    cfg = load_config()

    final_url, cookie_text = fetch_cookie()

    cfg["url"] = final_url or cfg.get("url") or ONEDRIVE_URL
    cfg["cookie"] = cookie_text

    save_config(cfg)

    print("OK: config.json 已更新")
    print("URL:", cfg["url"])
    print("Cookie length:", len(cookie_text))
    print("BadgerAuth:", "YES" if extract_badger_auth(cookie_text) else "NO")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", str(e))
        sys.exit(1)
