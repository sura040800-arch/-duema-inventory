from playwright.sync_api import sync_playwright


URL = "https://dm.takaratomy.co.jp/card/"


with sync_playwright() as p:

    browser = p.chromium.launch(headless=True)

    page = browser.new_page(
        viewport={
            "width": 1280,
            "height": 1000
        }
    )

    # =========================
    # ネットワーク監視
    # =========================

    def request_handler(request):

        if request.resource_type in ["xhr", "fetch"]:

            print("\n========== REQUEST ==========")
            print("METHOD:", request.method)
            print("URL:", request.url)

            try:
                print(
                    "POST:",
                    request.post_data
                )
            except:
                pass

    def response_handler(response):

        if response.request.resource_type in ["xhr", "fetch"]:

            print("\n========== RESPONSE ==========")
            print("STATUS:", response.status)
            print("URL:", response.url)

    page.on(
        "request",
        request_handler
    )

    page.on(
        "response",
        response_handler
    )

    # =========================
    # ページを開く
    # =========================

    print(
        "公式ページを開きます...",
        flush=True
    )

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(5000)

    print(
        "\n========== BEFORE ==========",
        flush=True
    )

    print(
        "URL:",
        page.url,
        flush=True
    )

    print(
        "カードリンク数:",
        page.locator(
            'a[href*="/card/detail/"]'
        ).count(),
        flush=True
    )

    # =========================
    # 2ページボタン
    # =========================

    target = page.locator(
        '[data-page="2"]'
    ).first

    print(
        "\n========== PAGE 2 BUTTON ==========",
        flush=True
    )

    if target.count() == 0:

        print(
            "data-page=2 が見つかりません",
            flush=True
        )

    else:

        print(
            "TAG:",
            target.evaluate(
                "el => el.tagName"
            ),
            flush=True
        )

        print(
            "HTML:",
            target.evaluate(
                "el => el.outerHTML"
            ),
            flush=True
        )

        print(
            "href:",
            target.get_attribute("href"),
            flush=True
        )

        print(
            "class:",
            target.get_attribute("class"),
            flush=True
        )

        print(
            "data-page:",
            target.get_attribute("data-page"),
            flush=True
        )

        print(
            "\n2ページ目をクリックします...",
            flush=True
        )

        target.click(
            force=True,
            timeout=10000
        )

        print(
            "クリック完了",
            flush=True
        )

        page.wait_for_timeout(10000)

        # =========================
        # 結果
        # =========================

        print(
            "\n========== AFTER ==========",
            flush=True
        )

        print(
            "URL:",
            page.url,
            flush=True
        )

        print(
            "カードリンク数:",
            page.locator(
                'a[href*="/card/detail/"]'
            ).count(),
            flush=True
        )

        # 現在表示されているカードIDを取得
        cards = page.locator(
            'a[href*="/card/detail/"]'
        )

        print(
            "\n========== CARD URLS ==========",
            flush=True
        )

        for i in range(
            min(cards.count(), 10)
        ):

            href = cards.nth(i).get_attribute(
                "href"
            )

            print(
                i + 1,
                href,
                flush=True
            )

    browser.close()
