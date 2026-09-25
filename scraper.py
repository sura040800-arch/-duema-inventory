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


def close_popup(page):
    try:
        page.evaluate("""
            () => {
                const x = document.querySelector('.first-modal-close');
                if (x) x.click();

                const modal = document.querySelector('#first-modal-wrap');
                if (modal) {
                    modal.style.display = 'none';
                    modal.style.pointerEvents = 'none';
                }
            }
        """)
    except Exception:
        pass


def collect_all_links(page):

    print("カード一覧を取得開始", flush=True)

    page.goto(
        LIST_URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(2000)
    close_popup(page)

    all_links = []

    for page_number in range(1, 471):

        print(
            f"一覧ページ {page_number}/470",
            flush=True
        )

        links = get_card_links(page)

        before = len(all_links)

        for link in links:
            if link not in all_links:
                all_links.append(link)

        print(
            f"今回追加 {len(all_links) - before}枚 / "
            f"現在 {len(all_links)}枚",
            flush=True
        )

        if page_number == 470:
            break

        next_page = page_number + 1

        # 次のページボタンを探す
        button = page.locator(
            f'a[data-page="{next_page}"]'
        )

        # 見つからない場合は少し待って再確認
        if button.count() == 0:

            print(
                f"{next_page}ページ目のボタンを再検索",
                flush=True
            )

            page.wait_for_timeout(1000)
            close_popup(page)

            button = page.locator(
                f'a[data-page="{next_page}"]'
            )

        if button.count() == 0:
            raise RuntimeError(
                f"{next_page}ページ目のボタンが見つかりません"
            )

        # 強制クリック
        try:
            button.first.click(
                force=True,
                timeout=10000
            )
        except Exception as e:

            print(
                f"クリック失敗。再読み込みします: {e}",
                flush=True
            )

            page.reload(
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(1500)
            close_popup(page)

            button = page.locator(
                f'a[data-page="{next_page}"]'
            )

            button.first.click(
                force=True,
                timeout=10000
            )

        # 非同期読み込みを待つ
        page.wait_for_timeout(1200)

    print(
        f"一覧取得完了: {len(all_links)}枚",
        flush=True
    )

    return all_links


def parse_card(page, url):

    html = page.content()

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    title = ""

    if soup.title:
        title = soup.title.get_text(
            " ",
            strip=True
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
        card_id = url.split(
            "?id=",
            1
        )[1]

    return {
        "id": card_id,
        "name": name,
        "number": number,
        "url": url
    }


def save_cards(cards):

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

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

        # ① 全カードのURLを取得
        links = collect_all_links(page)

        if len(links) < 20000:
            raise RuntimeError(
                f"取得枚数が少なすぎます: {len(links)}枚"
            )

        print(
            f"全URL取得成功: {len(links)}枚",
            flush=True
        )

        # ② 詳細ページを取得
        cards = []

        print(
            "詳細ページ取得開始",
            flush=True
        )

        for i, url in enumerate(
            links,
            1
        ):

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

                    page.wait_for_timeout(200)

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

                    print(
                        f"{i}/{len(links)} "
                        f"{card['name']}",
                        flush=True
                    )

                    break

                except Exception as e:

                    print(
                        f"失敗 {i}/{len(links)} "
                        f"({retry + 1}/3): {e}",
                        flush=True
                    )

                    time.sleep(1)

            if not success:
                print(
                    f"スキップ: {url}",
                    flush=True
                )

            # 100枚ごとに保存
            if i % 100 == 0:

                save_cards(cards)

                print(
                    f"途中保存: {len(cards)}枚",
                    flush=True
                )

        browser.close()

    save_cards(cards)

    print(
        f"★★ 完了: {len(cards)}枚 ★★",
        flush=True
    )


if __name__ == "__main__":
    main()
