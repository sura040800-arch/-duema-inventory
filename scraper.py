import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
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


# =========================================================
# 共通
# =========================================================

def clean_text(value):
    if value is None:
        return ""

    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def absolute_url(url):
    if not url:
        return ""

    return urljoin(BASE_URL, url)


def card_id_from_url(url):
    if not url:
        return None

    m = re.search(r"[?&]id=([^&#]+)", url)

    if not m:
        return None

    return m.group(1)


# =========================================================
# 公式検索ページのURLを作る
# =========================================================

def make_page_url(base_url, page_number):

    parsed = urlparse(base_url)

    query = parse_qs(
        parsed.query,
        keep_blank_values=True
    )

    # 公式サイトの検索条件 v
    state = {}

    if "v" in query and query["v"]:
        try:
            state = json.loads(query["v"][0])
        except Exception:
            state = {}

    # 初期値
    state.setdefault("suggest", "on")
    state.setdefault("samename", "show")
    state.setdefault("sort", "release_new")

    # ここが重要
    state["pagenum"] = str(page_number)

    new_query = urlencode(
        {
            "v": json.dumps(
                state,
                ensure_ascii=False,
                separators=(",", ":")
            )
        }
    )

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        )
    )


# =========================================================
# 一覧ページ解析
# =========================================================

def extract_card_links(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    results = []

    # 公式カード詳細リンク
    for a in soup.select(
        'a[href*="/card/detail/"]'
    ):

        href = a.get("href", "")

        cid = card_id_from_url(href)

        if not cid:
            continue

        url = absolute_url(href)

        results.append(
            (
                cid,
                url
            )
        )

    # 重複削除
    unique = []
    seen = set()

    for cid, url in results:

        if cid in seen:
            continue

        seen.add(cid)

        unique.append(
            (
                cid,
                url
            )
        )

    return unique


def get_page_count(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    pages = []

    for a in soup.select(
        "#cardlist .wp-pagenavi a[data-page]"
    ):

        value = a.get("data-page")

        try:
            pages.append(
                int(value)
            )
        except Exception:
            pass

    # 最後のページ
    if pages:
        return max(pages)

    # 念のため別検索
    text = soup.get_text(
        " ",
        strip=True
    )

    m = re.search(
        r"最後のページ",
        text
    )

    if m:
        for a in soup.select(
            'a[data-page]'
        ):
            value = a.get("data-page")

            try:
                pages.append(
                    int(value)
                )
            except Exception:
                pass

    return max(pages) if pages else 1


# =========================================================
# 全ページのカードID取得
# =========================================================

def discover_all_cards():

    print()
    print("========================================")
    print("公式カード一覧を取得")
    print("========================================")

    session = requests.Session()
    session.headers.update(
        HEADERS
    )

    # まず1ページ目
    print(
        "1ページ目を取得中...",
        flush=True
    )

    r = session.get(
        SEARCH_URL,
        timeout=TIMEOUT
    )

    r.raise_for_status()

    first_html = r.text

    first_links = extract_card_links(
        first_html
    )

    last_page = get_page_count(
        first_html
    )

    print(
        f"1ページ目: {len(first_links)}枚",
        flush=True
    )

    print(
        f"最後のページ: {last_page}",
        flush=True
    )

    if len(first_links) == 0:
        raise RuntimeError(
            "1ページ目からカードが取得できませんでした"
        )

    all_links = {}

    release_order = {}

    order = 0

    for cid, url in first_links:

        if cid not in all_links:

            all_links[cid] = url
            release_order[cid] = order

            order += 1

    # ページ2以降
    for page_number in range(
        2,
        last_page + 1
    ):

        page_url = make_page_url(
            SEARCH_URL,
            page_number
        )

        print(
            f"[{page_number}/{last_page}] 取得中...",
            flush=True
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

                # 50枚取れることを期待
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
                    f"  {len(links)}枚 / 新規{new_count}枚 / 累計{len(all_links)}枚",
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
    print(
        "========================================"
    )
    print(
        f"一覧取得完了: {len(all_links)}枚"
    )
    print(
        "========================================"
    )

    # 公式表示数と大きく違う場合は停止
    if len(all_links) < 10000:

        raise RuntimeError(
            f"取得枚数が少なすぎます: {len(all_links)}"
        )

    return all_links, release_order


# =========================================================
# カード詳細解析
# =========================================================

def parse_detail(cid, url, html, release_order):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    title = ""

    h1 = soup.find("h1")

    if h1:
        title = clean_text(
            h1.get_text(" ", strip=True)
        )

    # タイトルからカード名を取り出す
    name = title

    if "(" in name:
        name = name.split(
            "(",
            1
        )[0].strip()

    # 画像
    image_url = ""

    image = soup.select_one(
        'main img[src*="/card/"]'
    )

    if not image:
        image = soup.select_one(
            'img[src*="/cardimage/"]'
        )

    if not image:
        image = soup.find("img")

    if image:

        image_url = absolute_url(
            image.get("src", "")
        )

    # ページ全体から基本情報を取る
    text = soup.get_text(
        "\n",
        strip=True
    )

    def get_after(label):

        lines = [
            clean_text(x)
            for x in text.splitlines()
        ]

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

    # 特殊能力
    ability = ""

    marker = "特殊能力"

    if marker in text:

        part = text.split(
            marker,
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

    # フレーバー
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


# =========================================================
# 詳細ページ取得
# =========================================================

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


# =========================================================
# メイン
# =========================================================

def main():

    os.makedirs(
        DATA_DIR,
        exist_ok=True
    )

    # -----------------------------------------
    # 一覧
    # -----------------------------------------

    all_links, release_order = discover_all_cards()

    # -----------------------------------------
    # 既存データ
    # -----------------------------------------

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
                f"既存cards.json読込失敗: {e}"
            )

    print()
    print(
        f"既存カード: {len(old_cards)}枚"
    )

    # -----------------------------------------
    # 新規カード
    # -----------------------------------------

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

    # -----------------------------------------
    # 新規詳細取得
    # -----------------------------------------

    new_cards = []

    if targets:

        print()
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
                    completed % 10 == 0
                    or completed == len(targets)
                ):

                    print(
                        f"進捗: {completed}/{len(targets)}",
                        flush=True
                    )

    # -----------------------------------------
    # 全カード統合
    # -----------------------------------------

    cards = []

    for cid in all_links:

        if cid in old_cards:

            card = old_cards[cid]

            # 最新の順番だけ更新
            card["release_order"] = (
                release_order[cid]
            )

            # URLが空なら更新
            card["url"] = all_links[cid]

            cards.append(
                card
            )

    for card in new_cards:

        cards.append(
            card
        )

    # ID重複除去
    unique = {}

    for card in cards:

        cid = card.get("id")

        if cid:
            unique[cid] = card

    cards = list(
        unique.values()
    )

    # 最新順
    cards.sort(
        key=lambda x:
            x.get(
                "release_order",
                999999999
            )
    )

    # -----------------------------------------
    # 保存
    # -----------------------------------------

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
    print(
        "========================================"
    )
    print(
        "完成"
    )
    print(
        "========================================"
    )
    print(
        f"カード数: {len(cards)}"
    )
    print(
        f"新規取得: {len(new_cards)}"
    )


if __name__ == "__main__":
    main()
