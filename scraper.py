import json
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUT = Path("data/cards.json")
LIST_URL = "https://dm.takaratomy.co.jp/card/"


def get_card_links(page):
    links = []

    for a in page.locator('a[href*="/card/detail/?id="]').all():
        href = a.get_attribute("href")

        if not href:
            continue

        if href.startswith("/"):
            href = "https://dm.takaratomy.co.jp" + href

        if href not in links:
            links.append(href)

    return links


def collect_all_links(page):
    print("カード一覧を取得開始", flush=True)

    page.goto(
        LIST_URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(2000)

    # ポップアップを閉じる
    page.evaluate("""
        () => {
            const x = document.querySelector('.first-modal-close');
            if (x) x.click();

            const modal = document.querySelector('#first-modal-wrap');
            if (modal) modal.remove();
        }
    """)

    page.wait_for_timeout(500)

    all_links = []
    page_number = 1

    while page_number <= 470:

        print(
            f"一覧ページ {page_number}/470",
            flush=True
        )

        links = get_card_links(page)

        for link in links:
            if link not in all_links:
                all_links.append(link)

        print(
            f"現在 {len(all_links)} 枚",
            flush=True
        )

        if page_number >= 470:
            break

        next_page = page_number + 1

        # JavaScriptでページ番号を押す
        result = page.evaluate("""
            (pageNumber) => {
                const button =
                    document.querySelector(
                        `a[data-page="${pageNumber}"]`
                    );

                if (!button) return false;

                button.click();
                return true;
            }
        """, next_page)

        if not result:
            raise RuntimeError(
                f"{next_page}ページ目のボタンが見つかりません"
            )

        page.wait_for_timeout(1500)

        page_number = next_page

    print(
        f"一覧取得完了: {len(all_links)} 枚",
        flush=True
    )

    return all_links


def parse_card(page, url):
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    title = (
        soup.title.get_text(" ", strip=True)
        if soup.title
        else ""
    )

    title = title.split("|")[0].strip()

    match = re.match(
        r"(.+?)\(([^()]*)\)",
        title
    )

    if match:
        name = match.group(1).strip()
        number = match.group(2).strip()
    else:
        name = title
        number = ""

    card_id = ""

    if "?id=" in url:
        card_id = url.split("?id=", 1)[1]

    return {
        "id": card_id,
        "name": name,
        "number": number,
        "url": url
    }


def main():

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport={
                "width": 1280,
                "height": 900
            }
        )

        links = collect_all_links(page)

        if len(links) < 20000:
            raise RuntimeError(
                f"取得枚数が少なすぎます: {len(links)}"
            )

        cards = []

        print(
            f"詳細ページ取得開始: {len(links)}枚",
            flush=True
        )

        for i, url in enumerate(links, 1):

            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                if response is None:
                    raise RuntimeError("レスポンスなし")

                if response.status >= 400:
                    raise RuntimeError(
                        f"HTTP {response.status}"
                    )

                page.wait_for_timeout(300)

                card = parse_card(page, url)

                if card["name"]:
                    cards.append(card)

                print(
                    f"{i}/{len(links)} {card['name']}",
                    flush=True
                )

            except Exception as e:
                print(
                    f"失敗 {i}/{len(links)}: {e}",
                    flush=True
                )

            # 100枚ごとに保存
            if i % 100 == 0:

                with open(
                    OUT,
                    "w",
                    encoding="utf-8"
                ) as f:
                    json.dump(
                        cards,
                        f,
                        ensure_ascii=False,
                        indent=2
                    )

                print(
                    f"途中保存: {len(cards)}枚",
                    flush=True
                )

        browser.close()

    with open(
        OUT,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            cards,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"完了: {len(cards)}枚",
        flush=True
    )


if __name__ == "__main__":
    main()
