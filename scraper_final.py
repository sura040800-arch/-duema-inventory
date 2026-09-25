import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, parse_qs, unquote

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://dm.takaratomy.co.jp"
SEARCH = BASE + "/card/"
OUT = Path("data/cards.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DuemaInventoryUpdater/1.0)"}


def search_url(page_number: int = 1) -> str:
    state = {
        "suggest": "on",
        "keyword": "",
        "keyword_type": ["card_name", "card_ruby", "card_text", "race", "flavor", "illustrator"],
        "culture_cond": ["単色", "多色"],
        "pagenum": str(page_number),
        "samename": "show",
        "sort": "release_new",
    }
    return SEARCH + "?v=" + quote(json.dumps(state, ensure_ascii=False, separators=(",", ":")))


def extract_links(page):
    hrefs = page.locator('a[href*="/card/detail/"]').evaluate_all(
        "els => els.map(a => a.href).filter(Boolean)"
    )
    out, seen = [], set()
    for href in hrefs:
        m = re.search(r"[?&]id=([^&#]+)", href)
        if not m:
            continue
        cid = m.group(1)
        url = BASE + "/card/detail/?id=" + cid
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def current_page_number(page):
    try:
        if "?" not in page.url:
            return None
        qs = parse_qs(page.url.split("?", 1)[1])
        raw = qs.get("v", [""])[0]
        if raw:
            obj = json.loads(unquote(raw))
            return int(obj.get("pagenum", 1))
    except Exception:
        pass
    return None


def pager_pages(page):
    return page.locator('a[data-page]').evaluate_all(
        "els => els.map(a => Number(a.getAttribute('data-page'))).filter(Number.isFinite)"
    )


def click_page_and_wait(page, target, timeout=35000):
    """Trigger the official pager handler on an actually existing button."""
    selector = f'a[data-page="{target}"]'
    if page.locator(selector).count() == 0:
        return None
    old_sig = "|".join(extract_links(page)[:5])
    result = page.evaluate(
        """
        target => {
            const b = document.querySelector(`a[data-page="${target}"]`);
            if (!b) return "NOT_FOUND";
            if (window.jQuery) window.jQuery(b).trigger("click");
            else b.click();
            return "CLICK_OK";
        }
        """, target)
    print(f"official click target={target}: {result}", flush=True)
    if result != "CLICK_OK":
        return None
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        page.wait_for_timeout(500)
        links = extract_links(page)
        actual = current_page_number(page)
        sig = "|".join(links[:5])
        if actual == target and links and sig != old_sig:
            return links
    return None


def replace_pagenum(value, target):
    """Change pagenum in a URL, URL-encoded v JSON, or form body."""
    if not value:
        return value
    # Normal query parameter.
    value = re.sub(r'([?&]pagenum=)\d+', rf'\g<1>{target}', value)
    value = re.sub(r'(^|&)pagenum=\d+', rf'\g<1>pagenum={target}', value)
    # The official site normally stores the whole search state in ?v=JSON.
    try:
        from urllib.parse import urlsplit, urlunsplit, urlencode
        parts = urlsplit(value)
        qs = parse_qs(parts.query, keep_blank_values=True)
        if "v" in qs and qs["v"]:
            raw = qs["v"][0]
            obj = json.loads(unquote(raw))
            obj["pagenum"] = str(target)
            qs["v"] = [json.dumps(obj, ensure_ascii=False, separators=(",", ":"))]
            newq = urlencode(qs, doseq=True)
            value = urlunsplit((parts.scheme, parts.netloc, parts.path, newq, parts.fragment))
    except Exception:
        pass
    return value


