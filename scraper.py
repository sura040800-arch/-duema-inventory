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


def get_current_page(page):
    try:
        text = page.locator(
            ".wp-pagenavi .current"
        ).first.inner_text()

        return int(text.strip())
    except Exception:
        return 0


def get_last_page(page):
    try:
        value = page.locator(
            '.wp-pagenavi a[data-page]'
        ).last.get_attribute("data-page")

        return int(value)
    except Exception:
        return 470


def click_next_page(page, next_page):
    # 最大5回まで挑戦
    for attempt in range(5):

        # ボタンが出てくるまで待つ
        try:
            page.wait_for_function(
                """pageNumber => {
                    return !!document.querySelector(
                        `a[data-page="${pageNumber}"]`
                    );
                }""",
                arg=next_page,
                timeout=10000
            )
        except Exception:
            pass

        # JavaScriptでクリック
        result = page.evaluate(
            """
            pageNumber => {
                const button =
                    document.querySelector(
                        `a[data-page="${pageNumber}"]`
                    );

                if (!button) {
                    return false;
                }

                button.click();
                return true;
            }
            """,
            next_page
        )

        if result:
            # ページ番号が変わるまで待つ
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
                    timeout=15000
                )

                return True

            except Exception:
                pass

        print(
            f"{next_page}ページ目への移動を再試行 "
            f"({attempt + 1}/5)",
            flush=True
        )

        # 現在のページを再読み込み
        try:
            page.reload(
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(1500)

            # ポップアップがあれば閉じる
            page.evaluate("""
                () => {
                    const x =
                        document.querySelector(
                            '.first-modal-close'
                        );

                    if (x) x.click();
                }
            """)

            page.wait_for_timeout(500)

        except Exception:
            pass

    return False


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
            const x =
                document.querySelector(
                    '.first-modal-close'
                );

            if (x) x.click();
        }
    """)

    page.wait_for_timeout(500)

    all_links = []

    last_page = get_last_page(page)

    print(
        f"最終ページ: {last_page}",
        flush=True
    )

    for page_number in range(1, last_page + 1):

        print(
            f"一覧ページ {page_number}/{last_page}",
            flush=True
        )

        # 本当にそのページにいるか確認
        current = get_current_page(page)

        if current != page_number:
            print(
                f"現在ページ={current} → "
                f"{page_number}へ移動",
                flush=True
            )

        links = get_card_links(page)

        before = len(all_links)

        for link in links:
            if link not in all_links:
                all_links.append(link)

        added = len(all_links) - before

        print(
            f"今回追加 {added}枚 / "
            f"現在合計 {len(all_links)}枚",
            flush=True
        )

        if page_number >= last_page:
            break

        next_page = page_number + 1

        if not click_next_page(page, next_page):
            raise RuntimeError(
                f"{next_page}ページ目へ移動できません"
            )

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

    title = (
        soup.title.get_text(
            " ",
            strip=True
        )
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

        # まず一覧ページから全URL取得
        links = collect_all_links(page)

        if len(links) < 20000:
            raise RuntimeError(
                f"カードURLが少なすぎます: "
                f"{len(links)}枚"
            )

        print(
            f"全URL取得成功: {len(links)}枚",
            flush=True
        )

        cards = []

        print(
            "詳細ページの取得開始",
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
                            "カード名が取得できません"
                        )

                    cards.append(card)

                    success = True

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

            # 100枚ごとに途中保存
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
