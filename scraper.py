import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


OUT = Path("data/cards.json")

TEST_URLS = [
    "https://dm.takaratomy.co.jp/card/detail/?id=dm26rp3-OR001",
    "https://dm.takaratomy.co.jp/card/detail/?id=dm26sd1-u012",
]


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
    for img in soup.find_all("img"):
        src = img.get("src")

        if not src:
            continue

        if "card" in src.lower():
            if src.startswith("/"):
                src = "https://dm.takaratomy.co.jp" + src

            return src

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
        "type": get_value(lines, "カードの種類"),
        "civilization": get_value(lines, "文明"),
        "rarity": get_value(lines, "レアリティ"),
        "power": get_value(lines, "パワー"),
        "cost": get_value(lines, "コスト"),
        "mana": get_value(lines, "マナ"),
        "race": get_value(lines, "種族"),
        "illustrator": get_value(lines, "イラストレーター"),
        "abilities": get_abilities(lines),
        "flavor": get_flavor(lines),
    }


def parse_card(page, url):

    print(
        f"DETAIL TEST: {url}",
        flush=True
    )

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=120000
    )

    page.wait_for_timeout(1500)

    soup = BeautifulSoup(
        page.content(),
        "html.parser"
    )

    # タイトル
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

    # ID
    card_id = url.split(
        "?id=",
        1
    )[1]

    # 画像
    image = get_image(soup)

    # ページ本文
    lines = get_lines(soup)

    # 面を分割
    side_blocks = split_sides(lines)

    sides = []

    for block in side_blocks:

        side = parse_side(block)

        if side["type"]:
            sides.append(side)

    # 重複削除
    unique_sides = []

    for side in sides:

        if side not in unique_sides:
            unique_sides.append(side)

    sides = unique_sides

    # ツインパクト判定
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
        "sides": sides
    }

    # 通常カード
    if len(sides) == 1:

        side = sides[0]

        card["type"] = side["type"]
        card["civilization"] = side["civilization"]
        card["rarity"] = side["rarity"]
        card["power"] = side["power"]
        card["cost"] = side["cost"]
        card["mana"] = side["mana"]
        card["race"] = side["race"]
        card["illustrator"] = side["illustrator"]
        card["abilities"] = side["abilities"]
        card["flavor"] = side["flavor"]

    return card


def main():

    print(
        "================================",
        flush=True
    )

    print(
        "★ v3 ツインパクト解析テスト ★",
        flush=True
    )

    print(
        "通常カード1枚＋ツインパクト1枚",
        flush=True
    )

    print(
        "一覧ページは取得しません",
        flush=True
    )

    print(
        "================================",
        flush=True
    )

    cards = []

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

        for index, url in enumerate(
            TEST_URLS,
            1
        ):

            try:

                card = parse_card(
                    page,
                    url
                )

                cards.append(card)

                print(
                    f"★ {index}/2 成功: "
                    f"{card['name']}",
                    flush=True
                )

                print(
                    f"  面数: {len(card['sides'])}",
                    flush=True
                )

                for side_index, side in enumerate(
                    card["sides"],
                    1
                ):

                    print(
                        f"  面{side_index}: "
                        f"{side['type']} / "
                        f"{side['civilization']} / "
                        f"{side['rarity']} / "
                        f"パワー{side['power']} / "
                        f"コスト{side['cost']} / "
                        f"マナ{side['mana']} / "
                        f"種族{side['race']}",
                        flush=True
                    )

                    print(
                        f"    能力: "
                        f"{side['abilities']}",
                        flush=True
                    )

            except Exception as e:

                print(
                    f"★ {index}/2 失敗: {e}",
                    flush=True
                )

        browser.close()

    # JSON保存
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

    print(
        "================================",
        flush=True
    )

    print(
        f"★ TEST COMPLETE: {len(cards)}枚 ★",
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
    main()
