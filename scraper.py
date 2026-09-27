import asyncio
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


OUT = Path("data/cards.json")

# ==============================
# 今回は50枚だけテスト
# ==============================
LIMIT = 50

LIST_URL = "https://dm.takaratomy.co.jp/card/"

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


def clean(text):
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def get_image(soup):
    candidates = []

    for img in soup.find_all("img"):
        src = img.get("src")

        if not src:
            continue

        if src.startswith("//"):
            src = "https:" + src

        elif src.startswith("/"):
            src = "https://dm.takaratomy.co.jp" + src

        src_lower = src.lower()

        if (
            "wp-content/uploads" in src_lower
            or "/card/" in src_lower
        ):
            candidates.append(src)

    if candidates:
        return candidates[0]

    return ""


def get_lines(soup):
    text = soup.get_text("\n", strip=True)

    lines = []

    for line in text.splitlines():

        line = clean(line)

        if line:
            lines.append(line)

    return lines


def get_value(lines, label):

    for i, line in enumerate(lines):

        if line == label:

            if i + 1 >= len(lines):
                return ""

            value = lines[i + 1]

            if value in LABELS:
                return ""

            if value == "---":
                return ""

            return clean(value)

    return ""


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


def get_flavor(lines):

    start = None

    for i, line in enumerate(lines):

        if line == "フレーバー":
            start = i + 1
            break

    if start is None:
        return ""

    flavor_parts = []

    for line in lines[start:]:

        if line == "---":
            continue

        if line == "商品情報":
            break

        if line == "同名カードが含まれる商品を表示":
            break

        flavor_parts.append(line)

    return clean(" ".join(flavor_parts))


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

            product_index = block.index("商品情報")

            block = block[:product_index]

        if "同名カードが含まれる商品を表示" in block:

            same_index = block.index(
                "同名カードが含まれる商品を表示"
            )

            block = block[:same_index]

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


def parse_card_html(html, url):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

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

    card_id = url.split(
        "?id=",
        1
    )[1]

    image = get_image(soup)

    lines = get_lines(soup)

    side_blocks = split_sides(lines)

    sides = []

    for block in side_blocks:

        side = parse_side(block)

        if side["type"]:

            sides.append(side)

    unique_sides = []

    for side in sides:

        if side not in unique_sides:

            unique_sides.append(side)

    sides = unique_sides

    is_twin = (
        len(sides) >= 2
        or "/" in name
    )

    card = {
        "id": card_id,
        "name": name,
        "number": number,
        "url": url,
        "image": image,
        "type": "ツインパクト" if is_twin else "",
        "sides": sides,
    }

    # 通常カードは今まで通り
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


async def get_card_urls(page):

    print(
        "公式カード一覧を取得中...",
        flush=True
    )

    await page.goto(
        LIST_URL,
        wait_until="domcontentloaded",
        timeout=120000
    )

    await page.wait_for_timeout(3000)

    links = await page.locator(
        'a[href*="/card/detail/?id="]'
    ).evaluate_all(
        """
        elements => elements.map(
            e => e.href
        )
        """
    )

    unique = []

    for url in links:

        if url not in unique:

            unique.append(url)

    print(
        f"一覧から {len(unique)} URL取得",
        flush=True
    )

    return unique[:LIMIT]


async def scrape_detail(
    browser,
    url,
    index,
    total
):

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

        await page.wait_for_timeout(800)

        html = await page.content()

        await page.close()

        card = parse_card_html(
            html,
            url
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
            f"[{index}/{total}] 失敗: {url}",
            flush=True
        )

        print(
            f"  {e}",
            flush=True
        )

        return None


async def main():

    print(
        "================================",
        flush=True
    )

    print(
        "★ 公式カード50枚テスト ★",
        flush=True
    )

    print(
        "一覧 → 詳細 → JSON",
        flush=True
    )

    print(
        "================================",
        flush=True
    )

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        list_page = await browser.new_page()

        urls = await get_card_urls(
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

        total = len(urls)

        print(
            f"今回取得するカード数: {total}",
            flush=True
        )

        # 同時に6枚ずつ取得
        semaphore = asyncio.Semaphore(6)

        async def worker(index, url):

            async with semaphore:

                return await scrape_detail(
                    browser,
                    url,
                    index,
                    total
                )

        tasks = []

        for index, url in enumerate(
            urls,
            1
        ):

            tasks.append(
                worker(
                    index,
                    url
                )
            )

        results = await asyncio.gather(
            *tasks
        )

        cards = []

        for card in results:

            if card is not None:

                cards.append(card)

        await browser.close()

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

    twin_count = 0

    for card in cards:

        if len(
            card.get("sides", [])
        ) >= 2:

            twin_count += 1

    print(
        "================================",
        flush=True
    )

    print(
        f"★ TEST COMPLETE ★",
        flush=True
    )

    print(
        f"取得成功: {len(cards)}枚",
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

    asyncio.run(
        main()
    )
