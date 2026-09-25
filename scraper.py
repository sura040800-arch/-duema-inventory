import json
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUT = Path("data/cards.json")
LIST_URL = "https://dm.takaratomy.co.jp/card/"


def get_links(page):
    result = []

    for a in page.locator('a[href*="/card/detail/?id="]').all():
        href = a.get_attribute("href")

        if not href:
            continue

        if href.startswith("/"):
            href = "https://dm.takaratomy.co.jp" + href

        if href not in result:
            result.append(href)

    return result


def close_popup(page):
    try:
        page.evaluate("""
        () => {
            const x = document.querySelector('.first-modal-close');
            if (x) x.click();

            const m = document.querySelector('#first-modal-wrap');
            if (m) {
                m.style.display = 'none';
                m.style.pointerEvents = 'none';
            }
        }
        """)
    except Exception:
        pass


def get_page(page, number):

    selector = f'a[data-page="{number}"]'

    # 最大30秒待つ
    for _ in range(30):

        close_popup(page)

        if page.locator(selector).count() > 0:
            return True

        time.sleep(1)

    return False


def collect_links(page):

    print("公式サイトを開きます", flush=True)

    page.goto(
        LIST_URL,
        wait_until="commit",
        timeout=120000
    )

    page.wait_for_timeout(5000)
    close_popup(page)

    # 1ページ目が表示されるまで待つ
    page.wait_for_selector(
        'a[href*="/card/detail/?id="]',
        timeout=120000
    )

    links = []

    for number in range(1, 471):

        print(
            f"一覧ページ {number}/470",
            flush=True
        )

        current = get_links(page)

        before = len(links)

        for x in current:
            if x not in links:
                links.append(x)

        print(
            f"今回追加 {len(links) - before}枚 / "
            f"合計 {len(links)}枚",
            flush=True
        )

        if number == 470:
            break

        next_number = number + 1

        # 次ページのボタンが出るまで待つ
        if not get_page(page, next_number):

            raise RuntimeError(
                f"{next_number}ページ目のボタンが見つかりません"
            )

        # 公式サイトのクリック処理を実行
        page.evaluate(
            """
            n => {
                const b =
                    document.querySelector(
                        `a[data-page="${n}"]`
                    );

                if (b) {
                    b.click();
                }
            }
            """,
            next_number
        )

        # 非同期読み込み待ち
        page.wait_for_timeout(2000)

    print(
        f"一覧取得完了: {len(links)}枚",
        flush=True
    )

    return links


def parse_card(page, url):

    soup = BeautifulSoup(
        page.content(),
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

    card_id = url.split("?id=", 1)[1]

    return {
        "id": card_id,
        "name": name,
        "number": number,
        "url": url
    }


def save(cards):

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

        # 全カードURL取得
        links = collect_links(page)

        if len(links) < 20000:
            raise RuntimeError(
                f"カード数が少なすぎます: {len(links)}"
            )

        print(
            f"全URL取得成功: {len(links)}枚",
            flush=True
        )

        # 詳細ページ取得
        cards = []

        for i, url in enumerate(
            links,
            1
        ):

            try:

                page.goto(
                    url,
                    wait_until="commit",
                    timeout=120000
                )

                page.wait_for_timeout(1500)

                card = parse_card(
                    page,
                    url
                )

                if card["name"]:
                    cards.append(card)

                print(
                    f"{i}/{len(links)} "
                    f"{card['name']}",
                    flush=True
                )

            except Exception as e:

                print(
                    f"失敗 {i}: {e}",
                    flush=True
                )

            # 100枚ごとに保存
            if i % 100 == 0:
                save(cards)

                print(
                    f"途中保存 {len(cards)}枚",
                    flush=True
                )

        browser.close()

    save(cards)

    print(
        f"★★ 完了 {len(cards)}枚 ★★",
        flush=True
    )


if __name__ == "__main__":
    main()
