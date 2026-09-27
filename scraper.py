import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


OUT = Path("data/cards.json")

# ★テストするのはこの2枚だけ
TEST_URLS = [
    "https://dm.takaratomy.co.jp/card/detail/?id=dm26rp3-OR001",
    "https://dm.takaratomy.co.jp/card/detail/?id=dm26sd1-u012",
]


def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def get_card(page, url):
    print("DETAIL TEST:", url, flush=True)

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=120000
    )

    page.wait_for_timeout(1000)

    soup = BeautifulSoup(
        page.content(),
        "html.parser"
    )

    # カード名・番号
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

    card_id = url.split("?id=", 1)[1]

    # 画像URL
    image = ""

    for img in soup.find_all("img"):
        src = img.get("src")

        if src and "card" in src.lower():
            image = src

            if image.startswith("/"):
                image = (
                    "https://dm.takaratomy.co.jp"
                    + image
                )

            break

    # ページ内テキスト
    lines = []

    for line in soup.get_text(
        "\n",
        strip=True
    ).splitlines():

        line = clean(line)

        if line:
            lines.append(line)

    card = {
        "id": card_id,
        "name": name,
        "number": number,
        "url": url,
        "image": image,
        "sides": [],
    }

    # 基本情報を取得
    labels = {
        "カードの種類": "type",
        "文明": "civilization",
        "レアリティ": "rarity",
        "パワー": "power",
        "コスト": "cost",
        "マナ": "mana",
        "種族": "race",
        "イラストレーター": "illustrator",
    }

    for i, line in enumerate(lines):

        if line in labels and i + 1 < len(lines):

            key = labels[line]
            value = lines[i + 1]

            card[key] = value

    # 特殊能力
    abilities = []

    for i, line in enumerate(lines):

        if line == "特殊能力":

            text = []

            for j in range(
                i + 1,
                min(i + 30, len(lines))
            ):

                if lines[j] in [
                    "フレーバー",
                    "商品情報",
                    "イラストレーター",
                ]:
                    break

                text.append(lines[j])

            if text:
                abilities.append(
                    " ".join(text)
                )

    if abilities:
        card["abilities"] = abilities

    # ツインパクト判定
    if "/" in name:
        card["type"] = "ツインパクト"

    return card


def main():

    print(
        "================================",
        flush=True
    )

    print(
        "★ 2枚だけのDETAIL TEST ★",
        flush=True
    )

    print(
        "一覧ページは一切取得しません",
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

        for i, url in enumerate(
            TEST_URLS,
            1
        ):

            try:

                card = get_card(
                    page,
                    url
                )

                cards.append(card)

                print(
                    f"★ {i}/2 成功: {card['name']}",
                    flush=True
                )

            except Exception as e:

                print(
                    f"★ {i}/2 失敗: {e}",
                    flush=True
                )

        browser.close()

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
        "================================",
        flush=True
    )


if __name__ == "__main__":
    main()
