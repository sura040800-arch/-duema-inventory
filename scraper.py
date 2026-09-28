import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


# =========================================
# 設定
# =========================================

OUT = Path("data/cards.json")

LIST_URL = "https://dm.takaratomy.co.jp/card/"

# 1ページ50枚
PER_PAGE = 50

# 詳細カード取得の同時実行数
CONCURRENCY = 8

# 250枚ごとにJSON保存
BATCH_SIZE = 250

# 失敗時の再試行
RETRIES = 4


# =========================================
# 基本処理
# =========================================

def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def get_lines(text):
    return [
        clean(x)
        for x in text.splitlines()
        if clean(x)
    ]


def get_value(lines, label):
    if label not in lines:
        return ""

    i = lines.index(label)

    if i + 1 < len(lines):
        return lines[i + 1]

    return ""


# =========================================
# 画像
# =========================================

def get_image(soup):

    selectors = [
        'img[src*="/card/"]',
        ".card-detail img",
        ".cardDetail img",
    ]

    for selector in selectors:

        img = soup.select_one(selector)

        if not img:
            continue

        src = img.get("src", "")

        if src.startswith("//"):
            return "https:" + src

        if src.startswith("/"):
            return urljoin(LIST_URL, src)

        return src

    return ""


# =========================================
# 能力
# =========================================

def get_abilities(lines):

    if "能力" not in lines:
        return []

    start = lines.index("能力") + 1

    stop = {
        "フレーバー",
        "イラストレーター",
        "カードの種類",
        "文明",
        "レアリティ",
        "パワー",
        "コスト",
        "マナ",
        "種族",
    }

    result = []

    for line in lines[start:]:

        if line in stop:
            break

        if line:
            result.append(line)

    return result


# =========================================
# フレーバー
# =========================================

def get_flavor(lines):

    if "フレーバー" not in lines:
        return ""

    start = lines.index("フレーバー") + 1

    stop = {
        "カードの種類",
        "文明",
        "レアリティ",
        "パワー",
        "コスト",
        "マナ",
        "種族",
        "イラストレーター",
        "能力",
    }

    result = []

    for line in lines[start:]:

        if line in stop:
            break

        result.append(line)

    return " ".join(result)


# =========================================
# ツインパクト面分割
# =========================================

def split_sides(text):

    lines = get_lines(text)

    positions = []

    for i, line in enumerate(lines):

        if line == "カードの種類":
            positions.append(i)

    if not positions:
        return [lines]

    sides = []

    for i, start in enumerate(positions):

        if i + 1 < len(positions):
            end = positions[i + 1]
        else:
            end = len(lines)

        block = lines[start:end]

        if block:
            sides.append(block)

    return sides


# =========================================
# 面解析
# =========================================

def parse_side(lines):

    return {
        "type": get_value(
            lines,
            "カードの種類"
        ),

        "civilization": get_value(
            lines,
            "文明"
        ),

        "rarity": get_value(
            lines,
            "レアリティ"
        ),

        "power": get_value(
            lines,
            "パワー"
        ),

        "cost": get_value(
            lines,
            "コスト"
        ),

        "mana": get_value(
            lines,
            "マナ"
        ),

        "race": get_value(
            lines,
            "種族"
        ),

        "illustrator": get_value(
            lines,
            "イラストレーター"
        ),

        "abilities": get_abilities(
            lines
        ),

        "flavor": get_flavor(
            lines
        ),
    }


# =========================================
# カード解析
# =========================================

def parse_card(html, url):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = soup.get_text("\n")

    lines = get_lines(text)

    # -------------------------------------
    # ID
    # -------------------------------------

    match = re.search(
        r"[?&]id=([^&]+)",
        url
    )

    if not match:
        return None

    card_id = match.group(1)

    # -------------------------------------
    # カード名
    # -------------------------------------

    name = ""

    selectors = [
        "h1",
        "h2",
        ".card-name",
        ".card-detail-name",
        ".cardDetail-name",
    ]

    for selector in selectors:

        el = soup.select_one(
            selector
        )

        if not el:
            continue

        candidate = clean(
            el.get_text(
                " ",
                strip=True
            )
        )

        if (
            candidate
            and len(candidate) < 200
        ):
            name = candidate
            break

    # -------------------------------------
    # 面
    # -------------------------------------

    blocks = split_sides(text)

    sides = []

    for block in blocks:

        side = parse_side(block)

        if side["type"]:
            sides.append(side)

    if not sides:
        return None

    is_twin = len(sides) >= 2

    return {
        "id": card_id,
        "name": name,
        "type": (
            "ツインパクト"
            if is_twin
            else sides[0]["type"]
        ),
        "image": get_image(soup),
        "url": url,
        "sides": sides,
    }


# =========================================
# 既存JSON読み込み
# =========================================

