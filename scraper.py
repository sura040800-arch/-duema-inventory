import asyncio
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


# ==========================================
# 設定
# ==========================================

OUT = Path("data/cards.json")

LIST_URL = "https://dm.takaratomy.co.jp/card/"

# 同時取得数
CONCURRENCY = 8

# 何枚ごとにGitHubへ保存するか
CHECKPOINT = 250

# 詳細ページの最大リトライ回数
RETRIES = 3


LABELS = [
    "カードの種類",
    "文明",
    "レアリティ",
    "パワー",
    "コスト",
    "マナ",
    "種族",
    "イラストレーター",
    "特殊能力",
    "フレーバー",
    "商品情報",
]


# ==========================================
# 共通
# ==========================================

def clean(text):
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def get_lines(soup):
    text = soup.get_text("\n", strip=True)

    lines = []

    for line in text.splitlines():

        line = clean(line)

        if line:
            lines.append(line)

    return lines


def get_image(soup):

    candidates = []

    for img in soup.find_all("img"):

        src = img.get("src")

        if not src:
            continue

        if src.startswith("//"):
            src = "https:" + src

        elif src.startswith("/"):
            src = urljoin(
                "https://dm.takaratomy.co.jp",
                src
            )

        lower = src.lower()

        if (
            "wp-content/uploads" in lower
            or "/card/" in lower
        ):
            candidates.append(src)

    if candidates:
        return candidates[0]

    return ""


def get_value(lines, label):

    for i, line in enumerate(lines):

        if line != label:
            continue

        if i + 1 >= len(lines):
            return ""

        value = lines[i + 1]

        if value in LABELS:
            return ""

        if value == "---":
            return ""

        return clean(value)

    return ""


# ==========================================
# 能力
# ==========================================

def get_abilities(lines):

    start = None
    end = None

    for i, line in enumerate(lines):

        if line == "特殊能力":

            start = i + 1

            break

    if start is None:
        return []

    for i in range(start, len(lines)):

        if lines[i] == "フレーバー":

            end = i

            break

    if end is None:
        end = len(lines)

    abilities = []

    for line in lines[start:end]:

        line = clean(line)

        if not line:
            continue

        if line == "---":
            continue

        line = re.sub(
            r"^\*\s*",
            "",
            line
        )

        if line in [
            "商品情報",
            "同名カードが含まれる商品を表示",
        ]:
            break

        abilities.append(line)

    return abilities


# ==========================================
# フレーバー
# ==========================================

def get_flavor(lines):

    start = None

    for i, line in enumerate(lines):

        if line == "フレーバー":

            start = i + 1

            break

    if start is None:
        return ""

    parts = []

    for line in lines[start:]:

        if line == "---":
            continue

        if line == "商品情報":
            break

        if line == "同名カードが含まれる商品を表示":
            break

        parts.append(line)

    return clean(" ".join(parts))


# ==========================================
# ツインパクトなどの面分割
# ==========================================

def split_sides(lines):

    positions = []

    for i, line in enumerate(lines):

        if line == "カードの種類":

            positions.append(i)

    sides = []

    for index, start in enumerate(positions):

        if index + 1 < len(positions):

            end = positions[index + 1]

        else:

            end = len(lines)

        block = lines[start:end]

        if "商品情報" in block:

            block = block[
                :block.index("商品情報")
            ]

        if "同名カードが含まれる商品を表示" in block:

            block = block[
                :block.index(
                    "同名カードが含まれる商品を表示"
                )
            ]

        sides.append(block)

    return sides


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

        "abilities": get_abilities(lines),

        "flavor": get_flavor(lines),
    }


# ==========================================
# カード解析
# ==========================================

