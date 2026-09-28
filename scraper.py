import asyncio
import json
import os
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

INPUT = "data/card_ids.json"
OUTPUT = "data/cards.json"

CONCURRENCY = 12
SAVE_EVERY = 250


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def get_lines(soup):
    return [
        clean(x)
        for x in soup.get_text("\n", strip=True).splitlines()
        if clean(x)
    ]


def value_after(lines, label):
    for i, line in enumerate(lines):
        if line.startswith(label):
            value = line[len(label):].strip()

            if value:
                return value

            if i + 1 < len(lines):
                return lines[i + 1]

    return ""


def parse_side(lines):
    side = {
        "type": "",
        "name": "",
        "civilization": "",
        "rarity": "",
        "power": "",
        "cost": "",
        "mana": "",
        "race": "",
        "ability": "",
        "flavor": "",
        "illustrator": "",
    }

    side["civilization"] = value_after(lines, "文明")
    side["rarity"] = value_after(lines, "レアリティ")
    side["power"] = value_after(lines, "パワー")
    side["cost"] = value_after(lines, "コスト")
    side["mana"] = value_after(lines, "マナ")
    side["race"] = value_after(lines, "種族")
    side["illustrator"] = value_after(
        lines, "イラストレーター"
    )

    # カード種類
    for line in lines:
        if line.startswith("クリーチャー"):
            side["type"] = "クリーチャー"
            break
        if line.startswith("呪文"):
            side["type"] = "呪文"
            break
        if line.startswith("タマシード"):
            side["type"] = "タマシード"
            break
        if line.startswith("クロスギア"):
            side["type"] = "クロスギア"
            break
        if line.startswith("フィールド"):
            side["type"] = "フィールド"
            break

    # 名前
    skip = {
        "文明",
        "レアリティ",
        "パワー",
        "コスト",
        "マナ",
        "種族",
        "イラストレーター",
        "カードの種類",
    }

    for line in lines[:20]:
        if not line:
            continue

        if any(line.startswith(x) for x in skip):
            continue

        if line in [
            "クリーチャー",
            "呪文",
            "タマシード",
            "クロスギア",
            "フィールド",
        ]:
            continue

        if len(line) <= 100:
            side["name"] = line
            break

    # 能力
    ability = []

    keywords = [
        "このクリーチャー",
        "このカード",
        "この呪文",
        "自分",
        "相手",
        "山札",
        "墓地",
        "手札",
        "バトルゾーン",
        "マナゾーン",
        "召喚",
        "攻撃",
        "ブロック",
        "破壊",
        "出た時",
        "登場時",
        "S・トリガー",
        "G・ストライク",
        "シンカライズ",
        "メタモーフ",
    ]

    for line in lines:
        if any(k in line for k in keywords):
            if line not in ability:
                ability.append(line)

    side["ability"] = "\n".join(ability)

    return side


