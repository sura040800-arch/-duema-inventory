import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUT = Path("data/cards.json")

URL = "https://dm.takaratomy.co.jp/card/detail/?id=dm26rp3-OR001"


def main():
    print("カード1枚の取得テスト開始", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        response = page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        print("HTTP:", response.status, flush=True)

        page.wait_for_timeout(2000)

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        # ページタイトルからカード名・番号を取得
        title = soup.title.get_text(" ", strip=True) if soup.title else ""

        # 例：
        # ∑龍(DM26RP3 OR1/OR1) | デュエル・マスターズ
        title = title.split("|")[0].strip()

        match = re.match(r"(.+?)\(([^()]*)\)", title)

        if match:
            name = match.group(1).strip()
            number = match.group(2).strip()
        else:
            name = title
            number = ""

        card = {
            "id": "dm26rp3-OR001",
            "name": name,
            "number": number,
            "url": URL
        }

        OUT.parent.mkdir(parents=True, exist_ok=True)

        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(
                [card],
                f,
                ensure_ascii=False,
                indent=2
            )

        print("取得結果:", flush=True)
        print(json.dumps(card, ensure_ascii=False, indent=2), flush=True)
        print("TEST SUCCESS", flush=True)

        browser.close()


if __name__ == "__main__":
    main()
