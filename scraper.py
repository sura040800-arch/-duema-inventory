import requests
from bs4 import BeautifulSoup
import json
from urllib.parse import quote


BASE_URL = "https://dm.takaratomy.co.jp/card/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
}


def get_cards(html):
    soup = BeautifulSoup(html, "html.parser")

    cards = []

    for a in soup.select('a[href*="/card/detail/"]'):
        href = a.get("href", "")

        if "id=" not in href:
            continue

        if href not in cards:
            cards.append(href)

    return cards


def main():

    session = requests.Session()
    session.headers.update(HEADERS)

    # ================================
    # 1ページ目
    # ================================

    print("1ページ目を取得中...", flush=True)

    r = session.get(
        BASE_URL,
        timeout=30
    )

    r.raise_for_status()

    cards1 = get_cards(r.text)

    print(
        f"1ページ目: {len(cards1)}枚",
        flush=True
    )

    if len(cards1) == 0:
        raise RuntimeError(
            "1ページ目のカード取得に失敗しました"
        )

    # ================================
    # 公式ページの検索条件を取得
    # ================================

    soup = BeautifulSoup(
        r.text,
        "html.parser"
    )

    form = soup.select_one(
        "form#search_cond"
    )

    if not form:
        raise RuntimeError(
            "公式検索フォームが見つかりません"
        )

    print(
        "公式検索フォームを確認しました",
        flush=True
    )

    # ================================
    # フォームの値を取得
    # ================================

    params = {}

    for element in form.select(
        "input, select, textarea"
    ):

        name = element.get("name")

        if not name:
            continue

        if element.name == "select":

            selected = element.select_one(
                "option[selected]"
            )

            if selected:
                params[name] = selected.get(
                    "value",
                    ""
                )

        elif element.name == "textarea":

            params[name] = element.get_text()

        else:

            input_type = element.get(
                "type",
                ""
            ).lower()

            if input_type in (
                "checkbox",
                "radio"
            ):
                if not element.has_attr("checked"):
                    continue

            params[name] = element.get(
                "value",
                ""
            )

    # ================================
    # pagenumだけ2にする
    # ================================

    print(
        f"元のpagenum: {params.get('pagenum')}",
        flush=True
    )

    params["pagenum"] = "2"

    print(
        "pagenumを2に変更",
        flush=True
    )

    # ================================
    # 公式フォームのaction
    # ================================

    action = form.get("action")

    if not action:
        action = BASE_URL

    if action.startswith("/"):
        action = "https://dm.takaratomy.co.jp" + action

    print(
        f"action: {action}",
        flush=True
    )

    # ================================
    # 公式と同じGET/POSTを実行
    # ================================

    method = form.get(
        "method",
        "get"
    ).lower()

    print(
        f"method: {method}",
        flush=True
    )

    if method == "post":

        response = session.post(
            action,
            data=params,
            timeout=30
        )

    else:

        response = session.get(
            action,
            params=params,
            timeout=30
        )

    response.raise_for_status()

    # ================================
    # 2ページ目確認
    # ================================

    cards2 = get_cards(
        response.text
    )

    print()
    print(
        "========================================",
        flush=True
    )

    print(
        f"2ページ目: {len(cards2)}枚",
        flush=True
    )

    print(
        f"取得URL: {response.url}",
        flush=True
    )

    print(
        "========================================",
        flush=True
    )

    # ================================
    # 判定
    # ================================

    if len(cards2) == 0:

        print()
        print(
            "❌ 2ページ目のカードが0枚です",
            flush=True
        )

        print()
        print(
            "HTML先頭:",
            response.text[:500],
            flush=True
        )

        return

    if cards1 == cards2:

        print()
        print(
            "❌ 1ページ目と2ページ目が同じです",
            flush=True
        )

        return

    print()
    print(
        "✅ 2ページ目取得成功！！",
        flush=True
    )

    print()
    print(
        "1ページ目のカード:"
    )

    for card in cards1[:3]:
        print(card)

    print()
    print(
        "2ページ目のカード:"
    )

    for card in cards2[:3]:
        print(card)


if __name__ == "__main__":
    main()
