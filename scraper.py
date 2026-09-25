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
                const x =
                    document.querySelector('.first-modal-close');
                if (x) x.click();

                const modal =
                    document.querySelector('#first-modal-wrap');

                if (modal) {
                    modal.style.display = 'none';
                    modal.style.pointerEvents = 'none';
                }
            }
        """)
    except Exception:
        pass


def open_list(page):

    for attempt in range(5):

        try:
            print(
                f"公式サイトへ接続 {attempt + 1}/5",
                flush=True
            )

            page.goto(
                LIST_URL,
                wait_until="commit",
                timeout=120000
            )

            page.wait_for_timeout(5000)

            close_popup(page)

            # カード一覧が出るまで待つ
            page.wait_for_selector(
                'a[href*="/card/detail/?id="]',
                timeout=60000
            )

            print(
                "カード一覧の読み込み成功",
                flush=True
            )

            return True

        except Exception as e:

            print(
                f"接続失敗: {e}",
                flush=True
            )

            if attempt < 4:
                print(
                    "30秒待って再試行します",
                    flush=True
                )
                time.sleep(30)

    return False


def collect_all_links(page):

    print(
        "カード一覧を取得開始",
        flush=True
    )

    if not open_list(page):
        raise RuntimeError(
            "公式カード一覧を読み込めませんでした"
        )

    all_links = []

    for page_number in range(1, 471):

        print(
            f"一覧ページ {page_number}/470",
            flush=True
        )

        page.wait_for_timeout(500)

        links = get_card_links(page)

        before = len(all_links)

        for link in links:
            if link not in all_links:
                all_links.append(link)

        print(
            f"今回追加 {len(all_links) - before}枚 / "
            f"合計 {len(all_links)}枚",
            flush=True
        )

        if page_number == 470:
            break

        next_page = page_number + 1

        # 次ページボタンを探す
        button = page.locator(
            f'a[data-page="{next_page}"]'
        )

        if button.count() == 0:

            print(
                f"{next_page}ページ目のボタンがないため再読み込み",
                flush=True
            )

            if not open_list(page):
                raise RuntimeError(
                    "一覧ページを再読み込みできません"
                )

            # 目的のページまで戻る
            for p in range(2, next_page):

                b = page.locator(
                    f'a[data-page="{p}"]'
                )

                if b.count() == 0:
                    raise RuntimeError(
                        f"{p}ページ目へ移動できません"
                    )

                b.first.click(
                    force=True,
                    timeout=15000
                )

                page.wait_for_timeout(1000)

            button = page.locator(
                f'a[data-page="{next_page}"]'
            )

        try:

            button.first.click(
                force=True,
                timeout=15000
            )

        except Exception as e:

            print(
                f"ページ移動失敗: {e}",
                flush=True
            )

            time.sleep(5)

            button = page.locator(
                f'a[data-page="{next_page}"]'
            )

            button.first.click(
                force=True,
                timeout=15000
            )

        page.wait_for_timeout(1500)

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
        card_id = url.split("?id=", 1)[1]

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

        # 全カードURLを取得
        links = collect_all_links(page)

        if len(links) < 20000:
            raise RuntimeError(
                f"カードURLが少なすぎます: {len(links)}枚"
            )

        print(
            f"全URL取得成功: {len(links)}枚",
            flush=True
        )

        cards = []

        print(
            "詳細ページ取得開始",
            flush=True
        )

        for i, url in enumerate(
            links,
            1
        ):

            for retry in range(3):

                try:

                    response = page.goto(
                        url,
                        wait_until="commit",
                        timeout=120000
                    )

                    if response is None:
                        raise RuntimeError(
                            "レスポンスなし"
                        )

                    page.wait_for_timeout(1500)

                    card = parse_card(
                        page,
                        url
                    )

                    if not card["name"]:
                        raise RuntimeError(
                            "カード名なし"
                        )

                    cards.append(card)

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

                    time.sleep(3)

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
