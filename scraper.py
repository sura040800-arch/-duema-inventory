import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://dm.takaratomy.co.jp"
SEARCH = BASE + "/card/"
OUT = Path("data/cards.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DuemaInventoryUpdater/1.0)"}


def search_url(page_number: int) -> str:
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
    out = []
    seen = set()
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


def first_ids(page):
    links = extract_links(page)
    return links[:5], links[-5:]


def direct_jump(page, target, old_signature):
    """Use the official pager's JS handler, while temporarily changing a visible
    data-page button into the requested target page.
    """
    for attempt in range(1, 6):
        try:
            result = page.evaluate(
                """
                ({target}) => {
                  const buttons = Array.from(document.querySelectorAll('a[data-page]'));
                  if (!buttons.length) return 'NOT_FOUND';
                  let b = buttons.find(x => x.getAttribute('data-page') !== String(target));
                  if (!b) b = buttons[0];
                  b.setAttribute('data-page', String(target));
                  if (window.jQuery) {
                    window.jQuery(b).attr('data-page', String(target)).data('page', target).trigger('click');
                  } else {
                    b.click();
                  }
                  return 'CLICK_OK';
                }
                """,
                {"target": target},
            )
            print(f"page {target}: attempt {attempt}/5 click={result}", flush=True)
            if result != "CLICK_OK":
                time.sleep(1)
                continue

            # The official pager is asynchronous. Card IDs are a more reliable
            # signal than the visual .current element.
            try:
                page.wait_for_function(
                    """old => {
                      const xs = Array.from(document.querySelectorAll('a[href*="/card/detail/"]'))
                        .map(a => a.href).filter(Boolean).slice(0, 5).join('|');
                      return xs && xs !== old;
                    }""",
                    old_signature,
                    timeout=12000,
                )
            except PlaywrightTimeoutError:
                pass

            new_links = extract_links(page)
            new_sig = "|".join(new_links[:5])
            url = page.url
            if new_sig and new_sig != old_signature and f"pagenum={target}" in url:
                return new_links

            # URL can be updated before the DOM settles, so give it another moment.
            time.sleep(2)
            new_links = extract_links(page)
            new_sig = "|".join(new_links[:5])
            if new_sig and new_sig != old_signature and f"pagenum={target}" in page.url:
                return new_links
        except Exception as e:
            print(f"page {target}: attempt {attempt}/5 error={e}", flush=True)
            time.sleep(1)
    return None


def discover_all_links():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

        # The official page currently exposes the final page as a data-page value.
        last_pages = page.locator('a[data-page]').evaluate_all(
            "els => els.map(a => Number(a.getAttribute('data-page'))).filter(Number.isFinite)"
        )
        last_page = max(last_pages) if last_pages else 1
        body = page.locator("body").inner_text()
        m = re.search(r"([0-9][0-9,]*)枚", body)
        reported_total = int(m.group(1).replace(",", "")) if m else 0
        print(f"公式カード総数表示: {reported_total}", flush=True)
        print(f"公式最終ページ: {last_page}", flush=True)

        links_by_id = {}
        links = extract_links(page)
        for u in links:
            cid = u.split("id=", 1)[1].lower()
            links_by_id[cid] = u
        print(f"page 1: {len(links)} cards", flush=True)

        if last_page >= 20:
            old_sig = "|".join(links[:5])
            test_links = direct_jump(page, 20, old_sig)
            if not test_links:
                raise RuntimeError("直接ページ移動テスト(20ページ目)に失敗。cards.jsonは更新しません。")
            print("直接ページ移動テスト: SUCCESS (20ページ目)", flush=True)

            # Return to page 1 before the production loop.
            page.goto(SEARCH, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)

        for target in range(2, last_page + 1):
            current = extract_links(page)
            old_sig = "|".join(current[:5])
            got = direct_jump(page, target, old_sig)
            if not got:
                raise RuntimeError(f"{target}ページ目への移動に失敗。取得済み{len(links_by_id)}枚。")
            for u in got:
                cid = u.split("id=", 1)[1].lower()
                links_by_id[cid] = u
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
                print(f"details {done}/{total} success={len(cards)} fail={len(failures)}", flush=True)

    # Do not silently publish a badly incomplete database.
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
