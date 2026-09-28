import asyncio
from playwright.async_api import async_playwright


BASE_URL = "https://dm.takaratomy.co.jp/card/"


async def get_card_ids(page):

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


async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        page = await browser.new_page()

        print("=" * 60)
        print("公式サイト内部通信調査")
        print("=" * 60)

        # --------------------------------
        # 通信URLだけ記録
        # --------------------------------

        def request_handler(request):

            if request.resource_type in ["xhr", "fetch"]:

                print("")
                print("[通信]")
                print("METHOD:", request.method)
                print("URL:", request.url)

                if request.post_data:
                    print("POST:")
                    print(request.post_data[:1000])

        page.on("request", request_handler)

        # --------------------------------
        # 公式サイト
        # --------------------------------

        print("")
        print("公式サイトを開いています...")

        await page.goto(
            BASE_URL,
            wait_until="domcontentloaded",
            timeout=120000
        )

        await page.wait_for_timeout(7000)

        # --------------------------------
        # ページ1
        # --------------------------------

        ids1 = await get_card_ids(page)

        print("")
        print("=" * 60)
        print("ページ1")
        print("=" * 60)

        print("カード数:", len(ids1))

        for x in ids1[:5]:
            print(x)

        # --------------------------------
        # ページ2ボタン
        # --------------------------------

        print("")
        print("=" * 60)
        print("ページ2")
        print("=" * 60)

        buttons = page.locator(
            'a[data-page="2"]:visible'
        )

        count = await buttons.count()

        print("ページ2ボタン:", count)

        if count == 0:

            print("ページ2ボタンが見つかりません")

            await browser.close()
            return

        print("")
        print("ページ2をクリックします...")
        print("通信を監視しています...")

        await buttons.first.click(
            force=True,
            timeout=30000
        )

        # 通信が終わるまで待つ
        await page.wait_for_timeout(10000)

        # --------------------------------
        # ページ2
        # --------------------------------

        ids2 = await get_card_ids(page)

        print("")
        print("=" * 60)
        print("ページ2結果")
        print("=" * 60)

        print("カード数:", len(ids2))

        for x in ids2[:5]:
            print(x)

        # --------------------------------
        # 比較
        # --------------------------------

        overlap = len(
            set(ids1) & set(ids2)
        )

        print("")
        print("=" * 60)
        print("結果")
        print("=" * 60)

        print("ページ1:", len(ids1))
        print("ページ2:", len(ids2))
        print("重複:", overlap)

        if overlap < len(ids1):

            print("")
            print("★ カードが変化しています ★")
            print("内部通信を確認してください。")

        else:

            print("")
            print("★ カードが変化していません ★")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