def parse_card(card_id, html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    lines = get_lines(soup)

    # カード名
    name = ""

    og = soup.find(
        "meta",
        property="og:title"
    )

    if og:
        name = clean(
            og.get("content", "")
        )

    if not name:
        h1 = soup.find("h1")
        if h1:
            name = clean(
                h1.get_text(" ", strip=True)
            )

    # カード種類で面を分割
    positions = [
        i
        for i, line in enumerate(lines)
        if line == "カードの種類"
    ]

    sides = []

    if positions:

        for index, start in enumerate(positions):

            end = (
                positions[index + 1]
                if index + 1 < len(positions)
                else len(lines)
            )

            part = lines[start:end]

            if part:
                sides.append(
                    parse_side(part)
                )

    if not sides:
        sides = [parse_side(lines)]

    # 名前が取れなかった場合
    if sides and not sides[0]["name"]:
        sides[0]["name"] = name

    # ツインパクト判定
    twin = len(sides) >= 2

    result = {
        "id": card_id,
        "name": name,
        "type": "ツインパクト" if twin else sides[0].get("type", ""),
        "civilization": sides[0].get("civilization", ""),
        "rarity": sides[0].get("rarity", ""),
        "power": sides[0].get("power", ""),
        "cost": sides[0].get("cost", ""),
        "mana": sides[0].get("mana", ""),
        "race": sides[0].get("race", ""),
        "ability": sides[0].get("ability", ""),
        "flavor": sides[0].get("flavor", ""),
        "illustrator": sides[0].get("illustrator", ""),
        "sides": sides,
    }

    return result


async def fetch_card(browser, card_id):

    url = (
        "https://dm.takaratomy.co.jp/"
        "card/detail/?id="
        + card_id
    )

    for attempt in range(3):

        page = None

        try:

            page = await browser.new_page()

            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            await page.wait_for_timeout(300)

            html = await page.content()

            card = parse_card(
                card_id,
                html
            )

            if card["name"] or card["sides"]:

                return card

            raise RuntimeError(
                "カード情報を取得できませんでした"
            )

        except Exception as e:

            print(
                f"[retry {attempt + 1}] "
                f"{card_id}: {e}",
                flush=True
            )

            await asyncio.sleep(1)

        finally:

            if page:
                await page.close()

    return {
        "id": card_id,
        "name": "",
        "type": "",
        "sides": [],
        "error": True,
    }


async def main():

    with open(
        INPUT,
        "r",
        encoding="utf-8"
    ) as f:

        card_ids = json.load(f)

    # 既存データを読み込む
    cards = {}

    if os.path.exists(OUTPUT):

        try:

            with open(
                OUTPUT,
                "r",
                encoding="utf-8"
            ) as f:

                old = json.load(f)

            for card in old:

                if card.get("id"):
                    cards[card["id"]] = card

        except Exception as e:

            print(
                "既存cards.json読み込み失敗:",
                e
            )

    pending = [
        card_id
        for card_id in card_ids
        if card_id not in cards
    ]

    print("=" * 60)
    print("デュエマ公式カード詳細 本番取得")
    print("=" * 60)
    print("公式ID:", len(card_ids))
    print("既存:", len(cards))
    print("今回取得:", len(pending))
    print("同時取得:", CONCURRENCY)
    print("=" * 60)

    if not pending:

        print("未取得カードはありません。")
        return

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        completed = 0
        failed = []

        for start in range(
            0,
            len(pending),
            CONCURRENCY
        ):

            batch = pending[
                start:start + CONCURRENCY
            ]

            results = await asyncio.gather(
                *[
                    fetch_card(
                        browser,
                        card_id
                    )
                    for card_id in batch
                ]
            )

            for card in results:

                if card.get("error"):

                    failed.append(
                        card["id"]
                    )

                else:

                    cards[card["id"]] = card

            completed += len(batch)

            # 250枚ごとに保存
            if (
                completed % SAVE_EVERY == 0
                or completed == len(pending)
            ):

                os.makedirs(
                    "data",
                    exist_ok=True
                )

                ordered = [
                    cards[card_id]
                    for card_id in card_ids
                    if card_id in cards
                ]

                with open(
                    OUTPUT,
                    "w",
                    encoding="utf-8"
                ) as f:

                    json.dump(
                        ordered,
                        f,
                        ensure_ascii=False,
                        indent=2
                    )

            print(
                f"進捗: {completed}/{len(pending)} "
                f" / 累計: {len(cards)} "
                f" / 失敗: {len(failed)}",
                flush=True
            )

        await browser.close()

    print("")
    print("=" * 60)
    print("取得終了")
    print("総カード:", len(cards))
    print("今回取得:", len(pending))
    print("失敗:", len(failed))
    print("保存:", OUTPUT)
    print("=" * 60)

    if failed:

        with open(
            "data/failed_card_ids.json",
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                failed,
                f,
                ensure_ascii=False,
                indent=2
            )

        print(
            "失敗ID:",
            "data/failed_card_ids.json"
        )


if __name__ == "__main__":
    asyncio.run(main())
