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

try:
    from pykakasi import kakasi
    _kana_converter = kakasi()
except ImportError:
    _kana_converter = None


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
RUBY_RETRY_DAYS = 7
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
    """公式ページャーの最終ページを優先し、なければ実ページ件数から計算する。"""
    soup = BeautifulSoup(html, "html.parser")

    # WP-PageNaviに最終ページが明示されていれば、それが最も確実。
    for selector in (
        "#cardlist .wp-pagenavi a.last[data-page]",
        "#cardlist .wp-pagenavi a.last",
        "#cardlist .wp-pagenavi a[aria-label*='最後']",
    ):
        node = soup.select_one(selector)
        if node:
            raw = node.get("data-page")
            if raw and str(raw).isdigit():
                return int(raw)
            href = node.get("href", "")
            match = re.search(r"[?&](?:paged|page|pagenum)=([0-9]+)", href)
            if match:
                return int(match.group(1))

    total = get_total_card_count(html)
    first_page_count = len(extract_card_links(html))
    if total and first_page_count:
        return (total + first_page_count - 1) // first_page_count

    # 最終リンクが存在しないテーマ向けの保険。近傍リンク最大値を
    # 最終ページと誤認しないよう、総枚数がない場合は処理を止める。
    raise RuntimeError("公式カード一覧の最終ページ数を確定できませんでした")

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
def browser_get_page(page, page_number, previous_ids):
    """WP-PageNaviの「次へ」をたどって指定ページへ移動する。

    ページ番号リンクは通常、近傍の数ページ分しかDOMに存在しないため、
    a[data-page="N"]を直接探す方式だと途中で巡回が止まる。
    """
    print(f"{page_number}ページ目へ移動...", flush=True)

    pager = page.locator("#cardlist .wp-pagenavi")
    if pager.count() == 0:
        raise RuntimeError("ページ送りが見つかりません")

    anchors = pager.locator("a")
    next_locator = pager.locator(
        'a[rel="next"], a.nextpostslink, a.next, a[aria-label*="次"], a[title*="次"]'
    ).first

    if next_locator.count() == 0:
        # クラス名に依存せず「次へ」記号のリンクを探す。
        link_info = anchors.evaluate_all("""
            els => els.map((a, index) => ({
              index,
              page: Number(a.getAttribute('data-page')),
              text: (a.innerText || '').trim(),
              cls: String(a.className || ''),
              rel: String(a.getAttribute('rel') || '')
            }))
        """)
        next_info = next((x for x in link_info if
            x['rel'].lower() == 'next' or
            'next' in x['cls'].lower() or
            re.search(r'^(次へ|next|›|»|→|＞|〉)$', x['text'], re.I)
        ), None)
        if next_info:
            next_locator = anchors.nth(next_info['index'])
        else:
            current = page_number - 1
            target = current + 1
            target_info = next((x for x in link_info if x['page'] == target), None)
            if not target_info:
                raise RuntimeError(
                    f"{page_number}ページ目への連続したページリンクがありません。"
                    "飛びページを誤取得しないため中止します。"
                )
            next_locator = anchors.nth(target_info['index'])

    if next_locator.count() == 0:
        raise RuntimeError(f"{page_number}ページ目の次リンクが見つかりません")

    next_locator.click(timeout=15000)
    start_time = time.time()
    while time.time() - start_time < 40:
        html = page.content()
        links = extract_card_links(html)
        ids = [x[0] for x in links]
        if ids and ids != previous_ids:
            return links
        time.sleep(0.4)
    raise RuntimeError(f"{page_number}ページ目のカード取得がタイムアウトしました")


