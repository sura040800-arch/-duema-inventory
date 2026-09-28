import asyncio
import json
import os
import re

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE_URL = "https://dm.takaratomy.co.jp/card/detail/?id="
INPUT = "data/card_ids.json"
OUTPUT = "data/cards_test100.json"

TEST_COUNT = 100
CONCURRENCY = 6


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def parse_card(card_id, html):
    soup = BeautifulSoup(html, "html.parser")

    # ページ全体の文字
    text = soup.get_text("\n", strip=True)

    # タイトル
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title:
        title = clean(og_title.get("content", ""))

    if not title:
        h1 = soup.find("h1")
        if h1:
            title = clean(h1.get_text(" ", strip=True))

    # カードの種類ごとに分割
    parts = re.split(r"カードの種類", text)

    sides = []

    for part in parts[1:]:
        lines = [
            clean(x)
            for x in part.splitlines()
            if clean(x)
        ]

        if not lines:
            continue

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

        # できるだけラベルから取得
        labels = [
            ("文明", "civilization"),
            ("レアリティ", "rarity"),
            ("パワー", "power"),
            ("コスト", "cost"),
            ("マナ", "mana"),
            ("種族", "race"),
            ("イラストレーター", "illustrator"),
        ]

        for i, line in enumerate(lines):
            for label, key in labels:
                if line.startswith(label):
                    value = line[len(label):].strip()

                    if not value and i + 1 < len(lines):
                        value = lines[i + 1]

                    if value:
                        side[key] = value

        # カード名らしいものを探す
        for line in lines[:15]:
            if (
                line
                and line not in side.values()
                and len(line) <= 100
                and not any(
                    line.startswith(x)
                    for x in [
                        "文明",
                        "レアリティ",
                        "パワー",
                        "コスト",
                        "マナ",
                        "種族",
                        "イラストレーター",
                    ]
                )
            ):
                side["name"] = line
                break

        # 能力・フレーバー候補
        ability_lines = []

        for line in lines:
            if (
                "この" in line
                or "自分" in line
                or "相手" in line
                or "カード" in line
                or "山札" in line
                or "墓地" in line
                or "手札" in line
                or "バトルゾーン" in line
            ):
                ability_lines.append(line)

        side["ability"] = "\n".join(
            dict.fromkeys(ability_lines)
        )

        if side["name"] or side["type"] or side["ability"]:
            sides.append(side)

    # ツインパクト判定
    is_twin = len(sides) >= 2

    result = {
        "id": card_id,
        "name": title,
        "type": "ツインパクト" if is_twin else "",
        "sides": sides,
    }

    return result


async def fetch_one(browser, card_id):
    url = BASE_URL + card_id

    for attempt in range(3):
        page = None

        try:
            page = await browser.new_page()

            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(500)

            html = await page.content()

            card = parse_card(card_id, html)

            if card["sides"] or card["name"]:
                return card

            print(
                f"[警告] {card_id}: データを確認できません",
                flush=True,
            )

        except Exception as e:
            print(
                f"[再試行 {attempt + 1}] {card_id}: {e}",
                flush=True,
            )

        finally:
            if page:
                await page.close()

        await asyncio.sleep(1)

    return {
        "id": card_id,
        "name": "",
        "type": "",
        "sides": [],
        "error": True,
    }


async def main():

    with open(INPUT, "r", encoding="utf-8") as f:
        card_ids = json.load(f)

    card_ids = card_ids[:TEST_COUNT]

    print("=" * 60)
    print("カード詳細取得テスト")
    print("=" * 60)
    print("対象:", len(card_ids), "枚")
    print("同時取得:", CONCURRENCY, "枚")
    print("")

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        results = []

        for start in range(0, len(card_ids), CONCURRENCY):

            batch = card_ids[
                start:start + CONCURRENCY
            ]

            batch_results = await asyncio.gather(
                *[
                    fetch_one(browser, card_id)
                    for card_id in batch
                ]
            )

            results.extend(batch_results)

            success = sum(
                1
                for x in results
                if not x.get("error")
            )

            print(
                f"進捗: {len(results)}/{len(card_ids)} "
                f"成功: {success}",
                flush=True,
            )

        await browser.close()

    os.makedirs("data", exist_ok=True)

    with open(
        OUTPUT,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            results,
            f,
            ensure_ascii=False,
            indent=2,
        )

    success = sum(
        1
        for x in results
        if not x.get("error")
    )

    errors = len(results) - success

    print("")
    print("=" * 60)
    print("テスト終了")
    print("取得:", success)
    print("失敗:", errors)
    print("保存:", OUTPUT)
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
