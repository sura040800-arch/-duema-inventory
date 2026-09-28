import asyncio
from playwright.async_api import async_playwright

URL = "https://dm.takaratomy.co.jp/card/"


async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        page = await browser.new_page()

        print("公式サイトを開いています...")

        await page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=120000
        )

        await page.wait_for_timeout(7000)

        print("")
        print("現在URL:")
        print(page.url)

        print("")
        print("=" * 60)
        print("ページ2ボタン調査")
        print("=" * 60)

        buttons = page.locator(
            'a[data-page="2"]'
        )

        count = await buttons.count()

        print("ページ2ボタン数:", count)

        for i in range(count):

            button = buttons.nth(i)

            try:
                visible = await button.is_visible()
                href = await button.get_attribute("href")
                onclick = await button.get_attribute("onclick")
                data_page = await button.get_attribute("data-page")
                html = await button.evaluate(
                    "el => el.outerHTML"
                )

                print("")
                print("----- BUTTON", i, "-----")
                print("visible:", visible)
                print("data-page:", data_page)
                print("href:", href)
                print("onclick:", onclick)
                print("HTML:")
                print(html[:3000])

            except Exception as e:

                print("取得エラー:", repr(e))

        print("")
        print("=" * 60)
        print("調査終了")
        print("=" * 60)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
