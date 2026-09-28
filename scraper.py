import asyncio
from playwright.async_api import async_playwright


BASE_URL = "https://dm.takaratomy.co.jp/card/"


async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        page = await browser.new_page()

        print("=" * 70)
        print("公式サイト内部通信調査")
        print("=" * 70)

        # --------------------------------
        # 通信を監視
        # --------------------------------

        def on_request(request):

            if request.resource_type in ["xhr", "fetch"]:

                url = request.url

                print("")
                print("[REQUEST]")
                print("METHOD:", request.method)
                print("URL:", url)

                if request.post_data:
                    print("POST DATA:")
                    print(request.post_data[:2000])

        async def on_response(response):

            if response.request.resource_type not in ["xhr", "fetch"]:
                return

            print("")
            print("[RESPONSE]")
            print("STATUS:", response.status)
            print("URL:", response.url)

            content_type = response.headers.get(
                "content-type",
                ""
            )

            print("CONTENT-TYPE:", content_type)

            # JSONっぽいレスポンスなら中身も少し見る
            if (
                "json" in content_type
                or "javascript" in content_type
            ):

                try:
                    body = await response.text()

                    print("BODY:")
                    print(body[:3000])

                except Exception as e:
                    print("BODY取得失敗:", e)

        page.on("request", on_request)
        page.on("response", on_response)

        # --------------------------------
        # コンソールエラーも監視
        # --------------------------------

        page.on(
            "console",
            lambda msg: print(
                "[CONSOLE]",
                msg.type,
                msg.text
            )
        )

        page.on(
            "pageerror",
            lambda error: print(
                "[PAGE ERROR]",
                error
            )
        )

        # --------------------------------
        # 公式サイトを開く
        # --------------------------------

        print("")
        print("公式カード検索を開いています...")

        await page.goto(
            BASE_URL,
            wait_until="domcontentloaded",
            timeout=120000
        )

        await page.wait_for_timeout(7000)

        print("")
        print("現在URL:")
        print(page.url)

        # --------------------------------
        # 現在のカード
        # --------------------------------

        async def get_ids():

            ids = await page.locator(
                'a[href*="/card/detail/?id="]'
            ).evaluate_all(
                """
                els => els.map(e => {
                    const href = e.getAttribute("href") || "";
                    const m = href.match(/[?&]id=([^&]+)/);
                    return m ? m[1] : null;
                }).filter(Boolean)
                """
            )

            return list(dict.fromkeys(ids))

        ids1 = await get_ids()

        print("")
        print("ページ1")
        print("カード数:", len(ids1))
        print("先頭:", ids1[:5])

        # --------------------------------
        # ページ2ボタン確認
        # --------------------------------

        print("")
        print("=" * 70)
        print("ページ2ボタンを調査")
        print("=" * 70)

        buttons = page.locator(
            'a[data-page="2"]'
        )

        count = await buttons.count()

        print("ページ2ボタン総数:", count)

        for i in range(count):

            try:

                visible = await buttons.nth(i).is_visible()

                text = await buttons.nth(i).inner_text()

                href = await buttons.nth(i).get_attribute(
                    "href"
                )

                outer = await buttons.nth(i).evaluate(
                    "el => el.outerHTML"
                )

                print("")
                print("BUTTON", i)
                print("visible:", visible)
                print("text:", text)
                print("href:", href)
                print("HTML:")
                print(outer[:2000])

            except Exception as e:

                print(
                    "ボタン情報取得失敗:",
                    e
                )

        # --------------------------------
        # ページ2クリック
        # --------------------------------

        print("")
        print("=" * 70)
        print("ページ2をクリックします")
        print("=" * 70)

        visible_buttons = page.locator(
            'a[data-page="2"]:visible'
        )

        visible_count = await visible_buttons.count()

        print(
            "表示中のページ2ボタン:",
            visible_count
        )

        if visible_count == 0:

            print("")
            print("★ ページ2ボタンがありません ★")

            await browser.close()
            return

        before_url = page.url

        print("")
        print("クリック前URL:")
        print(before_url)

        await visible_buttons.first.click(
            force=True,
            timeout=30000
        )

        print("")
        print("クリック完了")
        print("通信完了待ち...")

        await page.wait_for_timeout(10000)

        # --------------------------------
        # 結果
        # --------------------------------

        ids2 = await get_ids()

        print("")
        print("=" * 70)
        print("ページ2クリック後")
        print("=" * 70)

        print("URL:")
        print(page.url)

        print("")
        print("カード数:")
        print(len(ids2))

        print("")
        print("先頭5枚:")

        for card_id in ids2[:5]:
            print(card_id)

        print("")
        print("ページ1との重複:")
        print(
            len(set(ids1) & set(ids2))
        )

        # --------------------------------
        # 最終判定
        # --------------------------------

        print("")
        print("=" * 70)
        print("調査終了")
        print("=" * 70)

        if ids1 != ids2:

            print("")
            print("★ カード一覧が変化しました ★")
            print("")
            print("内部通信を上に表示しています。")

        else:

            print("")
            print("★ カード一覧は変化していません ★")
            print("")
            print("内部通信またはJavaScript側に問題があります。")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
