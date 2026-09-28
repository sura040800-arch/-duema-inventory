import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


BASE = "https://dm.takaratomy.co.jp"
SEARCH = BASE + "/card/"

OUT = Path("data/cards.json")
IDS_OUT = Path("data/card_ids.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


# =========================================================
# 検索URL
# =========================================================

def search_url():
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
        "pagenum": "1",
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
# カードリンク
# =========================================================

def extract_links(page):

    hrefs = page.locator(
        'a[href*="/card/detail/"]'
    ).evaluate_all(
        """
        els => els.map(a => a.href).filter(Boolean)
        """
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


def get_ids(page):

    result = []

    for url in extract_links(page):

        m = re.search(
            r"[?&]id=([^&#]+)",
            url
        )

        if m:
            result.append(
                m.group(1).lower()
            )

    return result


# =========================================================
# 最終ページ
# =========================================================

def get_last_page(page):

    nums = page.locator(
        "[data-page]"
    ).evaluate_all(
        """
        els =>
            els
                .map(e => Number(e.getAttribute("data-page")))
                .filter(n => Number.isFinite(n))
        """
    )

    if nums:
        return max(nums)

    body = page.locator(
        "body"
    ).inner_text()

    m = re.search(
        r"最後のページ",
        body
    )

    if m:
        # 現在の公式サイトは470ページ。
        # ページャーが取得できない場合だけ470を使う。
        return 470

    return 1


# =========================================================
# ページボタンの詳細確認
# =========================================================

def find_page_control(page, target):

    locator = page.locator(
        f'[data-page="{target}"]'
    )

    count = locator.count()

    if count == 0:
        return None

    # 表示されている要素を優先
    for i in range(count):

        item = locator.nth(i)

        try:

            if not item.is_visible():
                continue

            return item

        except Exception:
            pass

    return None


# =========================================================
# ページ移動
# =========================================================

def go_next_page(
    page,
    current
):

    target = current + 1

    old_ids = set(
        get_ids(page)
    )

    print(
        f"page {current} -> {target}",
        flush=True
    )

    control = find_page_control(
        page,
        target
    )

    if control is None:

        raise RuntimeError(
            f"{target}ページ目の"
            "ページコントロールが見つかりません"
        )

    # デバッグ情報
    try:

        html = control.evaluate(
            "el => el.outerHTML"
        )

        print(
            f"page control: {html[:1000]}",
            flush=True
        )

    except Exception:
        pass

    # -----------------------------------------------------
    # クリック
    # -----------------------------------------------------

    for attempt in range(1, 6):

        try:

            control = find_page_control(
                page,
                target
            )

            if control is None:
                break

            control.scroll_into_view_if_needed()

            # 普通のPlaywrightクリック
            control.click(
                force=True,
                timeout=10000
            )

            # カード内容が変わるまで待つ
            for _ in range(30):

                time.sleep(0.5)

                new_ids = set(
                    get_ids(page)
                )

                if (
                    new_ids
                    and
                    new_ids != old_ids
                ):

                    print(
                        f"page check: "
                        f"cards={len(new_ids)}, "
                        f"new_cards={len(new_ids - old_ids)}",
                        flush=True
                    )

                    return extract_links(
                        page
                    )

            # -------------------------------------------------
            # クリックイベントを直接発火
            # -------------------------------------------------

            print(
                f"通常クリックで変化なし "
                f"attempt {attempt}/5",
                flush=True
            )

            control = find_page_control(
                page,
                target
            )

            if control:

                control.dispatch_event(
                    "click"
                )

                for _ in range(20):

                    time.sleep(0.5)

                    new_ids = set(
                        get_ids(page)
                    )

                    if (
                        new_ids
                        and
                        new_ids != old_ids
                    ):

                        print(
                            f"page check: "
                            f"cards={len(new_ids)}, "
                            f"new_cards={len(new_ids - old_ids)}",
                            flush=True
                        )

                        return extract_links(
                            page
                        )

        except Exception as e:

            print(
                f"click attempt {attempt}/5 "
                f"error={e}",
                flush=True
            )

        time.sleep(1)

    # -----------------------------------------------------
    # ここまで来たらHTMLを出す
    # -----------------------------------------------------

    control = find_page_control(
        page,
        target
    )

    if control:

        try:

            html = control.evaluate(
                "el => el.parentElement.outerHTML"
            )

            print(
                "PAGE CONTROL HTML:",
                html[:3000],
                flush=True
            )

        except Exception:
            pass

    raise RuntimeError(
        f"{target}ページ目への移動に失敗。"
        f"現在取得={len(old_ids)}枚"
    )


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
                "height": 1000
            }
        )

        print(
            "公式カード検索を開いています...",
            flush=True
        )

        page.goto(
            search_url(),
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(
            5000
        )

        # -----------------------------------------------------
        # 総数
        # -----------------------------------------------------

        body = page.locator(
            "body"
        ).inner_text()

        m = re.search(
            r"([0-9][0-9,]*)枚",
            body
        )

        reported_total = (
            int(
                m.group(1).replace(",", "")
            )
            if m
            else 0
        )

        print(
            f"公式カード総数: "
            f"{reported_total}",
            flush=True
        )

        # -----------------------------------------------------
        # 最終ページ
        # -----------------------------------------------------

        last_page = get_last_page(
            page
        )

        print(
            f"公式最終ページ: "
            f"{last_page}",
            flush=True
        )

        # -----------------------------------------------------
        # 1ページ目
        # -----------------------------------------------------

        links_by_id = {}

        links = extract_links(
            page
        )

        for url in links:

            m = re.search(
                r"[?&]id=([^&#]+)",
                url
            )

            if m:

                links_by_id[
                    m.group(1).lower()
                ] = url

        print(
            f"page 1/{last_page}: "
            f"+{len(links)} links, "
            f"unique={len(links_by_id)}",
            flush=True
        )

        # -----------------------------------------------------
        # 2ページ目以降
        # -----------------------------------------------------

        current = 1

        while current < last_page:

            new_links = go_next_page(
                page,
                current
            )

            current += 1

            for url in new_links:

                m = re.search(
                    r"[?&]id=([^&#]+)",
                    url
                )

                if m:

                    links_by_id[
                        m.group(1).lower()
                    ] = url

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
        "========================================",
        flush=True
    )

    print(
        f"ページ取得完了: "
        f"{len(links)} cards",
        flush=True
    )

    print(
        "========================================",
        flush=True
    )

    return (
        links,
        reported_total,
        last_page
    )


