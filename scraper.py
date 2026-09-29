import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlencode, urlparse, parse_qs


URL = "https://dm.takaratomy.co.jp/card/"

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

    result = []

    for a in soup.select('a[href*="/card/detail/"]'):

        href = a.get("href", "")

        if "id=" not in href:
            continue

        result.append(href)

    return list(dict.fromkeys(result))


def main():

    session = requests.Session()
    session.headers.update(HEADERS)

    print("1ページ目を取得中...")

    r = session.get(
        URL,
        timeout=30
    )

    r.raise_for_status()

    soup = BeautifulSoup(
        r.text,
        "html.parser"
    )

    cards1 = get_cards(r.text)

    print(
        f"1ページ目カード数: {len(cards1)}"
    )

    # --------------------------------
    # 公式フォーム取得
    # --------------------------------

    form = soup.select_one(
        "form#search_cond"
    )

    if not form:

        print(
            "ERROR: form#search_cond が見つかりません"
        )

        return

    print(
        "公式検索フォームを発見"
    )

    print(
        "method:",
        form.get("method")
    )

    print(
        "action:",
        form.get("action")
    )

    # --------------------------------
    # フォームの全入力値を取得
    # --------------------------------

    params = {}

    for element in form.select(
        "input, select, textarea"
    ):

        name = element.get("name")

        if not name:
            continue

        tag = element.name

        if tag == "select":

            selected = element.select_one(
                "option[selected]"
            )

            if selected:

                params[name] = selected.get(
                    "value",
                    ""
                )

            else:

                option = element.select_one(
                    "option"
                )

                if option:

                    params[name] = option.get(
                        "value",
                        ""
                    )

        elif tag == "textarea":

            params[name] = element.get_text()

        else:

            input_type = (
                element.get(
                    "type",
                    ""
                ).lower()
            )

            if input_type in (
                "checkbox",
                "radio"
            ):

                if not element.has_attr(
                    "checked"
                ):
                    continue

            params[name] = element.get(
                "value",
                ""
            )

    print()
    print("取得したフォーム項目:")

    for key, value in params.items():

        print(
            f"  {key} = {value}"
        )

    # --------------------------------
    # pagenumを2に変更
    # --------------------------------

    if "pagenum" not in params:

        print(
            "ERROR: pagenumがフォームにありません"
        )

        return

    params["pagenum"] = "2"

    # --------------------------------
    # 公式フォームのaction
    # --------------------------------

    action = form.get(
        "action"
    ) or URL

    action = urljoin(
        URL,
        action
    )

    method = (
        form.get(
            "method",
            "get"
        ).lower()
    )

    print()
    print(
        "2ページ目リクエスト"
    )

    print(
        "URL:",
        action
    )

    print(
        "METHOD:",
        method
    )

    # --------------------------------
    # リクエスト
    # --------------------------------

    if method == "post":

        r2 = session.post(
            action,
            data=params,
            timeout=30
        )

    else:

        r2 = session.get(
            action,
            params=params,
            timeout=30
        )

    r2.raise_for_status()

    cards2 = get_cards(
        r2.text
    )

    print()
    print(
        "========================================"
    )

    print(
        f"2ページ目カード数: {len(cards2)}"
    )

    print(
        f"2ページ目URL: {r2.url}"
    )

    print(
        "========================================"
    )

    # --------------------------------
    # 同じカードか確認
    # --------------------------------

    if cards1 == cards2:

        print()
        print(
            "❌ 1ページ目と2ページ目が同じ"
        )

        return

    if len(cards2) == 0:

        print()
        print(
            "❌ 2ページ目のカードが0枚"
        )

        return

    print()
    print(
        "✅ 2ページ目取得成功"
    )

    print()
    print(
        "1ページ目最初:",
        cards1[:3]
    )

    print(
        "2ページ目最初:",
        cards2[:3]
    )


if __name__ == "__main__":
    main()
