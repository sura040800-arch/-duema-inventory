def fetch_detail_with_browser(page, url):
    for attempt in range(1, 4):
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            if response is None:
                raise RuntimeError("レスポンスなし")

            status = response.status

            if status >= 400:
                raise RuntimeError(
                    f"HTTP {status}"
                )

            html = page.content()

            card = parse_detail_html(
                html,
                url,
            )

            if not card.get("name"):
                raise RuntimeError(
                    "カード名を取得できません"
                )

            return card, None

        except Exception as e:
            if attempt == 3:
                return None, str(e)

            time.sleep(1)

    return None, "unknown"


def fetch_details(links):

    print(
        "===== 詳細ページ取得テスト =====",
        flush=True,
    )

    # まず1枚だけブラウザで取得して確認する。
    test_url = links[0]

    print(
        f"テストURL: {test_url}",
        flush=True,
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            user_agent=HEADERS["User-Agent"]
        )

        page = context.new_page()

        # 画像などは読み込まない。
        # HTMLだけ取得して速度を上げる。
        def block_heavy(route):
            if route.request.resource_type in (
                "image",
                "media",
                "font",
                "stylesheet",
            ):
                route.abort()
            else:
                route.continue_()

        page.route(
            "**/*",
            block_heavy,
        )

        test_card, test_error = (
            fetch_detail_with_browser(
                page,
                test_url,
            )
        )

        if not test_card:

            browser.close()

            raise RuntimeError(
                "詳細ページの1枚目テストに失敗しました: "
                + str(test_error)
            )

        print(
            "1枚目テスト成功:",
            flush=True,
        )

        print(
            json.dumps(
                test_card,
                ensure_ascii=False,
            ),
            flush=True,
        )

        browser.close()

    print(
        "===== 詳細ページテスト成功 =====",
        flush=True,
    )

    print(
        "今回はここで終了します。",
        flush=True,
    )

    print(
        "23,478枚の本取得はまだ行いません。",
        flush=True,
    )

    # テスト成功だけ確認して止める。
    # cards.jsonは更新しない。
    raise RuntimeError(
        "TEST_OK: 詳細ページ1枚の取得に成功しました。"
        "本番取得はまだ実行していません。"
    )
