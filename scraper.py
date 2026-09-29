from playwright.sync_api import sync_playwright


URL = "https://dm.takaratomy.co.jp/card/"


with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=True
    )

    page = browser.new_page()

    print("公式ページを開いています...", flush=True)

    # ネットワーク監視
    def on_request(request):
        if request.resource_type in ["xhr", "fetch"]:
            print()
            print("REQUEST")
            print("METHOD:", request.method)
            print("URL:", request.url)
            print("POST:", request.post_data)
            print()

    def on_response(response):
        if response.request.resource_type in ["xhr", "fetch"]:
            print()
            print("RESPONSE")
            print("STATUS:", response.status)
            print("URL:", response.url)
            print()

    page.on("request", on_request)
    page.on("response", on_response)

    page.goto(
        URL,
        wait_until="networkidle",
        timeout=120000
    )

    page.wait_for_timeout(3000)

    print()
    print("==============================")
    print("ページ情報")
    print("==============================")

    # ページ番号リンク
    elements = page.locator(
        '#cardlist [data-page]'
    )

    print(
        "data-page要素数:",
        elements.count(),
        flush=True
    )

    for i in range(
        min(elements.count(), 20)
    ):

        el = elements.nth(i)

        print()
        print(
            "ELEMENT",
            i
        )

        print(
            el.evaluate(
                """e => e.outerHTML"""
            )
        )

    print()
    print("==============================")
    print("2ページ目をクリック")
    print("==============================")

    target = page.locator(
        '#cardlist [data-page="2"]'
    )

    print(
        "2ページ目要素:",
        target.count(),
        flush=True
    )

    if target.count() == 0:

        print(
            "2ページ目要素が見つかりません"
        )

        browser.close()

        raise RuntimeError(
            "data-page=2 がありません"
        )

    # クリック前のカード
    before = page.locator(
        '#cardlist a[href*="/card/detail/"]'
    ).count()

    print(
        "クリック前カード数:",
        before,
        flush=True
    )

    print(
        "クリックします...",
        flush=True
    )

    target.first.scroll_into_view_if_needed()

    target.first.click(
        force=True
    )

    # JS/AJAX待機
    page.wait_for_timeout(8000)

    after = page.locator(
        '#cardlist a[href*="/card/detail/"]'
    ).count()

    print()
    print("==============================")
    print("クリック後")
    print("==============================")

    print(
        "URL:",
        page.url,
        flush=True
    )

    print(
        "カード数:",
        after,
        flush=True
    )

    print()
    print(
        "pagenum:",
        page.locator(
            'input[name="pagenum"]'
        ).input_value()
        if page.locator(
            'input[name="pagenum"]'
        ).count()
        else "なし"
    )

    print()
    print("==============================")
    print("完了")
    print("==============================")

    browser.close()
