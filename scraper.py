import asyncio
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


# =========================
# 設定
# =========================

OUT = Path("data/cards.json")

LIST_URL = "https://dm.takaratomy.co.jp/card/"

# 同時に何枚取得するか
CONCURRENCY = 8

# 何枚ごとに保存・GitHubへチェックポイントするか
CHECKPOINT = 250

# 失敗時の再試行回数
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
    "能力",
    "フレーバー",
]


# =========================
# 共通処理
# =========================

def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def get_lines(text):
    return [clean(x) for x in text.splitlines() if clean(x)]


def get_image(soup):
    img = soup.select_one(
        'img[src*="/card/"], '
        'img[src*="/wp-content/"], '
        '.card-detail img'
    )

    if not img:
        return ""

    src = img.get("src", "")

    if src.startswith("//"):
        src = "https:" + src
    elif src.startswith("/"):
        src = urljoin(LIST_URL, src)

    return src


def get_value(lines, label):
    if label not in lines:
        return ""

    i = lines.index(label)

    if i + 1 < len(lines):
        return lines[i + 1]

    return ""


def get_abilities(lines):
    abilities = []

    if "能力" not in lines:
        return abilities

    start = lines.index("能力") + 1

    end_labels = {
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

    for line in lines[start:]:
        if line in end_labels:
            break

        if line:
            abilities.append(line)

    return abilities


def get_flavor(lines):
    if "フレーバー" not in lines:
        return ""

    i = lines.index("フレーバー")

    result = []

    for line in lines[i + 1:]:
        if line in {
            "カードの種類",
            "文明",
            "レアリティ",
            "パワー",
            "コスト",
            "マナ",
            "種族",
            "イラストレーター",
            "能力",
        }:
            break

        result.append(line)

    return " ".join(result)


# =========================
# ツインパクトの面分割
# =========================

def split_sides(text):
    """
    カードの種類が出るたびに面を分割。
    ツインパクトなら2面になる。
    """

    lines = get_lines(text)

    positions = []

    for i, line in enumerate(lines):
        if line == "カードの種類":
            positions.append(i)

    if not positions:
        return [lines]

    sides = []

    for index, start in enumerate(positions):
        if index + 1 < len(positions):
            end = positions[index + 1]
        else:
            end = len(lines)

        side = lines[start:end]

        if side:
            sides.append(side)

    return sides


# =========================
# 1面を解析
# =========================

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


# =========================
# カード1枚解析
# =========================

def parse_card(html, url):
    soup = BeautifulSoup(html, "html.parser")

    # ページ全体のテキスト
    text = soup.get_text("\n")

    lines = get_lines(text)

    # カードID
    m = re.search(r"[?&]id=([^&]+)", url)

    if not m:
        return None

    card_id = m.group(1)

    # カード名
    name = ""

    # よくあるカード名候補
    selectors = [
        "h1",
        "h2",
        ".card-name",
        ".card-detail-name",
        ".cardDetail-name",
    ]

    for selector in selectors:
        el = soup.select_one(selector)

        if el:
            candidate = clean(el.get_text(" ", strip=True))

            if candidate and len(candidate) < 200:
                name = candidate
                break

    # hタグから取れなかった場合
    if not name:
        for line in lines[:50]:
            if (
                line
                and line not in LABELS
                and len(line) <= 100
                and not re.match(r"^(カード検索|デュエル・マスターズ)", line)
            ):
                name = line
                break

    # 面を分割
    side_blocks = split_sides(text)

    sides = []

    for block in side_blocks:
        side = parse_side(block)

        # 面として最低限カード種類があるものだけ
        if side["type"]:
            sides.append(side)

    if not sides:
        return None

    # ツインパクト判定
    is_twin = len(sides) >= 2

    card_type = "ツインパクト" if is_twin else sides[0]["type"]

    card = {
        "id": card_id,
        "name": name,
        "type": card_type,
        "image": get_image(soup),
        "url": url,
        "sides": sides,
    }

    return card


# =========================
# 既存JSON読み込み
# =========================

def load_existing():
    if not OUT.exists():
        return {}

    try:
        with open(OUT, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            return {}

        result = {}

        for card in data:
            if isinstance(card, dict) and card.get("id"):
                result[card["id"]] = card

        return result

    except Exception as e:
        print(f"既存JSON読み込み失敗: {e}")
        return {}


# =========================
# JSON保存
# =========================

def save_cards(cards):
    OUT.parent.mkdir(parents=True, exist_ok=True)

    data = list(cards.values())

    data.sort(
        key=lambda x: (
            x.get("id", ""),
            x.get("name", ""),
        )
    )

    tmp = OUT.with_suffix(".tmp")

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    tmp.replace(OUT)

    print(f"JSON保存: {len(data)}枚")


# =========================
# GitHubチェックポイント
# =========================

def checkpoint_git():
    try:
        subprocess.run(
            ["git", "config", "user.name", "github-actions[bot]"],
            check=False,
        )

        subprocess.run(
            [
                "git",
                "config",
                "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com",
            ],
            check=False,
        )

        subprocess.run(
            ["git", "add", "data/cards.json"],
            check=False,
        )

        result = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--quiet",
            ],
            check=False,
        )

        # 変更なし
        if result.returncode == 0:
            print("GitHub保存: 変更なし")
            return

        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "自動更新: 公式カードデータ",
            ],
            check=False,
        )

        push = subprocess.run(
            ["git", "push", "origin", "main"],
            check=False,
        )

        if push.returncode == 0:
            print("GitHub保存: 成功")
        else:
            print("GitHub保存: push失敗")

    except Exception as e:
        print(f"GitHub保存エラー: {e}")


