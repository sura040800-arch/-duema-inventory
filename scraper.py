import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, parse_qs, unquote

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


BASE = "https://dm.takaratomy.co.jp"
SEARCH = BASE + "/card/"

OUT = Path("data/cards.json")
IDS_OUT = Path("data/card_ids.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DuemaInventoryUpdater/2.0)"
}


# =========================================================
# 公式検索URL
# =========================================================

def search_url(page_number=1):
    state = {
        "suggest": "on",
        "keyword": "",
        "keyword_type": [
            "card_name",
            "card_ruby",
            "card_text",
            "race",
            "flavor",
            "illustrator"
        ],
        "culture_cond": [
            "単色",
            "多色"
        ],
        "pagenum": str(page_number),
        "samename": "show",
        "sort": "release_new"
    }

    return (
        SEARCH
        + "?v="
        + quote(
            json.dumps(
                state,
                ensure_ascii=False,
                separators=(",", ":")
            )
        )
    )


# =========================================================
# カードURL取得
# =========================================================

def extract_links(page):
    hrefs = page.locator(
        'a[href*="/card/detail/"]'
    ).evaluate_all(
        "els => els.map(a => a.href).filter(Boolean)"
    )

    result = []
    seen = set()

    for href in hrefs:
        m = re.search(
            r"[?&]id=([^&#]+)",
            href
        )

        if not m:
            continue

        cid = m.group(1).lower()

        url = (
            BASE
            + "/card/detail/?id="
            + cid
        )

        if url not in seen:
            seen.add(url)
            result.append(url)

    return result


# =========================================================
# 現在のページ番号
# =========================================================

def current_page_number(page):
    try:
        if "?" not in page.url:
            return None

        query = page.url.split(
            "?",
            1
        )[1]

        qs = parse_qs(query)

        raw = qs.get(
            "v",
            [""]
        )[0]

        if not raw:
            return None

        obj = json.loads(
            unquote(raw)
        )

        return int(
            obj.get(
                "pagenum",
                1
            )
        )

    except Exception:
        return None


# =========================================================
# 最終ページ番号
# =========================================================

def get_last_page(page):
    pages = page.locator(
        "a[data-page]"
    ).evaluate_all(
        """
        els =>
            els
                .map(a => Number(a.getAttribute("data-page")))
                .filter(Number.isFinite)
        """
    )

    if pages:
        return max(pages)

    body = page.locator(
        "body"
    ).inner_text()

    # 例:
    # 23,478件
    # 1 / 470
    m = re.search(
        r"/\s*(\d+)",
        body
    )

    if m:
        return int(m.group(1))

    return 1


# =========================================================
# 次ページへ移動
# =========================================================

def go_next_page(page, current):
    target = current + 1

    for attempt in range(1, 6):

        try:
            old_links = extract_links(page)

            old_signature = "|".join(
                old_links[:10]
            )

            count = page.locator(
                f'a[data-page="{target}"]'
            ).count()

            if count == 0:
                raise RuntimeError(
                    f"次ページ {target} が見つかりません"
                )

            print(
                f"page {current} -> {target}: "
                f"attempt {attempt}/5",
                flush=True
            )

            # クリック
            page.evaluate(
                """
                target => {
                    const el =
                        document.querySelector(
                            `a[data-page="${target}"]`
                        );

                    if (!el) {
                        throw new Error(
                            "pagination button not found"
                        );
                    }

                    el.click();
                }
                """,
                target
            )

            # ★重要
            # wait_for_functionのtimeoutを
            # キーワード引数にしている
            try:
                page.wait_for_function(
                    """
                    oldSignature => {
                        const links =
                            Array.from(
                                document.querySelectorAll(
                                    'a[href*="/card/detail/"]'
                                )
                            )
                            .map(a => a.href)
                            .filter(Boolean)
                            .slice(0, 10)
                            .join("|");

                        return links &&
                               links !== oldSignature;
                    }
                    """,
                    old_signature,
                    timeout=20000
                )

            except Exception:
                pass

            # 念のため少し待つ
            page.wait_for_timeout(1500)

            actual = current_page_number(
                page
            )

            new_links = extract_links(
                page
            )

            new_signature = "|".join(
                new_links[:10]
            )

            print(
                f"page check: "
                f"actual={actual}, "
                f"cards={len(new_links)}",
                flush=True
            )

            if (
                actual == target
                and new_links
                and new_signature != old_signature
            ):
                return new_links

            time.sleep(2)

        except Exception as e:

            print(
                f"page {current} -> {target}: "
                f"attempt {attempt}/5 "
                f"error={e}",
                flush=True
            )

            time.sleep(2)

    return None


