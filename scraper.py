import os
import re
import json
import time
import threading
import unicodedata
import requests
from urllib.parse import quote
from datetime import datetime, timezone, timedelta

from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright


BASE_URL = "https://dm.takaratomy.co.jp"
SEARCH_URL = BASE_URL + "/card/"

DATA_DIR = "data"
CARDS_FILE = os.path.join(DATA_DIR, "cards.json")
IDS_FILE = os.path.join(DATA_DIR, "card_ids.json")

MAX_WORKERS = 6
TIMEOUT = 30
REQUEST_INTERVAL = 0.25
WIKI_BASE_URL = "https://dmwiki.net/"
WIKI_REQUEST_INTERVAL = 0.75
WIKI_MAX_WORKERS = 5
RUBY_RETRY_DAYS = 30
_request_lock = threading.Lock()
_last_request_at = 0.0
_wiki_request_lock = threading.Lock()
_last_wiki_request_at = 0.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
}


def clean_text(value):
    if not value:
        return ""

    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def absolute_url(url):
    if not url:
        return ""

    if url.startswith("http"):
        return url

    return BASE_URL + url


def card_id_from_url(url):
    if not url:
        return None

    m = re.search(
        r"[?&]id=([^&#]+)",
        url
    )

    if not m:
        return None

    return m.group(1)


