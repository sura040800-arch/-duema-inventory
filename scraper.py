import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


BASE_URL = "https://dm.takaratomy.co.jp"
SEARCH_URL = BASE_URL + "/card/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
}


def get_card_urls(html):
    soup = BeautifulSoup(html, "html.parser")

    urls = []

    for a in soup.select(
        '#cardlist a[href*="/card/detail/"]'
    ):
        href = a.get("href")

        if href:
            full = urljoin(BASE_URL, href)

            if full not in urls:
                urls.append(full)

    return urls


def get_form_data(soup):
    form = soup.select_one("#search_cond")

    if not form:
        raise RuntimeError(
            "#search_cond が見つかりません"
        )

    data = {}

    for element in form.select(
        "input, select, textarea"
    ):

        name = element.get("name")

        if not name:
            continue

        tag = element.name

        # -------------------------
        # input
        # -------------------------
        if tag == "input":

            input_type = (
                element.get("type") or "text"
            ).lower()

            if input_type in (
                "submit",
                "button",
                "reset",
                "image",
            ):
                continue

            if input_type in (
                "checkbox",
                "radio",
            ):
                if not element.has_attr("checked"):
                    continue

            value = element.get("value", "")

        # -------------------------
        # select
        # -------------------------
        elif tag == "select":

            selected = element.select_one(
                "option[selected]"
            )

            if selected:
                value = selected.get(
                    "value", ""
                )
            else:
                value = ""

        # -------------------------
        # textarea
        # -------------------------
        else:
            value = element.text

        # -------------------------
        # 同じnameが複数ある場合
        # -------------------------
        if name.endswith("[]"):

            if name not in data:
                data[name] = []

            data[name].append(value)

        else:
            data[name] = value

    return form, data


def main():

    session = requests.Session()
    session.headers.update(HEADERS)

    print("公式ページを取得中...", flush=True)

    # ==================================================
    # 1ページ目
    # ==================================================

    response = session.get(
        SEARCH_URL,
        timeout=60
    )

    response.raise_for_status()

    soup1 = BeautifulSoup(
        response.text,
        "html.parser"
    )

    print(
        "1ページ目取得完了",
        flush=True
    )

    urls1 = get_card_urls(
        response.text
    )

    print(
        "1ページ目カード数:",
        len(urls1),
        flush=True
    )

    print(
        "1ページ目先頭:",
        urls1[:5],
        flush=True
    )

    # ==================================================
    # 公式検索フォーム
    # ==================================================

    form, data = get_form_data(
        soup1
    )

    action = form.get("action")

    if not action:
        action = SEARCH_URL

    action = urljoin(
        SEARCH_URL,
        action
    )

    method = (
        form.get("method") or "get"
    ).lower()

    print(
        "フォーム送信先:",
        action,
        flush=True
    )

    print(
        "フォーム送信方法:",
        method.upper(),
        flush=True
    )

    # ==================================================
    # 2ページ目
    # ==================================================

    print(
        "2ページ目を取得中...",
        flush=True
    )

    # 公式JavaScriptがやっていること
    # input[name="pagenum"] にページ番号を入れて
    # form.submit() している
    data["pagenum"] = "2"

    if method == "post":

        response2 = session.post(
            action,
            data=data,
            timeout=60
        )

    else:

        response2 = session.get(
            action,
            params=data,
            timeout=60
        )

    response2.raise_for_status()

    urls2 = get_card_urls(
        response2.text
    )

    # ==================================================
    # 結果
    # ==================================================

    print()
    print("==============================")
    print("結果")
    print("==============================")

    print(
        "2ページ目URL:",
        response2.url,
        flush=True
    )

    print(
        "2ページ目カード数:",
        len(urls2),
        flush=True
    )

    print(
        "2ページ目先頭:",
        urls2[:10],
        flush=True
    )

    print()
    print("==============================")
    print("判定")
    print("==============================")

    if not urls2:

        print(
            "❌ 2ページ目のカードが取得できませんでした",
            flush=True
        )

        raise RuntimeError(
            "2ページ目取得失敗"
        )

    if urls1 == urls2:

        print(
            "❌ 1ページ目と2ページ目が同じです",
            flush=True
        )

        print(
            "公式のページ切り替え方法をさらに調査します",
            flush=True
        )

        raise RuntimeError(
            "ページ切り替え失敗"
        )

    print(
        "🎉 2ページ目の取得成功！",
        flush=True
    )

    print(
        "1ページ目:",
        urls1[:3],
        flush=True
    )

    print(
        "2ページ目:",
        urls2[:3],
        flush=True
    )


if __name__ == "__main__":
    main()
