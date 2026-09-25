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

    all_links = []
    page_number = 1

    while True:
        print(
            f"一覧ページ {page_number} / 470",
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

        button = page.locator(
            f'a[data-page="{next_page}"]'
        )

        if button.count() == 0:
            print(
                f"次のページ {next_page} が見つかりません",
                flush=True
            )
            break

        button.first.click()

        try:
            page.wait_for_function(
                """pageNumber => {
                    const current =
                        document.querySelector(
                            '.wp-pagenavi .current'
                        );
                    return current &&
                           current.textContent.trim() ===
                           String(pageNumber);
                }""",
                arg=next_page,
                timeout=30000
            )
        except Exception:
            print(
                f"ページ {next_page} の切り替え確認に失敗",
                flush=True
            )
            break

        page.wait_for_timeout(500)

        page_number = next_page

    print(
        f"一覧取得完了: {len(all_links)} 枚",
        flush=True
    )

    return all_links


def parse_card(page, url):
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(
        " ",
        strip=True
    ) if soup.title else ""

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

        # まず全カードのURLを取得
        links = collect_all_links(page)

        if len(links) < 20000:
            raise RuntimeError(
                f"取得枚数が少なすぎます: {len(links)}"
            )

        cards = []

        print(
            f"詳細ページ取得開始: {len(links)} 枚",
            flush=True
        )

        for i, url in enumerate(links, 1):

            success = False

            for retry in range(3):

                try:
                    response = page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=60000
                    )

                    if response is None:
                        raise RuntimeError(
                            "レスポンスなし"
                        )

                    if response.status >= 400:
                        raise RuntimeError(
                            f"HTTP {response.status}"
                        )

                    page.wait_for_timeout(300)

                    card = parse_card(
                        page,
                        url
                    )

                    if not card["name"]:
                        raise RuntimeError(
                            "カード名なし"
                        )

                    cards.append(card)

                    success = True
                    break

                except Exception as e:
                    print(
                        f"失敗 {i}/{len(links)} "
                        f"retry={retry + 1}: {e}",
                        flush=True
                    )
                    time.sleep(1)

            if not success:
                print(
                    f"3回失敗したためスキップ: {url}",
                    flush=True
                )

            # 100枚ごとに途中保存
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
                    f"途中保存: {len(cards)} 枚",
                    flush=True
                )

        browser.close()

    # 最終保存
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
        f"完了: {len(cards)} 枚",
        flush=True
    )


if __name__ == "__main__":
    main()