def load_existing():

    if not OUT.exists():
        return {}

    try:

        with open(
            OUT,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(data, list):
            return {}

        result = {}

        for card in data:

            if (
                isinstance(card, dict)
                and card.get("id")
            ):
                result[card["id"]] = card

        return result

    except Exception as e:

        print(
            f"既存JSON読み込み失敗: {e}"
        )

        return {}


# =========================================
# JSON保存
# =========================================

def save_cards(cards):

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    data = list(cards.values())

    data.sort(
        key=lambda x: (
            x.get("id", ""),
            x.get("name", "")
        )
    )

    tmp = OUT.with_suffix(
        ".tmp"
    )

    with open(
        tmp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    tmp.replace(OUT)

    print(
        f"JSON保存: {len(data)}枚"
    )


# =========================================
# ページURL生成
# =========================================

def make_page_url(
    base_url,
    page_number
):

    parsed = urlparse(base_url)

    query = parse_qs(
        parsed.query,
        keep_blank_values=True
    )

    # 公式サイトの v パラメータを使用
    if "v" in query:

        raw_v = query["v"][0]

        try:

            v = json.loads(
                raw_v
            )

        except Exception:

            v = {
                "suggest": "on",
                "sort": "release_new",
            }

    else:

        v = {
            "suggest": "on",
            "sort": "release_new",
        }

    v["pagenum"] = str(
        page_number
    )

    encoded_v = json.dumps(
        v,
        ensure_ascii=False,
        separators=(",", ":")
    )

    new_query = urlencode({
        "v": encoded_v
    })

    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))


# =========================================
# ポップアップ除去
# =========================================

async def remove_modal(page):

    try:

        await page.evaluate("""
        () => {

            const modal =
                document.querySelector(
                    '#first-modal-wrap'
                );

            if (modal) {

                modal.style.display =
                    'none';

                modal.style.visibility =
                    'hidden';

                modal.style.pointerEvents =
                    'none';
            }

            document.body.style.overflow =
                'auto';
        }
        """)

    except Exception:
        pass


# =========================================
# 一覧ページのURL取得
# =========================================

async def get_list_urls(page):

    urls = await page.locator(
        'a[href*="/card/detail/?id="]'
    ).evaluate_all("""
        els => els
            .map(e => e.href)
            .filter(Boolean)
    """)

    result = []

    seen = set()

    for url in urls:

        if url not in seen:

            seen.add(url)

            result.append(url)

    return result


# =========================================
# 全ページを直接取得
# =========================================