# =========================================================
# HTMLテキスト
# =========================================================

def all_text_lines(soup):

    text = soup.get_text(
        "\n",
        strip=True
    )

    return [
        x.strip()
        for x in text.splitlines()
        if x.strip()
    ]


def text_after(
    lines,
    label
):

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

            if "カード検索" not in text:
                break

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

    flavor = section_between(
        lines,
        "フレーバー",
        [
            "商品情報",
            "このカードのよくある質問",
            "関連カード"
        ]
    )

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

    m = re.search(
        r"[?&]id=([^&#]+)",
        url
    )

    cid = (
        m.group(1).lower()
        if m
        else ""
    )

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
# 詳細取得
# =========================================================

def fetch_detail(url):

    for attempt in range(1, 4):

        try:

            r = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            r.raise_for_status()

            card = parse_detail_html(
                r.text,
                url
            )

            if (
                card["id"]
                and card["name"]
            ):

                return card, None

            return (
                None,
                "カード名取得失敗"
            )

        except Exception as e:

            if attempt == 3:

                return (
                    None,
                    str(e)
                )

            time.sleep(
                attempt
            )

    return (
        None,
        "unknown"
    )


# =========================================================
# 詳細全取得
# =========================================================

def fetch_details(
    links
):

    total = len(links)

    print(
        f"詳細取得開始: {total}件",
        flush=True
    )

    release_order = {}

    for i, url in enumerate(
        links
    ):

        m = re.search(
            r"[?&]id=([^&#]+)",
            url
        )

        if m:

            release_order[
                m.group(1).lower()
            ] = i

    cards = []
    failures = []

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = {
            executor.submit(
                fetch_detail,
                url
            ): url
            for url in links
        }

        done = 0

        for future in as_completed(
            futures
        ):

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

                card[
                    "release_order"
                ] = release_order.get(
                    cid,
                    999999999
                )

                cards.append(
                    card
                )

            else:

                failures.append(
                    (
                        futures[future],
                        error
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

    unique = {}

    for card in cards:

        if card.get("id"):

            unique[
                card["id"]
            ] = card

    result = sorted(
        unique.values(),
        key=lambda x:
            x.get(
                "release_order",
                999999999
            )
    )

    return result, failures


# =========================================================
# MAIN
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

    links, reported_total, last_page = (
        discover_all_links()
    )

    # 取得数チェック
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

    # ID保存
    IDS_OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    ids = []

    for url in links:

        m = re.search(
            r"[?&]id=([^&#]+)",
            url
        )

        if m:

            ids.append(
                m.group(1).lower()
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
        f"card_ids.json: {len(ids)}件",
        flush=True
    )

    # 詳細
    cards, failures = fetch_details(
        links
    )

    print(
        f"最終カード数: {len(cards)}",
        flush=True
    )

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

    # 保存
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

    print(
        f"詳細取得失敗: "
        f"{len(failures)}件",
        flush=True
    )

    if failures:

        for url, error in failures[:20]:

            print(
                "FAIL:",
                url,
                error,
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