# =========================
# 公式カードURL全取得
# =========================

async def collect_all_urls(browser):
    print()
    print("=" * 32)
    print("★ 公式カードURL全件取得 ★")
    print("=" * 32)

    page = await browser.new_page()

    # タイムアウトを長めに
    page.set_default_timeout(30000)

    await page.goto(
        LIST_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    await page.wait_for_timeout(3000)

    urls = []
    seen = set()

    page_number = 1

    while True:

        # --------------------------------
        # ポップアップを強制的に無効化
        # --------------------------------

        try:
            await page.evaluate("""
                () => {
                    const modal = document.querySelector('#first-modal-wrap');

                    if (modal) {
                        modal.style.display = 'none';
                        modal.style.pointerEvents = 'none';
                    }

                    document.body.style.overflow = 'auto';
                }
            """)
        except Exception:
            pass

        # --------------------------------
        # 現在ページのカードURL取得
        # --------------------------------

        current_urls = await page.locator(
            'a[href*="/card/detail/?id="]'
        ).evaluate_all(
            """
            els => els
                .map(e => e.href)
                .filter(Boolean)
            """
        )

        added = 0

        for url in current_urls:
            if url not in seen:
                seen.add(url)
                urls.append(url)
                added += 1

        print(
            f"一覧ページ {page_number}: "
            f"+{added} URL / 累計 {len(urls)}"
        )

        # --------------------------------
        # 次ページ番号
        # --------------------------------

        next_number = page_number + 1

        selector = f'a[data-page="{next_number}"]'

        next_link = page.locator(selector).first

        count = await next_link.count()

        if count == 0:
            print("次ページリンクなし → 一覧取得終了")
            break

        # 現在ページのカードを記録
        old_signature = "|".join(
            current_urls[:5]
        )

        # --------------------------------
        # ★ 重要
        # 普通のclick()を使わない
        # JavaScriptで直接クリック
        # --------------------------------

        try:

            await page.evaluate(
                """
                (selector) => {
                    const el = document.querySelector(selector);

                    if (el) {
                        el.click();
                    }
                }
                """,
                selector,
            )

            # ページ更新待ち
            await page.wait_for_timeout(1500)

            # カード一覧が変わるまで待つ
            for _ in range(20):

                await page.wait_for_timeout(500)

                new_urls = await page.locator(
                    'a[href*="/card/detail/?id="]'
                ).evaluate_all(
                    """
                    els => els
                        .map(e => e.href)
                        .filter(Boolean)
                    """
                )

                new_signature = "|".join(
                    new_urls[:5]
                )

                if (
                    new_signature
                    and new_signature != old_signature
                ):
                    break

            page_number += 1

        except Exception as e:
            print(
                f"ページ移動失敗: {type(e).__name__}: {e}"
            )

            # 1回だけ再試行
            try:
                await page.evaluate(
                    """
                    (selector) => {
                        const el = document.querySelector(selector);

                        if (el) {
                            el.dispatchEvent(
                                new MouseEvent(
                                    'click',
                                    {
                                        bubbles: true,
                                        cancelable: true,
                                        view: window
                                    }
                                )
                            );
                        }
                    }
                    """,
                    selector,
                )

                await page.wait_for_timeout(2000)

                page_number += 1

            except Exception as e2:
                print(
                    f"再試行も失敗: {type(e2).__name__}: {e2}"
                )
                break

    await page.close()

    print()
    print("=" * 32)
    print(f"公式URL総数: {len(urls)}")
    print("=" * 32)

    return urls


# =========================
# カード詳細1枚取得
# =========================

async def fetch_card(context, url, semaphore):

    async with semaphore:

        for attempt in range(1, RETRIES + 1):

            page = await context.new_page()

            try:

                page.set_default_timeout(20000)

                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

                await page.wait_for_timeout(500)

                # 詳細ページの邪魔なポップアップを消す
                try:
                    await page.evaluate("""
                        () => {
                            const modal =
                                document.querySelector('#first-modal-wrap');

                            if (modal) {
                                modal.style.display = 'none';
                                modal.style.pointerEvents = 'none';
                            }

                            document.body.style.overflow = 'auto';
                        }
                    """)
                except Exception:
                    pass

                html = await page.content()

                card = parse_card(
                    html,
                    url,
                )

                await page.close()

                if card:
                    return card

                print(
                    f"解析失敗: {url} "
                    f"(試行 {attempt}/{RETRIES})"
                )

            except Exception as e:

                try:
                    await page.close()
                except Exception:
                    pass

                print(
                    f"取得失敗: {url} "
                    f"(試行 {attempt}/{RETRIES}) "
                    f"{type(e).__name__}: {e}"
                )

                await asyncio.sleep(1)

    return None


# =========================
# メイン
# =========================

async def main():

    print()
    print("=" * 32)
    print("★ デュエマ公式カード全件更新 ★")
    print("再開対応 / ツインパクト対応")
    print("=" * 32)

    cards = load_existing()

    print(
        f"既存データ: {len(cards)}枚"
    )

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        # --------------------------------
        # URLを全部取得
        # --------------------------------

        urls = await collect_all_urls(
            browser
        )

        # --------------------------------
        # IDで既存チェック
        # --------------------------------

        remaining = []

        for url in urls:

            m = re.search(
                r"[?&]id=([^&]+)",
                url
            )

            if not m:
                continue

            card_id = m.group(1)

            if card_id not in cards:
                remaining.append(
                    (card_id, url)
                )

        print()
        print("=" * 32)
        print(f"公式URL: {len(urls)}枚")
        print(f"取得済み: {len(cards)}枚")
        print(f"残り: {len(remaining)}枚")
        print("=" * 32)

        # --------------------------------
        # 全部取得済み
        # --------------------------------

        if not remaining:

            save_cards(cards)

            print()
            print("★ 全カード取得済み ★")

            await browser.close()
            return

        # --------------------------------
        # 詳細取得
        # --------------------------------

        context = await browser.new_context()

        semaphore = asyncio.Semaphore(
            CONCURRENCY
        )

        success = 0
        failed = 0

        for start in range(
            0,
            len(remaining),
            CHECKPOINT
        ):

            batch = remaining[
                start:
                start + CHECKPOINT
            ]

            print()
            print("=" * 32)
            print(
                f"詳細取得 "
                f"{start + 1} ～ "
                f"{start + len(batch)} / "
                f"{len(remaining)}"
            )
            print("=" * 32)

            tasks = []

            for card_id, url in batch:

                tasks.append(
                    fetch_card(
                        context,
                        url,
                        semaphore,
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

                    success += 1

                    if card["type"] == "ツインパクト":
                        print(
                            f"ツインパクト取得: "
                            f"{card['name']}"
                        )

                else:
                    failed += 1

            # --------------------------------
            # 250枚ごとに保存
            # --------------------------------

            save_cards(cards)

            print(
                f"今回成功: {success}枚"
            )

            print(
                f"今回失敗: {failed}枚"
            )

            print(
                f"現在JSON: {len(cards)}枚"
            )

            checkpoint_git()

        await context.close()
        await browser.close()

    # --------------------------------
    # 最終保存
    # --------------------------------

    save_cards(cards)

    checkpoint_git()

    twin_count = sum(
        1
        for card in cards.values()
        if card.get("type") == "ツインパクト"
    )

    print()
    print("=" * 32)
    print("★ 全件処理終了 ★")
    print(f"総カード数: {len(cards)}枚")
    print(f"ツインパクト: {twin_count}枚")
    print(f"保存先: {OUT}")
    print("=" * 32)


if __name__ == "__main__":
    asyncio.run(main())