async def collect_all_urls(
    browser
):

    print()
    print("=" * 40)
    print("★ 公式カードURL全件取得 ★")
    print("ページ番号直接指定方式")
    print("=" * 40)

    page = await browser.new_page()

    page.set_default_timeout(
        30000
    )

    all_urls = []
    seen = set()

    # 最初のページを開く
    await page.goto(
        LIST_URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    await page.wait_for_timeout(
        2500
    )

    # -------------------------------------
    # まず公式の総カード数を取得
    # -------------------------------------

    try:

        body_text = await page.locator(
            "body"
        ).inner_text()

        match = re.search(
            r"([0-9,]+)枚",
            body_text
        )

        if match:

            total_cards = int(
                match.group(1)
                .replace(",", "")
            )

        else:

            total_cards = 23478

    except Exception:

        total_cards = 23478

    total_pages = (
        total_cards + PER_PAGE - 1
    ) // PER_PAGE

    print(
        f"公式カード総数: "
        f"{total_cards}"
    )

    print(
        f"予定ページ数: "
        f"{total_pages}"
    )

    # =====================================
    # ページ1～最後まで直接アクセス
    # =====================================

    for page_number in range(
        1,
        total_pages + 1
    ):

        page_url = make_page_url(
            LIST_URL,
            page_number
        )

        success = False

        for attempt in range(
            1,
            RETRIES + 1
        ):

            try:

                await page.goto(
                    page_url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                await page.wait_for_timeout(
                    700
                )

                await remove_modal(
                    page
                )

                current_urls = (
                    await get_list_urls(
                        page
                    )
                )

                # ---------------------------------
                # URLが取れたら成功
                # ---------------------------------

                if current_urls:

                    added = 0

                    for url in current_urls:

                        if url not in seen:

                            seen.add(url)

                            all_urls.append(
                                url
                            )

                            added += 1

                    print(
                        f"一覧ページ "
                        f"{page_number}: "
                        f"+{added} URL / "
                        f"累計 {len(all_urls)}"
                    )

                    success = True

                    break

                print(
                    f"ページ{page_number}: "
                    f"URL 0件 "
                    f"({attempt}/{RETRIES})"
                )

            except Exception as e:

                print(
                    f"ページ{page_number} "
                    f"取得失敗 "
                    f"({attempt}/{RETRIES}): "
                    f"{type(e).__name__}"
                )

                await asyncio.sleep(
                    1
                )

        # ---------------------------------
        # ページ取得失敗
        # ---------------------------------

        if not success:

            print(
                f"★ ページ{page_number} "
                f"取得失敗 ★"
            )

    await page.close()

    print()
    print("=" * 40)
    print(
        f"★ 公式URL総数: "
        f"{len(all_urls)} ★"
    )
    print("=" * 40)

    return all_urls


# =========================================
# カード詳細取得
# =========================================

async def fetch_card(
    context,
    url,
    semaphore
):

    async with semaphore:

        for attempt in range(
            1,
            RETRIES + 1
        ):

            page = None

            try:

                page = await context.new_page()

                page.set_default_timeout(
                    20000
                )

                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=30000
                )

                await page.wait_for_timeout(
                    300
                )

                await remove_modal(
                    page
                )

                html = await page.content()

                card = parse_card(
                    html,
                    url
                )

                await page.close()

                if card:
                    return card

            except Exception as e:

                if page:

                    try:
                        await page.close()
                    except Exception:
                        pass

                if attempt < RETRIES:

                    await asyncio.sleep(
                        1
                    )

                else:

                    print(
                        f"取得失敗: {url}"
                    )

    return None


# =========================================
# 詳細カード一括取得
# =========================================

async def fetch_cards(
    browser,
    cards,
    remaining
):

    context = await browser.new_context()

    semaphore = asyncio.Semaphore(
        CONCURRENCY
    )

    total = len(remaining)

    success_count = 0
    failed_count = 0

    for start in range(
        0,
        total,
        BATCH_SIZE
    ):

        batch = remaining[
            start:
            start + BATCH_SIZE
        ]

        print()
        print("=" * 40)
        print(
            f"詳細取得 "
            f"{start + 1} ～ "
            f"{min(start + BATCH_SIZE, total)} "
            f"/ {total}"
        )
        print("=" * 40)

        tasks = []

        for card_id, url in batch:

            tasks.append(
                fetch_card(
                    context,
                    url,
                    semaphore
                )
            )

        results = await asyncio.gather(
            *tasks
        )

        for card in results:

            if card:

                cards[
                    card["id"]
                ] = card

                success_count += 1

                if (
                    card["type"]
                    == "ツインパクト"
                ):

                    print(
                        "ツインパクト取得: "
                        + card["name"]
                    )

            else:

                failed_count += 1

        save_cards(cards)

        print(
            f"今回までの成功: "
            f"{success_count}枚"
        )

        print(
            f"今回までの失敗: "
            f"{failed_count}枚"
        )

        print(
            f"現在JSON: "
            f"{len(cards)}枚"
        )

    await context.close()

    return success_count, failed_count


# =========================================
# メイン
# =========================================

async def main():

    print()
    print("=" * 40)
    print("★ デュエマ公式カード全件更新 ★")
    print("ページ番号直接指定版")
    print("再開対応 / ツインパクト対応")
    print("=" * 40)

    # -------------------------------------
    # 既存データ
    # -------------------------------------

    cards = load_existing()

    print(
        f"既存データ: "
        f"{len(cards)}枚"
    )

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        # -------------------------------------
        # 公式URL全部取得
        # -------------------------------------

        urls = await collect_all_urls(
            browser
        )

        # -------------------------------------
        # 未取得だけ抽出
        # -------------------------------------

        remaining = []

        for url in urls:

            match = re.search(
                r"[?&]id=([^&]+)",
                url
            )

            if not match:
                continue

            card_id = match.group(1)

            if card_id not in cards:

                remaining.append(
                    (
                        card_id,
                        url
                    )
                )

        print()
        print("=" * 40)
        print(
            f"公式URL: "
            f"{len(urls)}枚"
        )

        print(
            f"取得済み: "
            f"{len(cards)}枚"
        )

        print(
            f"残り: "
            f"{len(remaining)}枚"
        )

        print("=" * 40)

        # -------------------------------------
        # 詳細取得
        # -------------------------------------

        if remaining:

            await fetch_cards(
                browser,
                cards,
                remaining
            )

        # -------------------------------------
        # 失敗分をもう一度取得
        # -------------------------------------

        failed = []

        for card_id, url in remaining:

            if card_id not in cards:

                failed.append(
                    (
                        card_id,
                        url
                    )
                )

        if failed:

            print()
            print("=" * 40)
            print(
                f"★ 失敗分再取得: "
                f"{len(failed)}枚 ★"
            )
            print("=" * 40)

            await fetch_cards(
                browser,
                cards,
                failed
            )

        await browser.close()

    # -------------------------------------
    # 最終保存
    # -------------------------------------

    save_cards(cards)

    twin_count = sum(
        1
        for card in cards.values()
        if card.get("type")
        == "ツインパクト"
    )

    print()
    print("=" * 40)
    print("★ 全件処理終了 ★")
    print(
        f"総カード数: "
        f"{len(cards)}枚"
    )
    print(
        f"ツインパクト: "
        f"{twin_count}枚"
    )
    print(
        f"保存先: "
        f"{OUT}"
    )
    print("=" * 40)


if __name__ == "__main__":
    asyncio.run(main())
