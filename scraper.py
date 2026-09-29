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
    if value is None:
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

    match = re.search(r"[?&]id=([^&#]+)", url)

    if not match:
        return None

    return match.group(1)


def extract_card_links(html):
    soup = BeautifulSoup(html, "html.parser")

    result = []
    seen = set()

    for a in soup.select('a[href*="/card/detail/"]'):
        href = a.get("href", "")

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
    soup = BeautifulSoup(html, "html.parser")

    pages = []

    for a in soup.select(
        "#cardlist .wp-pagenavi a[data-page]"
    ):
        value = a.get("data-page")

        try:
            pages.append(int(value))
        except Exception:
            pass

    if pages:
        return max(pages)

    return 1


def get_real_page2_url():
    """
    公式サイトの実際のフォーム送信を使って
    本物の2ページ目URLを取得する。
    """

    print()
    print("========================================")
    print("公式ページング方式を確認")
    print("========================================")

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            user_agent=HEADERS["User-Agent"]
        )

        print(
            "公式1ページ目を開いています...",
            flush=True
        )

        page.goto(
            SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(1500)

        html = page.content()

        first_links = extract_card_links(html)

        if len(first_links) == 0:

            browser.close()

            raise RuntimeError(
                "公式1ページ目からカードが取得できませんでした"
            )

        last_page = get_page_count(html)

        print(
            f"1ページ目: {len(first_links)}枚",
            flush=True
        )

        print(
            f"最後のページ: {last_page}",
            flush=True
        )

        # --------------------------------
        # ここが今回の修正版
        # hidden input を JS で直接変更
        # --------------------------------

        print(
            "公式フォームから2ページ目へ移動...",
            flush=True
        )

        result = page.evaluate(
            """
            () => {
                const form = document.querySelector(
                    'form#search_cond'
                );

                if (!form) {
                    return {
                        ok: false,
                        error: "form#search_cond が見つかりません"
                    };
                }

                const input = form.querySelector(
                    'input[name="pagenum"]'
                );

                if (!input) {
                    return {
                        ok: false,
                        error: "pagenum input が見つかりません"
                    };
                }

                input.value = "2";

                form.submit();

                return {
                    ok: true,
                    value: input.value
                };
            }
            """
        )

        if not result.get("ok"):

            browser.close()

            raise RuntimeError(
                result.get(
                    "error",
                    "フォーム送信に失敗しました"
                )
            )

        print(
            f"pagenum={result.get('value')}",
            flush=True
        )

        # ページ遷移を待つ
        try:

            page.wait_for_load_state(
                "domcontentloaded",
                timeout=30000
            )

        except Exception:
            pass

        page.wait_for_timeout(2500)

        page2_url = page.url

        page2_html = page.content()

        page2_links = extract_card_links(
            page2_html
        )

        print(
            f"2ページ目URL: {page2_url}",
            flush=True
        )

        print(
            f"2ページ目カード数: {len(page2_links)}枚",
            flush=True
        )

        if len(page2_links) == 0:

            browser.close()

            raise RuntimeError(
                "2ページ目へ移動しましたがカードが取得できませんでした"
            )

        first_ids = [
            x[0]
            for x in first_links
        ]

        second_ids = [
            x[0]
            for x in page2_links
        ]

        if first_ids == second_ids:

            browser.close()

            raise RuntimeError(
                "2ページ目が1ページ目と完全に同じです"
            )

        browser.close()

        return page2_url, last_page


def discover_all_cards():

    print()
    print("========================================")
    print("公式カード一覧を取得")
    print("========================================")

    # --------------------------------
    # まず本物の2ページ目URLを取得
    # --------------------------------

    page2_url, last_page = get_real_page2_url()

    print()
    print("========================================")
    print("ページング確認成功")
    print("========================================")

    print(
        f"総ページ数: {last_page}",
        flush=True
    )

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    # --------------------------------
    # 1ページ目
    # --------------------------------

    print(
        "1ページ目を取得...",
        flush=True
    )

    r = session.get(
        SEARCH_URL,
        timeout=TIMEOUT
    )

    r.raise_for_status()

    first_links = extract_card_links(
        r.text
    )

    if len(first_links) == 0:

        raise RuntimeError(
            "1ページ目からカードを取得できませんでした"
        )

    all_links = {}
    release_order = {}

    order = 0

    for cid, url in first_links:

        if cid not in all_links:

            all_links[cid] = url

            release_order[cid] = order

            order += 1

    print(
        f"1ページ目: "
        f"{len(first_links)}枚 / "
        f"累計{len(all_links)}枚",
        flush=True
    )

    # --------------------------------
    # 2ページ目以降
    # --------------------------------

    for page_number in range(
        2,
        last_page + 1
    ):

        # 2ページ目はPlaywrightで取得した
        # 本物のURLをそのまま使う
        if page_number == 2:

            page_url = page2_url

        else:

            # 2ページ目URLのクエリを変更
            from urllib.parse import (
                urlparse,
                parse_qs,
                urlencode,
                urlunparse
            )

            parsed = urlparse(
                page2_url
            )

            query = parse_qs(
                parsed.query,
                keep_blank_values=True
            )

            if "v" not in query:

                raise RuntimeError(
                    "2ページ目URLにv=がありません"
                )

            state = json.loads(
                query["v"][0]
            )

            state["pagenum"] = str(
                page_number
            )

            new_query = urlencode(
                {
                    "v": json.dumps(
                        state,
                        ensure_ascii=False,
                        separators=(",", ":")
                    )
                }
            )

            page_url = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    new_query,
                    parsed.fragment
                )
            )

        success = False

        for attempt in range(1, 4):

            try:

                rr = session.get(
                    page_url,
                    timeout=TIMEOUT
                )

                rr.raise_for_status()

                links = extract_card_links(
                    rr.text
                )

                if len(links) == 0:

                    raise RuntimeError(
                        "カード0枚"
                    )

                new_count = 0

                for cid, url in links:

                    if cid not in all_links:

                        all_links[cid] = url

                        release_order[cid] = order

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
                    f"  retry {attempt}/3: {e}",
                    flush=True
                )

                time.sleep(2)

        if not success:

            raise RuntimeError(
                f"{page_number}ページ目の取得に失敗しました"
            )

    print()
    print("========================================")
    print(
        f"一覧取得完了: {len(all_links)}枚"
    )
    print("========================================")

    # --------------------------------
    # 安全装置
    # --------------------------------

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

    title = ""

    h1 = soup.find("h1")

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

    if not image:

        image = soup.find(
            "img"
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

    card_type = get_after(
        "カードの種類"
    )

    civilization = get_after(
        "文明"
    )

    rarity = get_after(
        "レアリティ"
    )

    power = get_after(
        "パワー"
    )

    cost = get_after(
        "コスト"
    )

    mana = get_after(
        "マナ"
    )

    race = get_after(
        "種族"
    )

    illustrator = get_after(
        "イラストレーター"
    )

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

        part = text.split(
            "フレーバー",
            1
        )[1]

        flavor = clean_text(
            part
        )

    return {
        "id": cid,
        "name": name,
        "number": cid,
        "type": card_type,
        "civilization": civilization,
        "rarity": rarity,
        "power": power,
        "cost": cost,
        "mana": mana,
        "race": race,
        "illustrator": illustrator,
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

    # --------------------------------
    # 既存データ読み込み
    # --------------------------------

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

    # --------------------------------
    # 新規カードだけ取得
    # --------------------------------

    targets = []

    for cid, url in all_links.items():

        if cid in old_cards:
            continue

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

        print(
            "新規カード詳細を取得中..."
        )

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
                        f"進捗: "
                        f"{completed}/"
                        f"{len(targets)}",
                        flush=True
                    )

    # --------------------------------
    # 全カード結合
    # --------------------------------

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

            cards.append(
                card
            )

    for card in new_cards:

        cards.append(
            card
        )

    # --------------------------------
    # 重複除去
    # --------------------------------

    unique = {}

    for card in cards:

        cid = card.get(
            "id"
        )

        if cid:

            unique[cid] = card

    cards = list(
        unique.values()
    )

    # --------------------------------
    # 最新順
    # --------------------------------

    cards.sort(
        key=lambda x:
        x.get(
            "release_order",
            999999999
        )
    )

    # --------------------------------
    # 保存
    # --------------------------------

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
        f"カード数: {len(cards)}"
    )
    print(
        f"新規取得: {len(new_cards)}"
    )
    print("========================================")


if __name__ == "__main__":
    main()