def get_total_card_count(html):
    """公式一覧に表示される総カード枚数を取得する。"""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    matches = re.findall(r"([\d,]+)\s*枚", text)
    for value in matches:
        try:
            total = int(value.replace(",", ""))
            if total >= 1000:
                return total
        except ValueError:
            pass
    return None

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

        last_page = get_page_count(html)
        expected_total = get_total_card_count(html)

        print(
            f"1ページ目: {len(first_links)}枚",
            flush=True
        )

        print(f"最終ページ: {last_page}", flush=True)
        if expected_total:
            print(f"公式掲載総数: {expected_total}枚", flush=True)

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

                    # ページ1へ戻し、次へリンクを順番にたどって再開位置まで復帰。
                    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(1500)
                    current_links = extract_card_links(page.content())
                    for back in range(2, page_number):
                        previous_ids = [x[0] for x in current_links]
                        current_links = browser_get_page(page, back, previous_ids)

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
        raise RuntimeError(f"取得枚数が少なすぎます: {len(all_links)}")
    if expected_total and len(all_links) != expected_total:
        raise RuntimeError(
            f"公式掲載数と取得数が一致しません: 公式{expected_total}枚 / 取得{len(all_links)}枚。"
            "不完全な一覧でcards.jsonを上書きしないため中止します。"
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


def clean_reading_punctuation(value):
    """読み文字列に残るカード名用の括弧・引用符を取り除く。"""
    return re.sub(r"[《》「」『』“”‘’]", "", str(value or "")).strip()


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
        r"([一-龯々〆ヵヶ]+[”’」』】〕]*)[（(]([ぁ-ゖァ-ヺー]+)[）)]",
        lambda m: m.group(2),
        value,
    )
    return re.sub(r"\[\s*編集\s*\]", "", clean_reading_punctuation(value))


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
    base_text = re.sub(r"\[\s*編集\s*\]", "", clean_text(base.get_text("", strip=True))).strip("《》")
    # 括弧ルビ形式も比較用に取り除く。
    base_text = re.sub(r"([一-龯々〆ヵヶ]+[”’」』】〕]*)[（(][ぁ-ゖァ-ヺー]+[）)]", r"\1", base_text)
    if normalize_card_title(base_text) != normalize_card_title(card_name):
        return ""

    has_ruby = bool(heading.find("ruby")) or bool(
        re.search(r"[一-龯々〆ヵヶ]+[”’」』】〕]*[（(][ぁ-ゖァ-ヺー]+[）)]", heading.get_text("", strip=True))
    )
    if not has_ruby:
        return ""
    reading = ruby_heading_text(heading)
    return clean_reading_punctuation(reading) if reading and normalize_card_title(reading) != normalize_card_title(card_name) else ""