def parse_card(html, url):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # --------------------------
    # タイトル
    # --------------------------

    title = ""

    if soup.title:

        title = clean(
            soup.title.get_text(
                " ",
                strip=True
            )
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

    # --------------------------
    # ID
    # --------------------------

    if "?id=" in url:

        card_id = url.split(
            "?id=",
            1
        )[1]

    else:

        card_id = url

    # --------------------------
    # 本文
    # --------------------------

    lines = get_lines(soup)

    blocks = split_sides(lines)

    sides = []

    for block in blocks:

        side = parse_side(block)

        if side["type"]:

            sides.append(side)

    # 重複面除去

    unique_sides = []

    for side in sides:

        if side not in unique_sides:

            unique_sides.append(side)

    sides = unique_sides

    # --------------------------
    # ツインパクト判定
    # --------------------------

    is_twin = (
        len(sides) >= 2
        or "/" in name
    )

    card = {

        "id": card_id,

        "name": name,

        "number": number,

        "url": url,

        "image": get_image(soup),

        "type": (
            "ツインパクト"
            if is_twin
            else ""
        ),

        "sides": sides,
    }

    # 通常カード

    if len(sides) == 1:

        side = sides[0]

        card["type"] = side["type"]

        card["civilization"] = (
            side["civilization"]
        )

        card["rarity"] = (
            side["rarity"]
        )

        card["power"] = (
            side["power"]
        )

        card["cost"] = (
            side["cost"]
        )

        card["mana"] = (
            side["mana"]
        )

        card["race"] = (
            side["race"]
        )

        card["illustrator"] = (
            side["illustrator"]
        )

        card["abilities"] = (
            side["abilities"]
        )

        card["flavor"] = (
            side["flavor"]
        )

    return card


# ==========================================
# JSON読み込み
# ==========================================

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

        result = {}

        for card in data:

            if card.get("id"):

                result[card["id"]] = card

        print(
            f"既存データ: {len(result)}枚",
            flush=True
        )

        return result

    except Exception as e:

        print(
            f"既存JSON読み込み失敗: {e}",
            flush=True
        )

        return {}


# ==========================================
# JSON保存
# ==========================================

def save_cards(cards):

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    data = list(cards.values())

    data.sort(
        key=lambda x: (
            x.get("number", ""),
            x.get("id", "")
        )
    )

    temp = OUT.with_suffix(".tmp")

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp.replace(OUT)

    print(
        f"JSON保存: {len(data)}枚",
        flush=True
    )


# ==========================================
# GitHub checkpoint
# ==========================================

def checkpoint_git():

    try:

        subprocess.run(
            [
                "git",
                "config",
                "user.name",
                "github-actions[bot]"
            ],
            check=True
        )

        subprocess.run(
            [
                "git",
                "config",
                "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com"
            ],
            check=True
        )

        subprocess.run(
            [
                "git",
                "add",
                "data/cards.json"
            ],
            check=True
        )

        diff = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--quiet"
            ]
        )

        if diff.returncode == 0:

            print(
                "GitHub保存: 変更なし",
                flush=True
            )

            return True

        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "自動更新: 公式カードデータ"
            ],
            check=True
        )

        subprocess.run(
            [
                "git",
                "push",
                "origin",
                "main"
            ],
            check=True
        )

        print(
            "GitHub保存: 成功",
            flush=True
        )

        return True

    except Exception as e:

        print(
            f"GitHub保存失敗: {e}",
            flush=True
        )

        return False


# ==========================================
# 公式一覧からURL取得
# ==========================================

async def collect_all_urls(page):

    print(
        "================================",
        flush=True
    )

    print(
        "★ 公式カードURL全件取得 ★",
        flush=True
    )

    print(
        "================================",
        flush=True
    )

    await page.goto(
        LIST_URL,
        wait_until="domcontentloaded",
        timeout=120000
    )

    await page.wait_for_timeout(3000)

    urls = set()

    page_number = 1

    while True:

        # --------------------------
        # 現在ページのカードURL
        # --------------------------

        current_urls = await page.locator(
            'a[href*="/card/detail/?id="]'
        ).evaluate_all(
            """
            elements =>
                elements.map(e => e.href)
            """
        )

        before = len(urls)

        for url in current_urls:

            if "?id=" in url:

                urls.add(url)

        added = len(urls) - before

        print(
            f"一覧ページ {page_number}: "
            f"+{added} URL / 累計 {len(urls)}",
            flush=True
        )

        # --------------------------
        # 次ページ
        # --------------------------

        next_number = page_number + 1

        selector = (
            f'a[data-page="{next_number}"]'
        )

        next_link = page.locator(
            selector
        ).first

        count = await next_link.count()

        if count == 0:

            print(
                "次ページなし",
                flush=True
            )

            break

        try:

            await next_link.click(
                timeout=30000
            )

            await page.wait_for_timeout(
                700
            )

            page_number += 1

        except Exception as e:

            print(
                f"ページ移動失敗: {e}",
                flush=True
            )

            break

        # 安全装置

        if page_number > 1000:

            print(
                "ページ数安全上限に到達",
                flush=True
            )

            break

    result = sorted(urls)

    print(
        "================================",
        flush=True
    )

    print(
        f"公式URL総数: {len(result)}",
        flush=True
    )

    print(
        "================================",
        flush=True
    )

    return result


