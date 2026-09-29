import os
import re
import json
import time
import requests

from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright


BASE_URL = "https://dm.takaratomy.co.jp"
SEARCH_URL = BASE_URL + "/card/"

DATA_DIR = "data"
CARDS_FILE = os.path.join(DATA_DIR, "cards.json")
IDS_FILE = os.path.join(DATA_DIR, "card_ids.json")

MAX_WORKERS = 12
TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
}


def clean_text(value):
    if not value:
        return ""

    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def absolute_url(url):
    if not url:
        return ""

    if url.startswith("http"):
        return url

    return BASE_URL + url


def card_id_from_url(url):
    if not url:
        return None

    m = re.search(
        r"[?&]id=([^&#]+)",
        url
    )

    if not m:
        return None

    return m.group(1)


def extract_card_links(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    result = []
    seen = set()

    for a in soup.select(
        'a[href*="/card/detail/"]'
    ):
        href = a.get(
            "href",
            ""
        )

        cid = card_id_from_url(href)

        if not cid:
            continue

        if cid in seen:
            continue

        seen.add(cid)

        result.append(
            (
                cid,
                absolute_url(href)
            )
        )

    return result


def get_page_count(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    values = []

    for a in soup.select(
        "#cardlist .wp-pagenavia a[data-page]"
    ):
        value = a.get(
            "data-page"
        )

        try:
            values.append(
                int(value)
            )
        except Exception:
            pass

    if values:
        return max(values)

    text = soup.get_text(
        " ",
        strip=True
    )

    matches = re.findall(
        r"([\d,]+)\s*枚",
        text
    )

    for value in matches:

        try:

            total = int(
                value.replace(
                    ",",
                    ""
                )
            )

            if total >= 1000:
                return (
                    total + 49
                ) // 50

        except Exception:
            pass

    raise RuntimeError(
        "最終ページ数を取得できませんでした"
    )


def get_page_ids(page):
    links = page.locator(
        '#cardlist .wp-pagenavi a'
    ).evaluate_all(
        """
        els => els.map(a => ({
            page: a.getAttribute("data-page"),
            text: a.innerText
        }))
        """
    )

    return links


def browser_get_page(
    page,
    page_number,
    previous_ids
):
    """
    公式ページャーを正確に指定してクリック。
    ナビゲーション完了を待ってからカードを取得する。
    """

    selector = (
        f'#cardlist .wp-pagenavi '
        f'a[data-page="{page_number}"]'
    )

    locator = page.locator(
        selector
    )

    if locator.count() == 0:

        raise RuntimeError(
            f"{page_number}ページ目の公式リンクがありません"
        )

    print(
        f"{page_number}ページ目を送信...",
        flush=True
    )

    # 公式JSのフォーム送信なので、
    # click + navigation待ちを同時に行う
    try:

        with page.expect_navigation(
            wait_until="domcontentloaded",
            timeout=30000
        ):

            locator.first.click(
                force=True
            )

    except Exception:
        # navigationイベントが発生しない場合でも
        # 少し待ってDOM更新を確認
        time.sleep(2)

    page.wait_for_timeout(
        1500
    )

    # カードが新しいものになるまで確認
    start = time.time()

    while True:

        html = page.content()

        links = extract_card_links(
            html
        )

        ids = [
            x[0]
            for x in links
        ]

        if ids and ids != previous_ids:

            return links

        if time.time() - start > 30:

            raise RuntimeError(
                f"{page_number}ページ目へ移動後、"
                "カード一覧が変化しませんでした"
            )

        time.sleep(0.5)


def discover_all_cards():

    print()
    print("========================================")
    print("公式カード一覧を取得")
    print("========================================")

    all_links = {}
    release_order = {}

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            user_agent=HEADERS["User-Agent"]
        )

        page = context.new_page()

        print(
            "公式カード検索を開いています...",
            flush=True
        )

        page.goto(
            SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(
            2000
        )

        # --------------------------------
        # 1ページ目
        # --------------------------------

        html = page.content()

        first_links = extract_card_links(
            html
        )

        if not first_links:

            browser.close()

            raise RuntimeError(
                "1ページ目からカードを取得できませんでした"
            )

        last_page = get_page_count(
            html
        )

        print(
            f"1ページ目: {len(first_links)}枚",
            flush=True
        )

        print(
            f"最終ページ: {last_page}",
            flush=True
        )

        order = 0

        for cid, url in first_links:

            all_links[cid] = url
            release_order[cid] = order
            order += 1

        # --------------------------------
        # ページ2以降
        # --------------------------------

        current_links = first_links

        for page_number in range(
            2,
            last_page + 1
        ):

            success = False

            for attempt in range(
                1,
                4
            ):

                try:

                    previous_ids = [
                        x[0]
                        for x in current_links
                    ]

                    current_links = (
                        browser_get_page(
                            page,
                            page_number,
                            previous_ids
                        )
                    )

                    new_count = 0

                    for cid, url in current_links:

                        if cid not in all_links:

                            all_links[cid] = url

                            release_order[cid] = order

                            order += 1

                            new_count += 1

                    print(
                        f"[{page_number}/{last_page}] "
                        f"{len(current_links)}枚 / "
                        f"新規{new_count}枚 / "
                        f"累計{len(all_links)}枚",
                        flush=True
                    )

                    success = True
                    break

                except Exception as e:

                    print(
                        f"retry {attempt}/3: {e}",
                        flush=True
                    )

                    time.sleep(2)

                    # ページ1に戻す
                    page.goto(
                        SEARCH_URL,
                        wait_until="domcontentloaded",
                        timeout=60000
                    )

                    page.wait_for_timeout(
                        1500
                    )

                    current_links = (
                        extract_card_links(
                            page.content()
                        )
                    )

                    # 失敗ページまで戻す
                    for back in range(
                        2,
                        page_number
                    ):

                        previous_ids = [
                            x[0]
                            for x in current_links
                        ]

                        current_links = (
                            browser_get_page(
                                page,
                                back,
                                previous_ids
                            )
                        )

            if not success:

                browser.close()

                raise RuntimeError(
                    f"{page_number}ページ目の取得に失敗しました"
                )

        browser.close()

    print()
    print("========================================")
    print(
        f"一覧取得完了: {len(all_links)}枚"
    )
    print("========================================")

    if len(all_links) < 10000:

        raise RuntimeError(
            f"取得枚数が少なすぎます: {len(all_links)}"
        )

    return all_links, release_order


def parse_detail(
    cid,
    url,
    html,
    release_order
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    h1 = soup.find("h1")

    title = ""

    if h1:
        title = clean_text(
            h1.get_text(
                " ",
                strip=True
            )
        )

    name = title

    if "(" in name:
        name = name.split(
            "(",
            1
        )[0].strip()

    image_url = ""

    image = soup.select_one(
        'img[src*="/cardimage/"]'
    )

    if not image:
        image = soup.select_one(
            "main img"
        )

    if image:
        image_url = absolute_url(
            image.get(
                "src",
                ""
            )
        )

    text = soup.get_text(
        "\n",
        strip=True
    )

    lines = [
        clean_text(x)
        for x in text.splitlines()
    ]

    def get_after(label):

        for i, line in enumerate(lines):

            if line == label:

                if i + 1 < len(lines):
                    return lines[i + 1]

        return ""

    ability = ""

    if "特殊能力" in text:

        part = text.split(
            "特殊能力",
            1
        )[1]

        if "フレーバー" in part:

            part = part.split(
                "フレーバー",
                1
            )[0]

        ability = clean_text(
            part
        )

    flavor = ""

    if "フレーバー" in text:

        flavor = clean_text(
            text.split(
                "フレーバー",
                1
            )[1]
        )

    return {
        "id": cid,
        "name": name,
        "number": cid,
        "type": get_after("カードの種類"),
        "civilization": get_after("文明"),
        "rarity": get_after("レアリティ"),
        "power": get_after("パワー"),
        "cost": get_after("コスト"),
        "mana": get_after("マナ"),
        "race": get_after("種族"),
        "illustrator": get_after("イラストレーター"),
        "text": ability,
        "flavor": flavor,
        "image": image_url,
        "url": url,
        "release_order": release_order
    }


def fetch_card(item):

    cid, url, release_order = item

    try:

        r = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        r.raise_for_status()

        return parse_detail(
            cid,
            url,
            r.text,
            release_order
        )

    except Exception as e:

        print(
            f"失敗: {cid} {e}",
            flush=True
        )

        return None


def main():

    os.makedirs(
        DATA_DIR,
        exist_ok=True
    )

    all_links, release_order = (
        discover_all_cards()
    )

    old_cards = {}

    if os.path.exists(
        CARDS_FILE
    ):

        try:

            with open(
                CARDS_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                old_data = json.load(f)

            if isinstance(
                old_data,
                list
            ):

                for card in old_data:

                    cid = card.get(
                        "id"
                    )

                    if cid:
                        old_cards[cid] = card

        except Exception as e:

            print(
                f"既存cards.json読込失敗: {e}"
            )

    print(
        f"既存カード: {len(old_cards)}枚"
    )

    targets = []

    for cid, url in all_links.items():

        if cid not in old_cards:

            targets.append(
                (
                    cid,
                    url,
                    release_order[cid]
                )
            )

    print(
        f"新規取得対象: {len(targets)}枚"
    )

    new_cards = []

    if targets:

        with ThreadPoolExecutor(
            max_workers=MAX_WORKERS
        ) as executor:

            futures = [
                executor.submit(
                    fetch_card,
                    item
                )
                for item in targets
            ]

            completed = 0

            for future in as_completed(
                futures
            ):

                completed += 1

                card = future.result()

                if card:
                    new_cards.append(card)

                if (
                    completed % 20 == 0
                    or completed == len(targets)
                ):

                    print(
                        f"詳細取得: "
                        f"{completed}/"
                        f"{len(targets)}",
                        flush=True
                    )

    cards = []

    for cid in all_links:

        if cid in old_cards:

            card = old_cards[cid]

            card["release_order"] = (
                release_order[cid]
            )

            card["url"] = (
                all_links[cid]
            )

            cards.append(card)

    cards.extend(
        new_cards
    )

    unique = {}

    for card in cards:

        cid = card.get("id")

        if cid:
            unique[cid] = card

    cards = list(
        unique.values()
    )

    cards.sort(
        key=lambda x:
        x.get(
            "release_order",
            999999999
        )
    )

    with open(
        CARDS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            cards,
            f,
            ensure_ascii=False,
            indent=2
        )

    with open(
        IDS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            list(all_links.keys()),
            f,
            ensure_ascii=False,
            indent=2
        )

    print()
    print("========================================")
    print(
        f"カード数: {len(cards)}枚"
    )
    print(
        f"新規取得: {len(new_cards)}枚"
    )
    print("========================================")


if __name__ == "__main__":
    main()