# =========================================================
# 全カードURL取得
# =========================================================

def discover_all_links():

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

        print(
            "公式カード検索ページを開いています...",
            flush=True
        )

        page.goto(
            search_url(1),
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(3000)

        # -------------------------------------------------
        # 公式表示枚数
        # -------------------------------------------------

        body = page.locator(
            "body"
        ).inner_text()

        reported_total = 0

        patterns = [
            r"([0-9][0-9,]*)\s*枚",
            r"([0-9][0-9,]*)\s*件"
        ]

        for pattern in patterns:

            m = re.search(
                pattern,
                body
            )

            if m:
                reported_total = int(
                    m.group(1).replace(
                        ",",
                        ""
                    )
                )
                break

        print(
            f"公式カード総数表示: "
            f"{reported_total}",
            flush=True
        )

        # -------------------------------------------------
        # 最終ページ
        # -------------------------------------------------

        last_page = get_last_page(
            page
        )

        print(
            f"公式最終ページ: "
            f"{last_page}",
            flush=True
        )

        # -------------------------------------------------
        # 1ページ目
        # -------------------------------------------------

        links_by_id = {}

        current = (
            current_page_number(page)
            or 1
        )

        links = extract_links(
            page
        )

        for url in links:

            cid = url.split(
                "id=",
                1
            )[1].lower()

            links_by_id[cid] = url

        print(
            f"page {current}/{last_page}: "
            f"+{len(links)} links, "
            f"unique={len(links_by_id)}",
            flush=True
        )

        # -------------------------------------------------
        # 2ページ目以降
        # -------------------------------------------------

        while current < last_page:

            new_links = go_next_page(
                page,
                current
            )

            if not new_links:

                raise RuntimeError(
                    f"{current + 1}ページ目への"
                    f"公式ページ移動に失敗。"
                    f"取得済み{len(links_by_id)}枚。"
                )

            actual = current_page_number(
                page
            )

            if actual != current + 1:

                raise RuntimeError(
                    "ページ番号確認失敗: "
                    f"期待={current + 1}, "
                    f"実際={actual}"
                )

            current = actual

            for url in new_links:

                cid = url.split(
                    "id=",
                    1
                )[1].lower()

                links_by_id[cid] = url

            print(
                f"page {current}/{last_page}: "
                f"+{len(new_links)} links, "
                f"unique={len(links_by_id)}",
                flush=True
            )

        browser.close()

    links = list(
        links_by_id.values()
    )

    print(
        f"ページ取得完了: "
        f"{last_page}ページ / "
        f"unique {len(links)} cards",
        flush=True
    )

    return (
        links,
        reported_total,
        last_page
    )


# =========================================================
# HTMLテキスト処理
# =========================================================

def all_text_lines(soup):

    text = soup.get_text(
        "\n",
        strip=True
    )

    result = []

    for line in text.splitlines():

        line = line.strip()

        if line:
            result.append(line)

    return result


def text_after(lines, label):

    for i, line in enumerate(lines):

        if line == label:

            if i + 1 < len(lines):
                return lines[i + 1]

    return ""


def section_between(
    lines,
    start_label,
    end_labels
):

    start = None

    for i, line in enumerate(lines):

        if line == start_label:

            start = i + 1
            break

    if start is None:
        return ""

    result = []

    for line in lines[start:]:

        if line in end_labels:
            break

        result.append(line)

    return "\n".join(
        result
    ).strip()


def clean_text(text):

    if not text:
        return ""

    result = []

    for line in text.splitlines():

        line = line.strip()

        if not line:
            continue

        if line in {
            "特殊能力",
            "フレーバー"
        }:
            continue

        result.append(line)

    return "\n".join(
        result
    )


# =========================================================
# 詳細ページ解析
# =========================================================

def parse_detail_html(
    html,
    url
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    lines = all_text_lines(
        soup
    )

    # -----------------------------------------------------
    # 名前
    # -----------------------------------------------------

    name = ""

    for tag in soup.find_all(
        ["h1", "h2", "h3"]
    ):

        text = tag.get_text(
            " ",
            strip=True
        )

        if text:

            name = text

            if "カード" not in text:
                break

    # -----------------------------------------------------
    # カード番号
    # -----------------------------------------------------

    number = ""

    m = re.search(
        r"\(([^()]*)\)",
        name
    )

    if m:
        number = m.group(1).strip()

    name = re.sub(
        r"\s*\([^()]*\)\s*$",
        "",
        name
    ).strip()

    # -----------------------------------------------------
    # 基本情報
    # -----------------------------------------------------

    card_type = text_after(
        lines,
        "カードの種類"
    )

    civilization = text_after(
        lines,
        "文明"
    )

    rarity = text_after(
        lines,
        "レアリティ"
    )

    power = text_after(
        lines,
        "パワー"
    )

    cost = text_after(
        lines,
        "コスト"
    )

    mana = text_after(
        lines,
        "マナ"
    )

    race = text_after(
        lines,
        "種族"
    )

    illustrator = text_after(
        lines,
        "イラストレーター"
    )

    # -----------------------------------------------------
    # 特殊能力
    # -----------------------------------------------------

    ability = section_between(
        lines,
        "特殊能力",
        [
            "フレーバー",
            "商品情報",
            "このカードのよくある質問",
            "関連カード"
        ]
    )

    ability = clean_text(
        ability
    )

    # -----------------------------------------------------
    # フレーバー
    # -----------------------------------------------------

    flavor = section_between(
        lines,
        "フレーバー",
        [
            "商品情報",
            "このカードのよくある質問",
            "関連カード"
        ]
    )

    flavor = clean_text(
        flavor
    )

    # -----------------------------------------------------
    # 画像
    # -----------------------------------------------------

    image = ""

    for img in soup.find_all(
        "img"
    ):

        src = (
            img.get("src")
            or img.get("data-src")
            or ""
        )

        if "cardimage" in src:

            image = src
            break

    if image.startswith("//"):
        image = "https:" + image

    elif image.startswith("/"):
        image = BASE + image

    # -----------------------------------------------------
    # ID
    # -----------------------------------------------------

    if "id=" in url:

        cid = url.split(
            "id=",
            1
        )[1].lower()

    else:

        cid = ""

    return {
        "id": cid,
        "name": name,
        "number": number,

        "card_type": card_type,
        "type": card_type,

        "civilization": civilization,
        "rarity": rarity,
        "power": power,
        "cost": cost,
        "mana": mana,
        "race": race,
        "illustrator": illustrator,

        "text": ability,
        "special_ability": ability,

        "flavor": flavor,

        "image": image,
        "url": url
    }


# =========================================================
# 詳細ページ1枚取得
# =========================================================

def fetch_detail(
    url
):

    session = requests.Session()

    for attempt in range(1, 4):

        try:

            response = session.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            response.raise_for_status()

            card = parse_detail_html(
                response.text,
                url
            )

            if (
                card.get("id")
                and card.get("name")
            ):
                return card, None

            return None, "カード名を取得できませんでした"

        except Exception as e:

            if attempt >= 3:

                return None, str(e)

            time.sleep(
                attempt
            )

    return None, "unknown error"


# =========================================================
# 全詳細取得
# =========================================================

def fetch_details(
    links
):

    total = len(links)

    print(
        f"詳細ページ取得開始: "
        f"{total}件",
        flush=True
    )

    # 公式一覧に出てきた順番
    release_order = {}

    for index, url in enumerate(
        links
    ):

        cid = url.split(
            "id=",
            1
        )[1].lower()

        release_order[cid] = index

    cards = []
    failures = []

    workers = 8

    def task(url):
        return fetch_detail(
            url
        )

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = {
            executor.submit(
                task,
                url
            ): url
            for url in links
        }

        done = 0

        for future in as_completed(
            futures
        ):

            url = futures[
                future
            ]

            done += 1

            try:

                card, error = (
                    future.result()
                )

            except Exception as e:

                card = None
                error = str(e)

            if card:

                cid = card["id"]

                # ★最新順
                card["release_order"] = release_order.get(
                    cid,
                    999999999
                )

                cards.append(
                    card
                )

            else:

                failures.append(
                    (
                        url,
                        error or "unknown"
                    )
                )

            if (
                done % 100 == 0
                or done == total
            ):

                print(
                    f"details "
                    f"{done}/{total} "
                    f"success={len(cards)} "
                    f"fail={len(failures)}",
                    flush=True
                )

    # -----------------------------------------------------
    # 失敗が多すぎる場合は保存しない
    # -----------------------------------------------------

    if failures:

        failure_rate = (
            len(failures)
            / max(total, 1)
        )

        if (
            len(failures) > 20
            and failure_rate > 0.01
        ):

            raise RuntimeError(
                "詳細ページの失敗が多すぎます: "
                f"{len(failures)}/{total}"
            )

    # -----------------------------------------------------
    # ID重複排除
    # -----------------------------------------------------

    unique = {}

    for card in cards:

        cid = card.get(
            "id"
        )

        if cid:
            unique[cid] = card

    # -----------------------------------------------------
    # 公式検索順
    # 最新 → 過去
    # -----------------------------------------------------

    result = sorted(
        unique.values(),
        key=lambda card:
            card.get(
                "release_order",
                999999999
            )
    )

    return result, failures


# =========================================================
# メイン
# =========================================================

def main():

    print(
        "========================================",
        flush=True
    )

    print(
        "デュエマ公式カード自動更新",
        flush=True
    )

    print(
        "========================================",
        flush=True
    )

    # -----------------------------------------------------
    # 全カードURL取得
    # -----------------------------------------------------

    (
        links,
        reported_total,
        last_page
    ) = discover_all_links()

    # -----------------------------------------------------
    # 公式表示数との確認
    # -----------------------------------------------------

    if reported_total:

        minimum = int(
            reported_total * 0.98
        )

        if len(links) < minimum:

            raise RuntimeError(
                "一覧取得数が公式表示より"
                "少なすぎます: "
                f"{len(links)}/"
                f"{reported_total}"
            )

    # -----------------------------------------------------
    # ID一覧保存
    # -----------------------------------------------------

    IDS_OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    ids = []

    for url in links:

        cid = url.split(
            "id=",
            1
        )[1].lower()

        ids.append(
            cid
        )

    IDS_OUT.write_text(
        json.dumps(
            ids,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        f"card_ids.json 保存: "
        f"{len(ids)}件",
        flush=True
    )

    # -----------------------------------------------------
    # 詳細取得
    # -----------------------------------------------------

    cards, failures = fetch_details(
        links
    )

    print(
        f"最終ユニークカード数: "
        f"{len(cards)}",
        flush=True
    )

    # -----------------------------------------------------
    # 最終チェック
    # -----------------------------------------------------

    if reported_total:

        minimum = int(
            reported_total * 0.98
        )

        if len(cards) < minimum:

            raise RuntimeError(
                "最終カード数が公式表示より"
                "少なすぎます: "
                f"{len(cards)}/"
                f"{reported_total}"
            )

    # -----------------------------------------------------
    # cards.json保存
    # -----------------------------------------------------

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    OUT.write_text(
        json.dumps(
            cards,
            ensure_ascii=False,
            separators=(",", ":")
        ),
        encoding="utf-8"
    )

    print(
        f"cards.json 保存完了: "
        f"{len(cards)}件",
        flush=True
    )

    # -----------------------------------------------------
    # 失敗表示
    # -----------------------------------------------------

    if failures:

        print(
            f"詳細取得失敗: "
            f"{len(failures)}件",
            flush=True
        )

        for url, error in failures[:20]:

            print(
                "FAIL:",
                url,
                error,
                flush=True
            )

    else:

        print(
            "詳細取得失敗: 0件",
            flush=True
        )

    print(
        "========================================",
        flush=True
    )

    print(
        "更新完了",
        flush=True
    )

    print(
        "========================================",
        flush=True
    )


if __name__ == "__main__":
    main()