def _wiki_get(url, params=None):
    """Wikiへのアクセスを全ワーカーで共有レート制限する。"""
    global _last_wiki_request_at
    with _wiki_request_lock:
        now = time.monotonic()
        wait = WIKI_REQUEST_INTERVAL - (now - _last_wiki_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_wiki_request_at = time.monotonic()
    response = requests.get(
        url,
        params=params,
        headers={**HEADERS, "Referer": "https://dmwiki.net/"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response


def fetch_wiki_reading(card_name):
    """DM Wikiのカード記事から読みを取得。URL直引きに失敗した場合はMediaWiki APIも使う。"""
    title = f"《{card_name}》"
    encoded_title = quote(title, safe="")
    urls = (
        WIKI_BASE_URL + encoded_title,
        "https://m.dmwiki.net/" + encoded_title,
    )
    for url in urls:
        try:
            response = _wiki_get(url)
            reading = extract_wiki_card_reading(response.text, card_name)
            if reading:
                return reading
        except requests.RequestException as exc:
            print(f"Wiki読み取得失敗: {card_name}: {exc}", flush=True)
        except Exception as exc:
            print(f"Wiki読み解析失敗: {card_name}: {exc}", flush=True)

    # URLエンコードや記事名の差異で直接URLが解決できない場合にAPIで正確な記事を探す。
    api_url = "https://dmwiki.net/api.php"
    title_candidates = (title, card_name)
    for candidate in title_candidates:
        try:
            response = _wiki_get(api_url, {
                "action": "parse", "page": candidate, "prop": "text",
                "format": "json", "formatversion": 2,
            })
            payload = response.json()
            html = payload.get("parse", {}).get("text", "")
            if html:
                reading = extract_wiki_card_reading(html, card_name)
                if reading:
                    return reading
        except requests.RequestException as exc:
            print(f"Wiki API読み取得失敗: {card_name}: {exc}", flush=True)
        except (ValueError, TypeError, AttributeError) as exc:
            print(f"Wiki API読み解析失敗: {card_name}: {exc}", flush=True)

    return ""


def ruby_attempt_is_recent(card, now=None):
    """Wiki等の確定読みは保持し、機械生成読みは定期的に再照合する。"""
    source = card.get("ruby_source", "")
    if card.get("card_ruby") and source not in ("generated", "fallback"):
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
    """ruby注釈(rt/rp)や括弧ルビを除いた正式名称を返す。"""
    clone = BeautifulSoup(str(node), "html.parser")
    for tag in clone.find_all(("rt", "rp")):
        tag.decompose()
    value = clean_text(clone.get_text("", strip=True))
    return re.sub(
        r"([一-龯々〆ヵヶ]+[”’」』】〕]*)[（(]([ぁ-ゖァ-ヺー]+)[）)]",
        r"\1",
        value,
    )


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
    value = clean_text(clone.get_text("", strip=True))
    return re.sub(
        r"([一-龯々〆ヵヶ]+[”’」』】〕]*)[（(]([ぁ-ゖァ-ヺー]+)[）)]",
        lambda m: m.group(2),
        value,
    )


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
        heading_text = clean_text(heading.get_text("", strip=True))
        if re.search(r"[一-龯々〆ヵヶ]+[”’」』】〕]*[（(][ぁ-ゖァ-ヺー]+[）)]", heading_text):
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
        "ruby_checked": bool(card_ruby),
        "number": cid,
        "type": get_after("カードの種類"),
        "civilization": get_after("文明"),
        "rarity": get_after("レアリティ"),
        "power": get_after("パワー"),
        "cost": get_after("コスト"),
        "mana": get_after("マナ"),
        "race": get_after("種族"),
        "illustrator": get_after("イラストレーター"),
        "abilities": [x.strip() for x in re.split(r"\n+", ability) if x.strip()],
        "text": ability,
        "flavor": flavor,
        "sides": [{
            "type": get_after("カードの種類"),
            "civilization": get_after("文明"),
            "rarity": get_after("レアリティ"),
            "power": get_after("パワー"),
            "cost": get_after("コスト"),
            "mana": get_after("マナ"),
            "race": get_after("種族"),
            "illustrator": get_after("イラストレーター"),
            "abilities": [x.strip() for x in re.split(r"\n+", ability) if x.strip()],
            "flavor": flavor
        }],
        "image": image_url,
        "url": url,
        "release_order": release_order
    }


def fetch_card(item):
    """新規カード詳細を最大3回取得。失敗カードを黙って欠落させない。"""
    global _last_request_at
    cid, url, release_order = item
    last_error = None

    for attempt in range(1, 4):
        try:
            with _request_lock:
                now = time.monotonic()
                wait = REQUEST_INTERVAL - (now - _last_request_at)
                if wait > 0:
                    time.sleep(wait)
                _last_request_at = time.monotonic()

            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            card = parse_detail(cid, url, response.text, release_order)
            if not card.get("name"):
                raise RuntimeError("カード名を抽出できません")
            return card
        except Exception as exc:
            last_error = exc
            print(f"詳細取得失敗 {cid} retry {attempt}/3: {exc}", flush=True)
            if attempt < 3:
                time.sleep(attempt * 2)

    print(f"詳細取得を断念: {cid}: {last_error}", flush=True)
    return None



def generate_fallback_reading(card_name):
    """確定ルビが見つからないカード向けの読み仮名フォールバック。

    pykakasiは一般的な漢字読みを生成する。特殊な当て字・固有読みはDM Wikiの
    ルビを優先し、機械生成した読みにはruby_source=generatedを付けて区別する。
    """
    if not card_name:
        return ""
    if _kana_converter is None:
        return ""
    try:
        parts = _kana_converter.convert(card_name)
        reading = "".join(str(part.get("hira", part.get("orig", ""))) for part in parts)
        return clean_text(reading) or card_name
    except Exception as exc:
        print(f"読み仮名フォールバック失敗: {card_name}: {exc}", flush=True)
        return card_name


def main():
    if _kana_converter is None:
        raise RuntimeError("読み仮名生成に必要な pykakasi がありません。依存パッケージをインストールしてください")
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
            # 既存データを読めない状態で空のカード一覧を作って上書きしない。
            raise RuntimeError(f"既存cards.jsonを安全に読み込めません。上書きを中止します: {exc}") from exc
        if not isinstance(old_data, list):
            raise RuntimeError("既存cards.jsonが配列形式ではありません。上書きを中止します")

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
            card["official_listed"] = True
            cards_by_id[cid] = card

    # 公式検索から一時的に消えた既存カードも削除しない。
    # 所持カード・デッキの参照切れを防ぎ、一覧復帰時は通常データへ戻す。
    archived_count = 0
    for cid, card in old_cards.items():
        if cid not in cards_by_id:
            card["official_listed"] = False
            cards_by_id[cid] = card
            archived_count += 1
    for cid in all_links:
        if cid in cards_by_id:
            cards_by_id[cid]["official_listed"] = True

    missing_ids = set(all_links) - set(cards_by_id)
    if missing_ids:
        sample = ", ".join(sorted(missing_ids)[:10])
        raise RuntimeError(
            f"新規カード詳細の取得漏れが{len(missing_ids)}枚あります（例: {sample}）。"
            "不完全なカードデータで既存cards.jsonを上書きしないため中止します。"
        )

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
        # Wiki等で確認済みの読みがあれば同名の全印刷版へ伝播。
        # 機械生成読みは確定扱いせず、7日ごとにWikiの特殊読みで上書きできるようにする。
        existing_reading = next((
            c.get("card_ruby") for c in group
            if c.get("card_ruby") and c.get("ruby_source") not in ("generated", "fallback")
        ), "")
        if existing_reading:
            for card in group:
                card["card_ruby"] = existing_reading
                card["ruby_checked"] = True
                card["ruby_source"] = card.get("ruby_source") or "existing"
            continue

        # 漢字を含まない名前は名前自体を読み検索語として保持する。
        if not re.search(r"[一-龯々〆ヵヶ]", card_name):
            for card in group:
                card["card_ruby"] = card_name
                card["ruby_checked"] = True
                card["ruby_source"] = "identity"
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
                    fallback = generate_fallback_reading(card_name)
                    card["card_ruby"] = fallback
                    card["ruby_checked"] = bool(fallback)
                    card["ruby_source"] = "generated" if fallback else "not_found"
        elif any(c.get("card_ruby") and c.get("ruby_source") not in ("generated", "fallback") for c in group):
            reading = next(c["card_ruby"] for c in group if c.get("card_ruby") and c.get("ruby_source") not in ("generated", "fallback"))
            for card in group:
                card["card_ruby"] = reading
                card["ruby_checked"] = True
                card["ruby_source"] = card.get("ruby_source") or "existing"
        elif any(re.search(r"[一-龯々〆ヵヶ]", card_name) for _ in (0,)):
            fallback = generate_fallback_reading(card_name)
            for card in group:
                card["card_ruby"] = fallback
                card["ruby_checked"] = bool(fallback)
                card["ruby_source"] = "generated" if fallback else "not_found"

    cards = list(cards_by_id.values())
    cards.sort(key=lambda x: x.get("release_order", 999999999))

    # 一時ファイルへ完全に書き込んでから置換し、途中失敗でJSONを壊さない。
    cards_tmp = CARDS_FILE + ".tmp"
    ids_tmp = IDS_FILE + ".tmp"
    with open(cards_tmp, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)
    with open(ids_tmp, "w", encoding="utf-8") as f:
        json.dump(list(all_links.keys()), f, ensure_ascii=False, indent=2)
    os.replace(cards_tmp, CARDS_FILE)
    os.replace(ids_tmp, IDS_FILE)

    found_unique = sum(1 for group in groups.values() if any(c.get("card_ruby") for c in group))
    wiki_unique = sum(1 for group in groups.values() if any(c.get("ruby_source") == "dmwiki" for c in group))
    generated_unique = sum(1 for group in groups.values() if any(c.get("ruby_source") == "generated" for c in group))
    missing_ruby = len(groups) - found_unique
    print("========================================", flush=True)
    print(f"カード数: {len(cards)}枚", flush=True)
    print(f"新規取得: {len(new_cards)}枚", flush=True)
    print(f"公式一覧外として保持: {archived_count}枚", flush=True)
    print(f"読みあり: {found_unique}/{len(groups)}種類", flush=True)
    print(f"Wiki確認ルビ: {wiki_unique}種類", flush=True)
    print(f"機械生成ルビ: {generated_unique}種類", flush=True)
    print(f"読み未取得: {missing_ruby}種類（7日後に再試行）", flush=True)
    print("========================================", flush=True)


if __name__ == "__main__":
    main()
