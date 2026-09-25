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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DuemaInventoryUpdater/1.0)"
}


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
            "illustrator",
        ],
        "culture_cond": ["単色", "多色"],
        "pagenum": str(page_number),
        "samename": "show",
        "sort": "release_new",
    }

    return SEARCH + "?v=" + quote(
        json.dumps(
            state,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


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
        m = re.search(r"[?&]id=([^&#]+)", href)

        if not m:
            continue

        card_id = m.group(1)

        url = (
            BASE
            + "/card/detail/?id="
            + card_id
        )

        if url not in seen:
            seen.add(url)
            result.append(url)

    return result


def get_page_buttons(page):
    return page.locator(
        "a[data-page]"
    ).evaluate_all(
        """
        els => els.map(a => ({
            page: Number(a.getAttribute("data-page")),
            text: a.innerText
        })).filter(x => Number.isFinite(x.page))
        """
    )


def get_current_page_from_url(page):
    try:
        if "?" not in page.url:
            return None

        query = parse_qs(
            page.url.split("?", 1)[1]
        )

        raw = query.get("v", [""])[0]

        if not raw:
            return None

        data = json.loads(
            unquote(raw)
        )

        return int(
            data.get("pagenum", 1)
        )

    except Exception:
        return None


def click_next_page(page, current_page, last_page):
    old_links = extract_links(page)

    if not old_links:
        raise RuntimeError(
            "現在ページのカードが取得できません。"
        )

    old_signature = "|".join(
        old_links[:10]
    )

    buttons = get_page_buttons(page)

    print(
        f"現在 {current_page}ページ目 / "
        f"最終 {last_page}ページ目",
        flush=True,
    )

    print(
        "表示中ページ:",
        [x["page"] for x in buttons],
        flush=True,
    )

    candidates = sorted(
        {
            x["page"]
            for x in buttons
            if current_page < x["page"] <= last_page
        }
    )

    if not candidates:
        raise RuntimeError(
            f"次のページボタンがありません。"
            f"現在={current_page}, "
            f"表示={buttons}"
        )

    target = candidates[0]

    selector = (
        f'a[data-page="{target}"]'
    )

    if page.locator(selector).count() == 0:
        raise RuntimeError(
            f"ページ{target}のボタンが見つかりません。"
        )

    print(
        f"公式ページャー: "
        f"{current_page} -> {target}",
        flush=True,
    )

    for attempt in range(1, 6):

        try:
            result = page.evaluate(
                """
                target => {
                    const button =
                        document.querySelector(
                            `a[data-page="${target}"]`
                        );

                    if (!button) {
                        return "NOT_FOUND";
                    }

                    if (window.jQuery) {
                        window.jQuery(button).trigger("click");
                    } else {
                        button.click();
                    }

                    return "CLICK_OK";
                }
                """,
                target,
            )

            print(
                f"クリック {attempt}/5: {result}",
                flush=True,
            )

            if result != "CLICK_OK":
                time.sleep(2)
                continue

            deadline = time.time() + 35

            while time.time() < deadline:
                page.wait_for_timeout(500)

                new_links = extract_links(page)

                if not new_links:
                    continue

                new_signature = "|".join(
                    new_links[:10]
                )

                if new_signature != old_signature:
                    print(
                        f"ページ移動成功: "
                        f"{current_page} -> {target}",
                        flush=True,
                    )

                    return new_links

            print(
                "カード内容が変わりませんでした。",
                flush=True,
            )

        except Exception as e:
            print(
                f"クリックエラー "
                f"{attempt}/5: {e}",
                flush=True,
            )

        time.sleep(2)

    return None


def discover_all_links():
    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport={
                "width": 1280,
                "height": 900,
            }
        )

        print(
            "公式カード検索を開いています...",
            flush=True,
        )

        page.goto(
            SEARCH,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(3000)

        body_text = page.locator(
            "body"
        ).inner_text()

        total_match = re.search(
            r"([0-9][0-9,]*)枚",
            body_text,
        )

        reported_total = (
            int(
                total_match.group(1)
                .replace(",", "")
            )
            if total_match
            else 0
        )

        buttons = get_page_buttons(page)

        page_numbers = [
            x["page"]
            for x in buttons
        ]

        if not page_numbers:
            browser.close()

            raise RuntimeError(
                "公式ページャーを取得できません。"
            )

        last_page = max(page_numbers)

        print(
            f"公式表示カード数: {reported_total}",
            flush=True,
        )

        print(
            f"公式最終ページ: {last_page}",
            flush=True,
        )

        all_links = {}

        current_page = 1

        first_links = extract_links(page)

        for url in first_links:
            card_id = url.split(
                "id=", 1
            )[1].lower()

            all_links[card_id] = url

        print(
            f"page 1/{last_page}: "
            f"{len(first_links)} cards / "
            f"unique={len(all_links)}",
            flush=True,
        )

        while current_page < last_page:

            new_links = click_next_page(
                page,
                current_page,
                last_page,
            )

            if not new_links:
                browser.close()

                raise RuntimeError(
                    f"{current_page + 1}ページ目の取得に失敗。"
                    f"取得済み={len(all_links)}枚。"
                    "cards.jsonは更新しません。"
                )

            current_page += 1

            actual_page = get_current_page_from_url(
                page
            )

            print(
                f"URL上のページ番号: "
                f"{actual_page}",
                flush=True,
            )

            for url in new_links:
                card_id = url.split(
                    "id=", 1
                )[1].lower()

                all_links[card_id] = url

            print(
                f"page {current_page}/{last_page}: "
                f"{len(new_links)} cards / "
                f"unique={len(all_links)}",
                flush=True,
            )

        browser.close()

    links = list(
        all_links.values()
    )

    print(
        "===== 一覧取得完了 =====",
        flush=True,
    )

    print(
        f"ページ数: {last_page}",
        flush=True,
    )

    print(
        f"取得カード数: {len(links)}",
        flush=True,
    )

    print(
        f"公式表示カード数: {reported_total}",
        flush=True,
    )

    if (
        reported_total
        and len(links)
        < int(reported_total * 0.98)
    ):
        raise RuntimeError(
            "取得カード数が公式表示より少なすぎます。"
            f"{len(links)}/{reported_total}"
            " cards.jsonは更新しません。"
        )

    return (
        links,
        reported_total,
        last_page,
    )


def text_after(soup, label):
    text = soup.get_text(
        "\n",
        strip=True,
    )

    match = re.search(
        re.escape(label)
        + r"\s*\n([^\n]+)",
        text,
    )

    return (
        match.group(1).strip()
        if match
        else ""
    )


def parse_detail_html(html, url):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    heading = soup.find(
        ["h1", "h2"]
    )

    title = (
        heading.get_text(
            " ",
            strip=True,
        )
        if heading
        else ""
    )

    name = re.sub(
        r"\s*\([^)]*\)\s*$",
        "",
        title,
    ).strip()

    number = ""

    number_match = re.search(
        r"\(([^)]*)\)",
        title,
    )

    if number_match:
        number = number_match.group(1).strip()

    image = ""

    if heading:
        image_tag = heading.find_next("img")

        if image_tag and image_tag.get("src"):
            image = image_tag.get("src")

    card_id = (
        url.split("id=", 1)[1].lower()
        if "id=" in url
        else url
    )

    return {
        "id": card_id,
        "name": name,
        "number": number,
        "card_type": text_after(soup, "カードの種類"),
        "civilization": text_after(soup, "文明"),
        "rarity": text_after(soup, "レアリティ"),
        "power": text_after(soup, "パワー"),
        "cost": text_after(soup, "コスト"),
        "mana": text_after(soup, "マナ"),
        "race": text_after(soup, "種族"),
        "illustrator": text_after(soup, "イラストレーター"),
        "image": image,
        "url": url,
    }


def fetch_detail(session, url):
    for attempt in range(1, 4):

        try:
            response = session.get(
                url,
                headers=HEADERS,
                timeout=30,
            )

            response.raise_for_status()

            card = parse_detail_html(
                response.text,
                url,
            )

            if (
                card.get("id")
                and card.get("name")
            ):
                return card, None

            return None, "カード名を取得できません"

        except Exception as e:

            if attempt == 3:
                return None, str(e)

            time.sleep(attempt)

    return None, "unknown"


def fetch_details(links):
    total = len(links)

    cards = []
    failures = []

    workers = 8

    print(
        "===== 詳細ページ取得開始 =====",
        flush=True,
    )

    print(
        f"対象カード: {total}",
        flush=True,
    )

    def task(url):
        session = requests.Session()

        return fetch_detail(
            session,
            url,
        )

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = {
            executor.submit(
                task,
                url,
            ): url
            for url in links
        }

        done = 0

        for future in as_completed(
            futures
        ):

            url = futures[future]

            done += 1

            try:
                card, error = future.result()

            except Exception as e:
                card = None
                error = str(e)

            if card:
                cards.append(card)
            else:
                failures.append(
                    (
                        url,
                        error or "unknown",
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
                    flush=True,
                )

    allowed_failures = max(
        20,
        int(total * 0.01),
    )

    if len(failures) > allowed_failures:
        raise RuntimeError(
            "詳細ページ取得の失敗が多すぎます。"
            f"{len(failures)}/{total}"
            " cards.jsonは更新しません。"
        )

    if len(cards) < int(total * 0.98):
        raise RuntimeError(
            "取得カード数が少なすぎます。"
            f"{len(cards)}/{total}"
            " cards.jsonは更新しません。"
        )

    unique = {
        card["id"]: card
        for card in cards
        if card.get("id")
        and card.get("name")
    }

    data = sorted(
        unique.values(),
        key=lambda card: (
            card.get("number", ""),
            card.get("name", ""),
        ),
    )

    return data, failures


def main():

    links, reported_total, last_page = (
        discover_all_links()
    )

    data, failures = fetch_details(
        links
    )

    print(
        "===== 最終確認 =====",
        flush=True,
    )

    print(
        f"最終ユニークカード数: {len(data)}",
        flush=True,
    )

    print(
        f"公式表示カード数: {reported_total}",
        flush=True,
    )

    if (
        reported_total
        and len(data)
        < int(reported_total * 0.98)
    ):
        raise RuntimeError(
            "最終カード数が公式表示より少なすぎます。"
            f"{len(data)}/{reported_total}"
            " cards.jsonは更新しません。"
        )

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUT.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print(
        "==============================",
        flush=True,
    )

    print(
        f"SUCCESS: {len(data)} cards",
        flush=True,
    )

    print(
        f"保存先: {OUT}",
        flush=True,
    )

    print(
        "==============================",
        flush=True,
    )

    if failures:
        print(
            f"詳細取得失敗: {len(failures)}件",
            flush=True,
        )

        for url, error in failures[:20]:
            print(
                "FAIL",
                url,
                error,
                flush=True,
            )


if __name__ == "__main__":
    main()