def discover_ajax_request(page):
    """Capture the real XHR/fetch used by the official page-2 navigation."""
    captured = []
    def on_request(req):
        if req.resource_type in ("xhr", "fetch"):
            try:
                captured.append({
                    "url": req.url,
                    "method": req.method,
                    "post_data": req.post_data,
                    "headers": {k: v for k, v in req.headers.items()
                                if k.lower() in ("content-type", "x-requested-with", "referer")},
                })
            except Exception:
                pass
    page.on("request", on_request)
    links = click_page_and_wait(page, 2, timeout=35000)
    page.remove_listener("request", on_request)
    print(f"page2 async requests captured: {len(captured)}", flush=True)
    for i, x in enumerate(captured[-10:]):
        print(f"XHR[{i}] {x['method']} {x['url']} post={x['post_data']!r}", flush=True)
    # Prefer a request whose URL/body contains the search state or pagenum.
    for req in reversed(captured):
        blob = (req["url"] or "") + " " + (req["post_data"] or "")
        if "pagenum" in blob or "card" in blob.lower() or "search" in blob.lower():
            return req, links
    return (captured[-1] if captured else None), links


def links_from_html(html):
    if not html:
        return []
    # Usually the response is an HTML fragment. Also tolerate JSON wrapping HTML.
    candidates = [html]
    try:
        obj = json.loads(html)
        def collect(x):
            if isinstance(x, str): candidates.append(x)
            elif isinstance(x, dict):
                for v in x.values(): collect(v)
            elif isinstance(x, list):
                for v in x: collect(v)
        collect(obj)
    except Exception:
        pass
    out, seen = [], set()
    for text in candidates:
        if "/card/detail/" not in text:
            continue
        soup = BeautifulSoup(text, "html.parser")
        for a in soup.select('a[href*="/card/detail/"]'):
            href = a.get("href")
            if not href:
                continue
            if href.startswith("/"):
                href = BASE + href
            m = re.search(r"[?&]id=([^&#]+)", href)
            if not m:
                continue
            cid = m.group(1)
            url = BASE + "/card/detail/?id=" + cid
            if url not in seen:
                seen.add(url)
                out.append(url)
        if out:
            break
    return out


def replay_ajax(page, req, target):
    if not req:
        return None
    url = replace_pagenum(req["url"], target)
    post = replace_pagenum(req.get("post_data"), target)
    headers = dict(req.get("headers") or {})
    headers["referer"] = page.url
    try:
        r = page.request.fetch(
            url,
            method=req["method"],
            headers=headers,
            data=post if req["method"] not in ("GET", "HEAD") else None,
            fail_on_status_code=False,
            timeout=60000,
        )
        body = r.text()
        print(f"AJAX page {target}: status={r.status} bytes={len(body)}", flush=True)
        if r.status < 400 and "/card/detail/" in body:
            return body
    except Exception as e:
        print(f"AJAX replay failed page={target}: {e}", flush=True)
    return None

def discover_all_links():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

        pages = pager_pages(page)
        last_page = max(pages) if pages else 1
        body = page.locator("body").inner_text()
        m = re.search(r"([0-9][0-9,]*)枚", body)
        reported_total = int(m.group(1).replace(",", "")) if m else 0
        print(f"公式カード総数表示: {reported_total}", flush=True)
        print(f"公式最終ページ: {last_page}", flush=True)

        links_by_id = {}
        first = extract_links(page)
        for u in first:
            links_by_id[u.split("id=", 1)[1].lower()] = u
        print(f"page 1/{last_page}: +{len(first)} links, unique={len(links_by_id)}", flush=True)

        # First prove the known-good page 1 -> 2 transition and capture the
        # actual async request behind it. If the endpoint is replayable, we can
        # request pages 3..N without depending on the pager's moving DOM window.
        req, page2 = discover_ajax_request(page)
        if not page2:
            browser.close()
            raise RuntimeError("公式サイトの2ページ目取得に失敗しました。")
        for u in page2:
            links_by_id[u.split("id=", 1)[1].lower()] = u
        print(f"page 2/{last_page}: +{len(page2)} links, unique={len(links_by_id)}", flush=True)

        for target in range(3, last_page + 1):
            got = replay_ajax(page, req, target)
            if not got:
                # If replay is unavailable for a page, use the real visible
                # official button as a safe fallback rather than guessing.
                got = click_page_and_wait(page, target, timeout=35000)
            if not got:
                browser.close()
                raise RuntimeError(
                    f"{target}ページ目の取得に失敗。取得済み{len(links_by_id)}枚。cards.jsonは更新しません。"
                )
            for u in got:
                links_by_id[u.split("id=", 1)[1].lower()] = u
            if target % 10 == 0 or target == last_page:
                print(f"page {target}/{last_page}: +{len(got)} links, unique={len(links_by_id)}", flush=True)

        browser.close()

    links = list(links_by_id.values())
    print(f"ページ取得完了: {last_page}ページ / unique {len(links)} cards", flush=True)
    return links, reported_total, last_page