def extract_card_links(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    result = []
    seen = set()

    for a in soup.select(
        'a[href*="/card/detail/"]'
    ):
        href = a.get(
            "href",
            ""
        )

        cid = card_id_from_url(href)

        if not cid:
            continue

        if cid in seen:
            continue

        seen.add(cid)

        result.append(
            (
                cid,
                absolute_url(href)
            )
        )

    return result


def get_page_count(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    values = []

    for a in soup.select(
        "#cardlist .wp-pagenavia a[data-page]"
    ):
        value = a.get(
            "data-page"
        )

        try:
            values.append(
                int(value)
            )
        except Exception:
            pass

    if values:
        return max(values)

    text = soup.get_text(
        " ",
        strip=True
    )

    matches = re.findall(
        r"([\d,]+)\s*枚",
        text
    )

    for value in matches:

        try:

            total = int(
                value.replace(
                    ",",
                    ""
                )
            )

            if total >= 1000:
                return (
                    total + 49
                ) // 50

        except Exception:
            pass

    raise RuntimeError(
        "最終ページ数を取得できませんでした"
    )


def get_page_ids(page):
    links = page.locator(
        '#cardlist .wp-pagenavi a'
    ).evaluate_all(
        """
        els => els.map(a => ({
            page: a.getAttribute("data-page"),
            text: a.innerText
        }))
        """
    )

    return links
def browser_get_page(
    page,
    page_number,
    previous_ids
):
    """
    現在の公式カード一覧ページから
    指定ページのリンクをクリックして移動する。
    """

    print(
        f"{page_number}ページ目へ移動...",
        flush=True
    )

    selector = (
        f'#cardlist .wp-pagenavi '
        f'a[data-page="{page_number}"]'
    )

    locator = page.locator(selector).first

    if locator.count() == 0:
        raise RuntimeError(
            f"{page_number}ページ目のリンクが"
            "見つかりません"
        )

    locator.dispatch_event(
        "click"
    )

    start = time.time()

    while True:
        html = page.content()

        links = extract_card_links(
            html
        )

        ids = [
            x[0]
            for x in links
        ]

        if ids and ids != previous_ids:
            return links

        if time.time() - start > 30:
            raise RuntimeError(
                f"{page_number}ページ目のカード取得が"
                "タイムアウトしました"
            )

        time.sleep(0.5)
def discover_all_cards():

    print()
    print("========================================")
    print("公式カード一覧を取得")
    print("========================================")

    all_links = {}
    release_order = {}

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            user_agent=HEADERS["User-Agent"]
        )

        page = context.new_page()

        print(
            "公式カード検索を開いています...",
            flush=True
        )

        page.goto(
            SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(
            2000
        )

        # --------------------------------
        # 1ページ目
        # --------------------------------

        html = page.content()

        first_links = extract_card_links(
            html
        )

        if not first_links:

            browser.close()

            raise RuntimeError(
                "1ページ目からカードを取得できませんでした"
            )

        last_page = get_page_count(
            html
        )

        print(
            f"1ページ目: {len(first_links)}枚",
            flush=True
        )

        print(
            f"最終ページ: {last_page}",
            flush=True
        )

        order = 0

        for cid, url in first_links:

            all_links[cid] = url
            release_order[cid] = order
            order += 1

        # --------------------------------
        # ページ2以降
        # --------------------------------

        current_links = first_links

        for page_number in range(
            2,
            last_page + 1
        ):

            success = False

            for attempt in range(
                1,
                4
            ):

                try:

                    previous_ids = [
                        x[0]
                        for x in current_links
                    ]

                    current_links = (
                        browser_get_page(
                            page,
                            page_number,
                            previous_ids
                        )
                    )

                    new_count = 0

                    for cid, url in current_links:

                        if cid not in all_links:

                            all_links[cid] = url

                            release_order[cid] = order

                            order += 1

                            new_count += 1

                    print(
                        f"[{page_number}/{last_page}] "
                        f"{len(current_links)}枚 / "
                        f"新規{new_count}枚 / "
                        f"累計{len(all_links)}枚",
                        flush=True
                    )

                    success = True
                    break

                except Exception as e:

                    print(
                        f"retry {attempt}/3: {e}",
                        flush=True
                    )

                    time.sleep(2)

                    # ページ1に戻す
                    page.goto(
                        SEARCH_URL,
                        wait_until="domcontentloaded",
                        timeout=60000
                    )

                    page.wait_for_timeout(
                        1500
                    )

                    current_links = (
                        extract_card_links(
                            page.content()
                        )
                    )

                    # 失敗ページまで戻す
                    for back in range(
                        2,
                        page_number
                    ):

                        previous_ids = [
                            x[0]
                            for x in current_links
                        ]

                        current_links = (
                            browser_get_page(
                                page,
                                back,
                                previous_ids
                            )
                        )

            if not success:

                browser.close()

                raise RuntimeError(
                    f"{page_number}ページ目の取得に失敗しました"
                )

        browser.close()

    print()
    print("========================================")
    print(
        f"一覧取得完了: {len(all_links)}枚"
    )
    print("========================================")

    if len(all_links) < 10000:

        raise RuntimeError(
            f"取得枚数が少なすぎます: {len(all_links)}"
        )

    return all_links, release_order


def clean_card_name(value):
    """カード番号・商品情報などの末尾を除いたカード名。"""
    value = clean_text(value)
    value = re.sub(r"\s*\|\s*デュエル・マスターズ\s*$", "", value)
    value = re.sub(
        r"\s*[（(]\s*DM[A-Z0-9-]*\s+[^()（）]*?/[^()（）]*?[）)]\s*$",
        "",
        value,
        flags=re.I,
    )
    return value.strip()


def normalize_card_title(value):
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^0-9a-zぁ-ゖァ-ヺ一-龯々〆ヵヶ]", "", value)


def ruby_heading_text(node):
    """Wiki見出しのruby/括弧ルビを読みへ置換した文字列を返す。"""
    clone = BeautifulSoup(str(node), "html.parser")
    for ruby in clone.find_all("ruby"):
        rt = ruby.find("rt")
        rb = ruby.find("rb")
        reading = clean_text(rt.get_text("", strip=True)) if rt else ""
        base = clean_text(rb.get_text("", strip=True)) if rb else ""
        if reading:
            ruby.replace_with(reading)
        elif base:
            ruby.replace_with(base)
    for tag in clone.find_all(("rt", "rp")):
        tag.decompose()
    value = clean_text(clone.get_text("", strip=True))
    # Wiki側の表示形式が「漢字(かな)」のテキストになっている場合も処理。
    value = re.sub(
        r"([一-龯々〆ヵヶ]+)[（(]([ぁ-ゖァ-ヺー]+)[）)]",
        lambda m: m.group(2),
        value,
    )
    return value.strip("《》「」『』")


def extract_wiki_card_reading(html, card_name):
    """DM Wikiのカード記事見出しから、カード名全体のルビ読みを抽出。"""
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1#firstHeading, h1.mw-first-heading, h1")
    if not heading:
        return ""

    # ルビを外した見出しが、照合対象の正式カード名と一致する場合のみ採用。
    base = BeautifulSoup(str(heading), "html.parser")
    for tag in base.find_all(("rt", "rp")):
        tag.decompose()
    base_text = clean_text(base.get_text("", strip=True)).strip("《》")
    # 括弧ルビ形式も比較用に取り除く。
    base_text = re.sub(r"([一-龯々〆ヵヶ]+)[（(][ぁ-ゖァ-ヺー]+[）)]", r"\1", base_text)
    if normalize_card_title(base_text) != normalize_card_title(card_name):
        return ""

    has_ruby = bool(heading.find("ruby")) or bool(
        re.search(r"[一-龯々〆ヵヶ]+[（(][ぁ-ゖァ-ヺー]+[）)]", heading.get_text("", strip=True))
    )
    if not has_ruby:
        return ""
    reading = ruby_heading_text(heading)
    return reading if reading and normalize_card_title(reading) != normalize_card_title(card_name) else ""


def fetch_wiki_reading(card_name):
    """カード名に対応するDM Wiki記事からルビ読みを取得。"""
    global _last_wiki_request_at
    title = f"《{card_name}》"
    urls = (
        WIKI_BASE_URL + quote(title, safe=""),
        "https://dmwiki.net/index.php?title=" + quote(title, safe=""),
    )
    for url in urls:
        try:
            with _wiki_request_lock:
                now = time.monotonic()
                wait = WIKI_REQUEST_INTERVAL - (now - _last_wiki_request_at)
                if wait > 0:
                    time.sleep(wait)
                _last_wiki_request_at = time.monotonic()
            response = requests.get(
                url,
                headers={**HEADERS, "Referer": "https://dmwiki.net/"},
                timeout=TIMEOUT,
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            reading = extract_wiki_card_reading(response.text, card_name)
            if reading:
                return reading
            # 200でも別ページ/リダイレクトで見出しが一致しなければ次URLへ。
        except requests.RequestException as exc:
            print(f"Wiki読み取得失敗: {card_name}: {exc}", flush=True)
        except Exception as exc:
            print(f"Wiki読み解析失敗: {card_name}: {exc}", flush=True)
    return ""


def ruby_attempt_is_recent(card, now=None):
    """読み未発見カードの連日再取得を避ける。成功済みは永久に再取得しない。"""
    if card.get("card_ruby"):
        return True
    stamp = card.get("ruby_attempted_at")
    if not stamp:
        return False
    try:
        attempted = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if attempted.tzinfo is None:
            attempted = attempted.replace(tzinfo=timezone.utc)
        now = now or datetime.now(timezone.utc)
        return now - attempted < timedelta(days=RUBY_RETRY_DAYS)
    except Exception:
        return False


def extract_ruby_base_text(node):
    """ruby注釈(rt/rp)を除いた、カードに印刷された正式名称を返す。"""
    clone = BeautifulSoup(str(node), "html.parser")
    for tag in clone.find_all(("rt", "rp")):
        tag.decompose()
    return clean_text(clone.get_text("", strip=True))


def extract_ruby_reading(node):
    """ruby注釈を読みへ置き換えた名称を返す。"""
    clone = BeautifulSoup(str(node), "html.parser")
    for ruby in clone.find_all("ruby"):
        rt = ruby.find("rt")
        rb = ruby.find("rb")
        reading = clean_text(rt.get_text("", strip=True)) if rt else ""
        base = clean_text(rb.get_text("", strip=True)) if rb else ""
        if reading:
            ruby.replace_with(reading)
        elif base:
            ruby.replace_with(base)
    for tag in clone.find_all(("rt", "rp")):
        tag.decompose()
    return clean_text(clone.get_text("", strip=True))


def extract_card_ruby(soup, title=""):
    """公式カード詳細HTMLからカード名の読み（ruby/rt等）を抽出する。

    カード名見出しにあるルビを最優先し、補助的にdata属性・埋め込みJSONを確認する。
    見出し以外のページ内ruby（ナビゲーション等）を誤って読みとして採用しない。
    """
    heading = soup.find("h1")
    if heading:
        ruby_nodes = heading.find_all("ruby")
        if ruby_nodes:
            value = extract_ruby_reading(heading)
            if value:
                return value

    # 公式ページのHTML属性に読みが保持されている場合
    for node in (heading, *soup.select("[data-card-ruby], [data-ruby], [data-reading], [data-yomi]")):
        if not node:
            continue
        for attr in ("data-card-ruby", "data-ruby", "data-reading", "data-yomi", "aria-label"):
            value = node.get(attr)
            if isinstance(value, str):
                value = clean_text(value)
                if value and (attr != "aria-label" or (title and title in value)):
                    return value

    # WordPress側の埋め込みJSON/JSにある公式読みキー
    patterns = (
        r'["\'](?:card_ruby|cardRuby|ruby|reading|yomi)["\']\s*:\s*["\']([^"\']+)["\']',
    )
    for script in soup.find_all("script"):
        raw = script.string or script.get_text("", strip=True)
        if not raw or not any(k in raw.lower() for k in ("card_ruby", "cardruby", "reading", "yomi")):
            continue
        for pattern in patterns:
            match = re.search(pattern, raw, re.I)
            if match:
                value = clean_text(match.group(1))
                if value:
                    return value

    return ""


def parse_detail(
    cid,
    url,
    html,
    release_order
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    h1 = soup.find("h1")
    card_ruby = extract_card_ruby(soup)

    title = ""

    if h1:
        # rubyのrt（読み）を正式カード名に混ぜない。
        title = extract_ruby_base_text(h1)

    name = title

    if "(" in name:
        name = name.split(
            "(",
            1
        )[0].strip()

    image_url = ""

    image = soup.select_one(
        'img[src*="/cardimage/"]'
    )

    if not image:
        image = soup.select_one(
            "main img"
        )

    if image:
        image_url = absolute_url(
            image.get(
                "src",
                ""
            )
        )

    text = soup.get_text(
        "\n",
        strip=True
    )

    lines = [
        clean_text(x)
        for x in text.splitlines()
    ]

    def get_after(label):

        for i, line in enumerate(lines):

            if line == label:

                if i + 1 < len(lines):
                    return lines[i + 1]

        return ""

    ability = ""

    if "特殊能力" in text:

        part = text.split(
            "特殊能力",
            1
        )[1]

        if "フレーバー" in part:

            part = part.split(
                "フレーバー",
                1
            )[0]

        ability = clean_text(
            part
        )

    flavor = ""

    if "フレーバー" in text:

        flavor = clean_text(
            text.split(
                "フレーバー",
                1
            )[1]
        )

    return {
        "id": cid,
        "name": name,
        "card_ruby": card_ruby,
        "ruby_checked": True,
        "number": cid,
        "type": get_after("カードの種類"),
        "civilization": get_after("文明"),
        "rarity": get_after("レアリティ"),
        "power": get_after("パワー"),
        "cost": get_after("コスト"),
        "mana": get_after("マナ"),
        "race": get_after("種族"),
        "illustrator": get_after("イラストレーター"),
        "text": ability,
        "flavor": flavor,
        "image": image_url,
        "url": url,
        "release_order": release_order
    }


def fetch_card(item):

    global _last_request_at
    cid, url, release_order = item

    try:
        # 公式サイトへのアクセスを一定間隔に制限し、初回の全件読み取得で
        # 短時間に大量リクエストを送らない。
        with _request_lock:
            now = time.monotonic()
            wait = REQUEST_INTERVAL - (now - _last_request_at)
            if wait > 0:
                time.sleep(wait)
            _last_request_at = time.monotonic()

        r = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        r.raise_for_status()

        return parse_detail(
            cid,
            url,
            r.text,
            release_order
        )

    except Exception as e:

        print(
            f"失敗: {cid} {e}",
            flush=True
        )

        return None


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    all_links, release_order = discover_all_cards()

    old_cards = {}
    if os.path.exists(CARDS_FILE):
        try:
            with open(CARDS_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            if isinstance(old_data, list):
                for card in old_data:
                    cid = card.get("id")
                    if cid:
                        old_cards[cid] = card
        except Exception as exc:
            print(f"既存cards.json読込失敗: {exc}", flush=True)

    print(f"既存カード: {len(old_cards)}枚", flush=True)
    new_targets = [
        (cid, url, release_order[cid])
        for cid, url in all_links.items()
        if cid not in old_cards
    ]
    print(f"新規カード詳細取得対象: {len(new_targets)}枚", flush=True)

    new_cards = []
    if new_targets:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_card, item): item for item in new_targets}
            for index, future in enumerate(as_completed(futures), 1):
                card = future.result()
                if card:
                    new_cards.append(card)
                if index % 100 == 0 or index == len(futures):
                    print(f"新規カード詳細取得: {index}/{len(futures)}", flush=True)

    # 既存カードの情報を保持し、一覧側で変わったURL/発売順だけ更新。
    cards_by_id = {}
    for cid, url in all_links.items():
        if cid in old_cards:
            card = old_cards[cid]
            card["release_order"] = release_order[cid]
            card["url"] = url
            cards_by_id[cid] = card
    for card in new_cards:
        cid = card.get("id")
        if cid:
            cards_by_id[cid] = card

    # 読み取得は印刷版ごとではなく、同じ正式カード名ごとに1回だけ行う。
    groups = {}
    for card in cards_by_id.values():
        card_name = clean_card_name(card.get("name", ""))
        if not card_name:
            continue
        groups.setdefault(card_name, []).append(card)

    now = datetime.now(timezone.utc)
    wiki_targets = []
    for card_name, group in groups.items():
        # すでに読みがある版があれば同名の全印刷版へ伝播。
        existing_reading = next((c.get("card_ruby") for c in group if c.get("card_ruby")), "")
        if existing_reading:
            for card in group:
                card["card_ruby"] = existing_reading
                card["ruby_checked"] = True
                card["ruby_source"] = card.get("ruby_source") or "existing"
            continue

        # かな/英数字だけの名前には漢字ルビ照合が不要。
        if not re.search(r"[一-龯々〆ヵヶ]", card_name):
            for card in group:
                card["ruby_checked"] = True
                card["ruby_source"] = "not_required"
            continue

        # 旧版で ruby_checked=True なのに空欄になったカードも、成功扱いにせず再試行する。
        if any(not ruby_attempt_is_recent(card, now) for card in group):
            wiki_targets.append(card_name)

    print(f"DM Wiki読み取得対象: {len(wiki_targets)}種類", flush=True)
    wiki_results = {}
    if wiki_targets:
        with ThreadPoolExecutor(max_workers=WIKI_MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_wiki_reading, name): name for name in wiki_targets}
            for index, future in enumerate(as_completed(futures), 1):
                card_name = futures[future]
                try:
                    wiki_results[card_name] = future.result() or ""
                except Exception as exc:
                    print(f"Wiki取得エラー {card_name}: {exc}", flush=True)
                    wiki_results[card_name] = ""
                if index % 100 == 0 or index == len(futures):
                    found = sum(bool(v) for v in wiki_results.values())
                    print(f"読み取得: {index}/{len(futures)} / 成功{found}", flush=True)

    attempted_at = now.isoformat(timespec="seconds")
    for card_name, group in groups.items():
        if card_name in wiki_results:
            reading = wiki_results[card_name]
            for card in group:
                card["ruby_attempted_at"] = attempted_at
                if reading:
                    card["card_ruby"] = reading
                    card["ruby_checked"] = True
                    card["ruby_source"] = "dmwiki"
                else:
                    # 取得できなかったものを成功済み扱いにしない。30日後に再試行。
                    card["ruby_checked"] = False
                    card["ruby_source"] = "not_found"
        elif any(c.get("card_ruby") for c in group):
            reading = next(c["card_ruby"] for c in group if c.get("card_ruby"))
            for card in group:
                card["card_ruby"] = reading
                card["ruby_checked"] = True

    cards = list(cards_by_id.values())
    cards.sort(key=lambda x: x.get("release_order", 999999999))

    with open(CARDS_FILE, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)
    with open(IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(all_links.keys()), f, ensure_ascii=False, indent=2)

    found_unique = sum(1 for group in groups.values() if any(c.get("card_ruby") for c in group))
    print("========================================", flush=True)
    print(f"カード数: {len(cards)}枚", flush=True)
    print(f"新規取得: {len(new_cards)}枚", flush=True)
    print(f"読みあり: {found_unique}/{len(groups)}種類", flush=True)
    print("========================================", flush=True)


if __name__ == "__main__":
    main()
