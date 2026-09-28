import asyncio
from playwright.async_api import async_playwright


URL = "https://dm.takaratomy.co.jp/card/"


async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=True)

        page = await browser.new_page()

        print("=" * 60)
        print("ページ2クリック時の通信調査")
        print("=" * 60)

        # --------------------------------
        # 通信を記録
        # --------------------------------

        def on_request(request):

            url = request.url

            # 公式サイト関連だけ表示
            if "dm.takaratomy.co.jp" in url:

                print("")
                print("[REQUEST]")
                print("METHOD:", request.method)
                print("URL:")
                print(url)

                if request.post_data:

                    print("")
                    print("POST DATA:")
                    print(request.post_data[:3000])

        page.on("request", on_request)

        # --------------------------------
        # 公式サイト
        # --------------------------------

        print("")
        print("公式サイトを開いています...")

        await page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=120000
        )

        await page.wait_for_timeout(7000)

        # --------------------------------
        # 現在のカードID
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
        print("ページ1カード数:", len(ids1))

        print("ページ1先頭:")
        for x in ids1[:5]:
            print(x)

        # --------------------------------
        # ページ2ボタン
        # --------------------------------

        print("")
        print("=" * 60)
        print("ページ2をクリック")
        print("=" * 60)

        button = page.locator(
            'a[data-page="2"]:visible'
        ).first

        if await button.count() == 0:

            print("ページ2ボタンが見つかりません")

            await browser.close()
            return

        print("ページ2ボタン発見")

        # --------------------------------
        # クリック
        # --------------------------------

        await button.click(
            force=True,
            timeout=30000
        )

        print("")
        print("クリック完了")
        print("通信待機中...")

        # JavaScriptによる通信を待つ
        await page.wait_for_timeout(10000)

        # --------------------------------
        # 結果
        # --------------------------------

        ids2 = await get_ids()

        print("")
        print("=" * 60)
        print("結果")
        print("=" * 60)

        print("ページ1:", len(ids1))
        print("ページ2:", len(ids2))

        print("")
        print("ページ2先頭:")

        for x in ids2[:5]:
            print(x)

        print("")
        print("重複:")
        print(
            len(set(ids1) & set(ids2))
        )

        print("")
        print("=" * 60)
        print("調査終了")
        print("=" * 60)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
