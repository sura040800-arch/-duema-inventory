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


def get_total_cards(html):
    """
    「23310枚」のような公式表示から
    総カード数を取得する。
    """

    text = BeautifulSoup(
        html,
        "html.parser"
    ).get_text(
        " ",
        strip=True
    )

    patterns = [
        r"([\d,]+)枚",
        r"([\d,]+)\s*枚"
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text
        )

        for value in matches:

            try:

                number = int(
                    value.replace(
                        ",",
                        ""
                    )
                )

                if number >= 1000:
                    return number

            except Exception:
                pass

    return None


def get_real_page_count(page):
    """
    公式のページャーまたは総カード数から
    ページ数を決定する。
    """

    html = page.content()

    # --------------------------------
    # data-page を探す
    # --------------------------------

    values = page.locator(
        "a[data-page]"
    ).evaluate_all(
        """
        els => els
            .map(a => a.getAttribute("data-page"))
            .filter(x => x)
        """
    )

    numbers = []

    for value in values:

        try:
            numbers.append(
                int(value)
            )
        except Exception:
            pass

    if numbers:

        last_page = max(numbers)

        print(
            f"ページャーから最終ページ取得: "
            f"{last_page}",
            flush=True
        )

        return last_page

    # --------------------------------
    # 総カード数から計算
    # --------------------------------

    total = get_total_cards(
        html
    )

    if total:

        last_page = (
            total + 49
        ) // 50

        print(
            f"公式総カード数: {total}枚",
            flush=True
        )

        print(
            f"総カード数から最終ページ計算: "
            f"{last_page}",
            flush=True
        )

        return last_page

    raise RuntimeError(
        "公式ページからページ数を取得できませんでした"
    )


def get_current_ids(page):
    links = page.locator(
        '#cardlist a[href*="/card/detail/"]'
    ).evaluate_all(
        """
        els => els.map(a => a.href)
        """
    )

    ids = []

    for url in links:

        cid = card_id_from_url(
            url
        )

        if cid:
            ids.append(cid)

    return ids


def click_page(page, page_number, old_ids):
    """
    公式のページャーを実際にクリックする。
    """

    locator = page.locator(
        f'a[data-page="{page_number}"]'
    )

    if locator.count() == 0:

        # data-pageが取れない場合は
        # 表示文字から探す
        locator = page.locator(
            f'a.page:has-text("{page_number}")'
        )

    if locator.count() == 0:

        raise RuntimeError(
            f"{page_number}ページ目のリンクが見つかりません"
        )

    print(
        f"{page_number}ページ目をクリック...",
        flush=True
    )

    locator.first.click(
        force=True
    )

    # --------------------------------
    # カード一覧が変わるまで待つ
    # --------------------------------

    start = time.time()

    while True:

        new_ids = get_current_ids(
            page
        )

        if new_ids and new_ids != old_ids:

            return new_ids

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

        print(
            f"1ページ目: {len(first_links)}枚",
            flush=True
        )

        # --------------------------------
        # 最終ページ
        # --------------------------------

        last_page = get_real_page_count(
            page
        )

        # --------------------------------
        # 1ページ目保存
        # --------------------------------

        order = 0

        for cid, url in first_links:

            if cid not in all_links:

                all_links[cid] = url

                release_order[cid] = order

                order += 1

        # --------------------------------
        # 2ページ目以降
        # --------------------------------

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

                    old_ids = get_current_ids(
                        page
                    )

                    new_ids = click_page(
                        page,
                        page_number,
                        old_ids
                    )

                    # --------------------------------
                    # 現在ページのURLを取得
                    # --------------------------------

                    links = page.locator(
                        '#cardlist a[href*="/card/detail/"]'
                    ).evaluate_all(
                        """
                        els => els.map(a => a.href)
                        """
                    )

                    if not links:

                        raise RuntimeError(
                            "カードリンクが0件です"
                        )

                    new_count = 0

                    for url in links:

                        cid = card_id_from_url(
                            url
                        )

                        if not cid:
                            continue

                        if cid not in all_links:

                            all_links[cid] = (
                                absolute_url(url)
                            )

                            release_order[cid] = (
                                order
                            )

                            order += 1

                            new_count += 1

                    print(
                        f"[{page_number}/{last_page}] "
                        f"{len(links)}枚 / "
                        f"新規{new_count}枚 / "
                        f"累計{len(all_links)}枚",
                        flush=True
                    )

                    success = True

                    break

                except Exception as e:

                    print(
                        f"[{page_number}/{last_page}] "
                        f"retry {attempt}/3: {e}",
                        flush=True
                    )

                    time.sleep(2)

                    # 失敗したらページ1からやり直す
                    page.goto(
                        SEARCH_URL,
                        wait_until="domcontentloaded",
                        timeout=60000
                    )

                    page.wait_for_timeout(
                        1500
                    )

                    # 必要なページまで戻す
                    if page_number > 2:

                        for back_page in range(
                            2,
                            page_number
                        ):

                            old_ids = get_current_ids(
                                page
                            )

                            click_page(
                                page,
                                back_page,
                                old_ids
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

                    cid = card.get("id")

                    if cid:

                        old_cards[cid] = card

        except Exception as e:

            print(
                f"既存cards.json読込失敗: {e}",
                flush=True
            )

    print(
        f"既存カード: {len(old_cards)}枚",
        flush=True
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
        f"新規取得対象: {len(targets)}枚",
        flush=True
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

                    new_cards.append(
                        card
                    )

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
