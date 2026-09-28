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
IDS_OUT = Path("data/card_ids.json")

HEADERS = {
    "User-Agent":
        "Mozilla/5.0 (compatible; DuemaInventoryUpdater/2.0)"
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


def extract_links(page):

    hrefs = page.locator(
        'a[href*="/card/detail/"]'
    ).evaluate_all(
        "els => els.map(a => a.href).filter(Boolean)"
    )

    out = []
    seen = set()

    for href in hrefs:

        m = re.search(
            r"[?&]id=([^&#]+)",
            href
        )

        if not m:
            continue

        cid = m.group(1)

        url = (
            BASE
            + "/card/detail/?id="
            + cid
        )

        if url not in seen:

            seen.add(url)
            out.append(url)

    return out


def current_page_number(page):

    try:

        if "?" not in page.url:
            return None

        qs = parse_qs(
            page.url.split("?", 1)[1]
        )

        raw = qs.get("v", [""])[0]

        if raw:

            obj=json.loads(
                unquote(raw)
            )

            return int(
                obj.get("pagenum", 1)
            )

    except Exception:
        pass

    return None


def pager_pages(page):

    return page.locator(
        'a[data-page]'
    ).evaluate_all(
        """
        els =>
          els
            .map(a => Number(a.getAttribute('data-page')))
            .filter(Number.isFinite)
        """
    )


def click_next_official_page(page, current):

    target=current+1

    for attempt in range(1,6):

        try:

            count=page.locator(
                f'a[data-page="{target}"]'
            ).count()

            if count==0:

                visible=pager_pages(page)

                raise RuntimeError(
                    f"次ページ {target} がDOMにありません。"
                    f" visible={visible}"
                )

            old_url=page.url

            old_ids=extract_links(page)[:5]

            old_sig="|".join(old_ids)

            result=page.evaluate(
                """
                target => {

                  const b =
                    document.querySelector(
                      `a[data-page="${target}"]`
                    );

                  if(!b){
                    return "NOT_FOUND";
                  }

                  if(window.jQuery){
                    window.jQuery(b).trigger("click");
                  }else{
                    b.click();
                  }

                  return "CLICK_OK";
                }
                """,
                target
            )

            print(
                f"page {current} -> {target}: "
                f"attempt {attempt}/5 "
                f"click={result}",
                flush=True
            )

            if result!="CLICK_OK":

                time.sleep(2)
                continue

            try:

                page.wait_for_function(
                    """
                    oldUrl =>
                      location.href !== oldUrl
                    """,
                    old_url,
                    timeout=15000
                )

            except PlaywrightTimeoutError:
                pass

            try:

                page.wait_for_function(
                    """
                    oldSig => {

                      const xs =
                        Array.from(
                          document.querySelectorAll(
                            'a[href*="/card/detail/"]'
                          )
                        )
                        .map(a => a.href)
                        .filter(Boolean)
                        .slice(0,5)
                        .join("|");

                      return xs && xs !== oldSig;
                    }
                    """,
                    old_sig,
                    timeout=20000
                )

            except PlaywrightTimeoutError:
                pass

            time.sleep(0.8)

            actual=current_page_number(page)

            new_links=extract_links(page)

            new_sig="|".join(
                new_links[:5]
            )

            if(
                actual==target
                and new_links
                and new_sig!=old_sig
            ):

                return new_links

            print(
                f"page {current} -> {target}: "
                f"まだ未完了 "
                f"actual={actual} "
                f"cards={len(new_links)}",
                flush=True
            )

            time.sleep(1.5)

        except Exception as e:

            print(
                f"page {current} -> {target}: "
                f"attempt {attempt}/5 "
                f"error={e}",
                flush=True
            )

            time.sleep(2)

    return None


def discover_all_links():

    with sync_playwright() as p:

        browser=p.chromium.launch(
            headless=True
        )

        page=browser.new_page(
            viewport={
                "width":1280,
                "height":900
            }
        )

        # 最新カード順で公式検索ページを開く
        page.goto(
            search_url(1),
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(2500)

        pages=pager_pages(page)

        last_page=max(pages) if pages else 1

        body=page.locator("body").inner_text()

        m=re.search(
            r"([0-9][0-9,]*)枚",
            body
        )

        reported_total=(
            int(
                m.group(1).replace(",", "")
            )
            if m
            else 0
        )

        print(
            f"公式カード総数表示: "
            f"{reported_total}",
            flush=True
        )

        print(
            f"公式最終ページ: "
            f"{last_page}",
            flush=True
        )

        # dictの挿入順をそのまま
        # 公式の最新→過去順として利用する
        links_by_id={}

        current=(
            current_page_number(page)
            or 1
        )

        links=extract_links(page)

        for u in links:

            cid=u.split(
                "id=",
                1
            )[1].lower()

            links_by_id[cid]=u

        print(
            f"page {current}/{last_page}: "
            f"+{len(links)} links, "
            f"unique={len(links_by_id)}",
            flush=True
        )

        while current<last_page:

            got=click_next_official_page(
                page,
                current
            )

            if not got:

                raise RuntimeError(
                    f"{current + 1}ページ目への"
                    f"公式ページ移動に失敗。"
                    f"取得済み{len(links_by_id)}枚。"
                )

            actual=current_page_number(page)

            if actual!=current+1:

                raise RuntimeError(
                    "ページ番号確認失敗: "
                    f"期待={current + 1}, "
                    f"実際={actual}。"
                    "cards.jsonは更新しません。"
                )

            current=actual

            for u in got:

                cid=u.split(
                    "id=",
                    1
                )[1].lower()

                links_by_id[cid]=u

            print(
                f"page {current}/{last_page}: "
                f"+{len(got)} links, "
                f"unique={len(links_by_id)}",
                flush=True
            )

        browser.close()

    links=list(
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


def all_text_lines(soup):

    text=soup.get_text(
        "\n",
        strip=True
    )

    lines=[]

    for x in text.splitlines():

        x=x.strip()

        if not x:
            continue

        lines.append(x)

    return lines


def text_after(lines,label):

    for i,x in enumerate(lines):

        if x==label:

            if i+1<len(lines):

                return lines[i+1]

    return ""


def section_between(
    lines,
    start_label,
    end_labels
):

    start=None

    for i,x in enumerate(lines):

        if x==start_label:

            start=i+1
            break

    if start is None:
        return ""

    result=[]

    for x in lines[start:]:

        if x in end_labels:
            break

        result.append(x)

    return "\n".join(result).strip()


def clean_ability_text(text):

    if not text:
        return ""

    lines=[]

    for line in text.splitlines():

        line=line.strip()

        if not line:
            continue

        # ページ上の不要な重複を軽減
        if line in {
            "特殊能力",
            "フレーバー"
        }:
            continue

        lines.append(line)

    return "\n".join(lines)


def parse_detail_html(html,url):

    soup=BeautifulSoup(
        html,
        "html.parser"
    )

    lines=all_text_lines(soup)

    h=soup.find(
        ["h1","h2"]
    )

    title=(
        h.get_text(
            " ",
            strip=True
        )
        if h
        else ""
    )

    name=re.sub(
        r"\s*\([^)]*\)\s*$",
        "",
        title
    ).strip()

    number=""

    m=re.search(
        r"\(([^)]*)\)",
        title
    )

    if m:
        number=m.group(1).strip()

    card_type=text_after(
        lines,
        "カードの種類"
    )

    civilization=text_after(
        lines,
        "文明"
    )

    rarity=text_after(
        lines,
        "レアリティ"
    )

    power=text_after(
        lines,
        "パワー"
    )

    cost=text_after(
        lines,
        "コスト"
    )

    mana=text_after(
        lines,
        "マナ"
    )

    race=text_after(
        lines,
        "種族"
    )

    illustrator=text_after(
        lines,
        "イラストレーター"
    )

    ability=section_between(
        lines,
        "特殊能力",
        [
            "フレーバー",
            "商品情報",
            "このカードのよくある質問"
        ]
    )

    flavor=section_between(
        lines,
        "フレーバー",
        [
            "商品情報",
            "このカードのよくある質問"
        ]
    )

    ability=clean_ability_text(
        ability
    )

    flavor=clean_ability_text(
        flavor
    )

    img=""

    if h:

        im=h.find_next(
            "img"
        )

        if im and im.get("src"):

            img=im["src"]

    # 念のためカード画像を探す
    if not img:

        for im in soup.find_all("img"):

            src=im.get("src","")

            if "cardimage" in src:

                img=src
                break

    if img.startswith("//"):

        img="https:"+img

    elif img.startswith("/"):

        img=BASE+img

    cid=(
        url.split(
            "id=",
            1
        )[1].lower()
        if "id=" in url
        else url
    )

    return {
        "id":cid,
        "name":name,
        "number":number,

        "card_type":card_type,
        "type":card_type,

        "civilization":civilization,
        "rarity":rarity,
        "power":power,
        "cost":cost,
        "mana":mana,
        "race":race,
        "illustrator":illustrator,

        "text":ability,
        "special_ability":ability,

        "flavor":flavor,

        "image":img,
        "url":url
    }


def fetch_detail(
    session,
    url
):

    for attempt in range(1,4):

        try:

            r=session.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            r.raise_for_status()

            card=parse_detail_html(
                r.text,
                url
            )

            if(
                card.get("id")
                and card.get("name")
            ):

                return card,None

            return None,"empty name"

        except Exception as e:

            if attempt==3:

                return None,str(e)

            time.sleep(
                0.7*attempt
            )

    return None,"unknown"


def fetch_details(links):

    cards=[]
    failures=[]

    total=len(links)

    workers=8

    print(
        f"詳細ページ取得開始: "
        f"{total}件 / "
        f"workers={workers}",
        flush=True
    )

    # 公式一覧の順番を保存
    release_order={}

    for index,url in enumerate(links):

        cid=url.split(
            "id=",
            1
        )[1].lower()

        release_order[cid]=index

    def task(url):

        s=requests.Session()

        return fetch_detail(
            s,
            url
        )

    with ThreadPoolExecutor(
        max_workers=workers
    ) as ex:

        futures={
            ex.submit(
                task,
                u
            ):u
            for u in links
        }

        done=0

        for fut in as_completed(
            futures
        ):

            url=futures[fut]

            done+=1

            try:

                card,err=fut.result()

            except Exception as e:

                card=None
                err=str(e)

            if card:

                cid=card["id"]

                card["release_order"]=
                    release_order.get(
                        cid,
                        999999999
                    )

                cards.append(card)

            else:

                failures.append(
                    (
                        url,
                        err or "unknown"
                    )
                )

            if(
                done%100==0
                or done==total
            ):

                print(
                    f"details "
                    f"{done}/{total} "
                    f"success={len(cards)} "
                    f"fail={len(failures)}",
                    flush=True
                )

    if failures and len(failures)>max(
        20,
        int(total*0.01)
    ):

        raise RuntimeError(
            f"詳細ページの失敗が多すぎます: "
            f"{len(failures)}/{total}"
        )

    if len(cards)<int(total*0.98):

        raise RuntimeError(
            f"取得カード数が少なすぎます: "
            f"{len(cards)}/{total}"
        )

    unique={
        c["id"]:c
        for c in cards
        if c.get("id")
        and c.get("name")
    }

    # 公式検索の最新→過去順
    data=list(
        sorted(
            unique.values(),
            key=lambda c:
                c.get(
                    "release_order",
                    999999999
                )
        )
    )

    return data,failures


def main():

    links,reported_total,last_page=\
        discover_all_links()

    if(
        reported_total
        and
        len(links)<int(
            reported_total*0.98
        )
    ):

        raise RuntimeError(
            "一覧取得数が公式表示より"
            "少なすぎます: "
            f"{len(links)}/"
            f"{reported_total}"
        )

    # ID一覧も保存
    IDS_OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    ids=[
        u.split(
            "id=",
            1
        )[1].lower()
        for u in links
    ]

    IDS_OUT.write_text(
        json.dumps(
            ids,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    data,failures=fetch_details(
        links
    )

    print(
        f"最終ユニークカード数: "
        f"{len(data)}",
        flush=True
    )

    if(
        reported_total
        and
        len(data)<int(
            reported_total*0.98
        )
    ):

        raise RuntimeError(
            "最終カード数が公式表示より"
            "少なすぎます: "
            f"{len(data)}/"
            f"{reported_total}"
        )

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    OUT.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            separators=(",",":")
        ),
        encoding="utf-8"
    )

    print(
        f"Wrote {len(data)} cards "
        f"to {OUT}",
        flush=True
    )

    if failures:

        print(
            f"詳細取得失敗: "
            f"{len(failures)}件",
            flush=True
        )

        for url,err in failures[:20]:

            print(
                "FAIL",
                url,
                err,
                flush=True
            )


if __name__=="__main__":
    main()