# ==========================================
# 詳細ページ取得
# ==========================================

async def fetch_card(
    browser,
    semaphore,
    url,
    index,
    total
):

    async with semaphore:

        for attempt in range(
            1,
            RETRIES + 1
        ):

            page = None

            try:

                page = await browser.new_page(
                    viewport={
                        "width": 1280,
                        "height": 900
                    }
                )

                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=120000
                )

                # 必要最低限の待機

                await page.wait_for_timeout(
                    400
                )

                html = await page.content()

                card = parse_card(
                    html,
                    url
                )

                if not card["name"]:

                    raise Exception(
                        "カード名を取得できませんでした"
                    )

                print(
                    f"[{index}/{total}] "
                    f"{card['name']} "
                    f"面数={len(card['sides'])}",
                    flush=True
                )

                return card

            except Exception as e:

                print(
                    f"[{index}/{total}] "
                    f"失敗 {attempt}/{RETRIES}: "
                    f"{url}",
                    flush=True
                )

                if attempt < RETRIES:

                    await asyncio.sleep(
                        attempt * 2
                    )

            finally:

                if page:

                    try:

                        await page.close()

                    except Exception:

                        pass

        return None


# ==========================================
# メイン
# ==========================================

async def main():

    print(
        "================================",
        flush=True
    )

    print(
        "★ デュエマ公式カード全件更新 ★",
        flush=True
    )

    print(
        "再開対応 / ツインパクト対応",
        flush=True
    )

    print(
        "================================",
        flush=True
    )

    cards = load_existing()

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        # --------------------------
        # URL全件取得
        # --------------------------

        list_page = await browser.new_page()

        urls = await collect_all_urls(
            list_page
        )

        await list_page.close()

        if not urls:

            print(
                "カードURLを取得できませんでした。",
                flush=True
            )

            await browser.close()

            return

        # --------------------------
        # 既存カードを除外
        # --------------------------

        pending = []

        for url in urls:

            if "?id=" not in url:
                continue

            card_id = url.split(
                "?id=",
                1
            )[1]

            if card_id in cards:

                continue

            pending.append(url)

        print(
            f"公式URL: {len(urls)}枚",
            flush=True
        )

        print(
            f"取得済み: {len(cards)}枚",
            flush=True
        )

        print(
            f"残り: {len(pending)}枚",
            flush=True
        )

        # --------------------------
        # 詳細取得
        # --------------------------

        semaphore = asyncio.Semaphore(
            CONCURRENCY
        )

        completed_since_checkpoint = 0

        total_pending = len(pending)

        for start in range(
            0,
            total_pending,
            CONCURRENCY
        ):

            batch = pending[
                start:start + CONCURRENCY
            ]

            tasks = []

            for offset, url in enumerate(
                batch
            ):

                index = start + offset + 1

                tasks.append(
                    fetch_card(
                        browser,
                        semaphore,
                        url,
                        index,
                        total_pending
                    )
                )

            results = await asyncio.gather(
                *tasks
            )

            for card in results:

                if card is None:
                    continue

                cards[
                    card["id"]
                ] = card

                completed_since_checkpoint += 1

            # --------------------------
            # 定期保存
            # --------------------------

            if (
                completed_since_checkpoint
                >= CHECKPOINT
            ):

                save_cards(cards)

                checkpoint_git()

                completed_since_checkpoint = 0

        await browser.close()

    # --------------------------
    # 最終保存
    # --------------------------

    save_cards(cards)

    checkpoint_git()

    # --------------------------
    # 結果
    # --------------------------

    twin_count = 0

    for card in cards.values():

        if len(
            card.get("sides", [])
        ) >= 2:

            twin_count += 1

    print(
        "================================",
        flush=True
    )

    print(
        "★ 全件処理終了 ★",
        flush=True
    )

    print(
        f"総カード数: {len(cards)}枚",
        flush=True
    )

    print(
        f"ツインパクト: {twin_count}枚",
        flush=True
    )

    print(
        f"保存先: {OUT}",
        flush=True
    )

    print(
        "================================",
        flush=True
    )


if __name__ == "__main__":

    asyncio.run(main())