def text_after(soup, label):
    txt = soup.get_text("\n", strip=True)
    m = re.search(re.escape(label) + r"\s*\n([^\n]+)", txt)
    return m.group(1).strip() if m else ""


def parse_detail_html(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h = soup.find(["h1", "h2"])
    title = h.get_text(" ", strip=True) if h else ""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()
    number = ""
    m = re.search(r"\(([^)]*)\)", title)
    if m:
        number = m.group(1).strip()
    card_type = text_after(soup, "カードの種類")
    civilization = text_after(soup, "文明")
    rarity = text_after(soup, "レアリティ")
    power = text_after(soup, "パワー")
    cost = text_after(soup, "コスト")
    mana = text_after(soup, "マナ")
    race = text_after(soup, "種族")
    illustrator = text_after(soup, "イラストレーター")
    img = ""
    if h:
        im = h.find_next("img")
        if im and im.get("src"):
            img = im["src"]
    cid = url.split("id=", 1)[1].lower() if "id=" in url else url
    return {
        "id": cid,
        "name": name,
        "number": number,
        "card_type": card_type,
        "civilization": civilization,
        "rarity": rarity,
        "power": power,
        "cost": cost,
        "mana": mana,
        "race": race,
        "illustrator": illustrator,
        "image": img,
        "url": url,
    }


def fetch_detail(session, url):
    for attempt in range(1, 4):
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            card = parse_detail_html(r.text, url)
            if card.get("id") and card.get("name"):
                return card, None
            return None, "empty name"
        except Exception as e:
            if attempt == 3:
                return None, str(e)
            time.sleep(0.7 * attempt)
    return None, "unknown"


def fetch_details(links):
    cards = []
    failures = []
    total = len(links)
    workers = 8
    print(f"詳細ページ取得開始: {total}件 / workers={workers}", flush=True)

    def task(url):
        s = requests.Session()
        return fetch_detail(s, url)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(task, u): u for u in links}
        done = 0
        for fut in as_completed(futures):
            url = futures[fut]
            done += 1
            try:
                card, err = fut.result()
            except Exception as e:
                card, err = None, str(e)
            if card:
                cards.append(card)
            else:
                failures.append((url, err or "unknown"))
            if done % 100 == 0 or done == total:
                print(
                    f"details {done}/{total} success={len(cards)} fail={len(failures)}",
                    flush=True,
                )

    if failures and len(failures) > max(20, int(total * 0.01)):
        raise RuntimeError(f"詳細ページの失敗が多すぎます: {len(failures)}/{total}")
    if len(cards) < int(total * 0.98):
        raise RuntimeError(f"取得カード数が少なすぎます: {len(cards)}/{total}")

    unique = {c["id"]: c for c in cards if c.get("id") and c.get("name")}
    data = sorted(unique.values(), key=lambda c: (c.get("number", ""), c.get("name", "")))
    return data, failures


def main():
    links, reported_total, last_page = discover_all_links()
    if reported_total and len(links) < int(reported_total * 0.98):
        raise RuntimeError(f"一覧取得数が公式表示より少なすぎます: {len(links)}/{reported_total}")

    data, failures = fetch_details(links)
    print(f"最終ユニークカード数: {len(data)}", flush=True)
    if reported_total and len(data) < int(reported_total * 0.98):
        raise RuntimeError(f"最終カード数が公式表示より少なすぎます: {len(data)}/{reported_total}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(data)} cards to {OUT}", flush=True)
    if failures:
        print(f"詳細取得失敗: {len(failures)}件（1%未満のため公開）", flush=True)
        for url, err in failures[:20]:
            print("FAIL", url, err, flush=True)


if __name__ == "__main__":
    main()
