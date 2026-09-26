import json
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUT = Path("data/cards.json")
LIST_URL = "https://dm.takaratomy.co.jp/card/"


def get_links(page):
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
            if (x) {
                x.click();
            }

            const m = document.querySelector('#first-modal-wrap');
            if (m) {
                m.style.display = 'none';
                m.style.pointerEvents = 'none';
            }
        }
        """)
    except Exception:
        pass


def find_button(page, number):
    selector = f'a[data-page="{number}"]'

    for _ in range(20):
        close_popup(page)

        if page.locator(selector).count() > 0:
            return page.locator(selector).first

        time.sleep(1)

    return None


def move_page(page, number):
    for retry in range(5):
        print(
            f"{number}ページ目へ移動 ({retry + 1}/5)",
            flush=True
        )

        button = find_button(page, number)

        if button is not None:
            try:
                page.evaluate(
                    """
                    n => {
                        const b =
                            document.querySelector(
                                `a[data-page="${n}"]`
                            );

                        if (b) {
                            if (window.jQuery) {
                                window.jQuery(b).trigger('click');
                            } else {
                                b.click();
                            }
                        }
                    }
                    """,
                    number
                )

                page.wait_for_timeout(2500)

                return True

            except Exception as e:
                print(
                    f"移動エラー: {e}",
                    flush=True
                )

        print(
            "ボタンが見つからないので再読み込み",
            flush=True
        )

        try:
            page.reload(
                wait_until="domcontentloaded",
                timeout=120000
            )

            page.wait_for_timeout(3000)
            close_popup(page)

        except Exception as e:
            print(
                f"再読み込みエラー: {e}",
                flush=True
            )

        time.sleep(2)

    return False


def collect_links(page):
    print(
        "公式カード一覧を開きます",
        flush=True
    )

    page.goto(
        LIST_URL,
        wait_until="domcontentloaded",
        timeout=120000
    )

    page.wait_for_timeout(3000)

    close_popup(page)

    page.wait_for_selector(
        'a[href*="/card/detail/?id="]',
        timeout=120000
    )

    all_links = []

    for number in range(1, 471):
        print(
            f"一覧ページ {number}/470",
            flush=True
        )

        links = get_links(page)

        before = len(all_links)

        for link in links:
            if link not in all_links:
                all_links.append(link)

        added = len(all_links) - before

        print(
            f"今回追加 {added}枚 / 合計 {len(all_links)}枚",
            flush=True
        )

        if number == 470:
            break

        if not move_page(page, number + 1):
            raise RuntimeError(
                f"{number + 1}ページ目へ移動できません"
            )

    print(
        f"一覧取得完了: {len(all_links)}枚",
        flush=True
    )

    return all_links


def parse_card(page, url):
    soup = BeautifulSoup(
        page.content(),
        "html.parser"
    )

    if soup.title:
        title = soup.title.get_text(
            " ",
            strip=True
        )
    else:
        title = ""

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

        links = collect_links(page)

        if len(links) < 20000:
            raise RuntimeError(
                f"カード数が少なすぎます: {len(links)}"
            )

        print(
            f"全URL取得成功: {len(links)}枚",
            flush=True
        )

        cards = []

        for i, url in enumerate(links, 1):
            try:
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=120000
                )

                page.wait_for_timeout(1000)

                card = parse_card(
                    page,
                    url
                )

                if card["name"]:
                    cards.append(card)

                print(
                    f"{i}/{len(links)} {card['name']}",
                    flush=True
                )

            except Exception as e:
                print(
                    f"失敗 {i}: {e}",
                    flush=True
                )

            if i % 100 == 0:
                save(cards)

                print(
                    f"途中保存: {len(cards)}枚",
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
