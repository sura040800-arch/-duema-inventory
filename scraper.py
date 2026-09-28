import asyncio
from playwright.async_api import async_playwright


URL = "https://dm.takaratomy.co.jp/card/"


async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("=" * 60)
        print("ページ送り処理だけ調査")
        print("=" * 60)

        await page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=120000
        )

        await page.wait_for_timeout(5000)

        # JavaScriptファイル
        scripts = await page.locator(
            "script[src]"
        ).evaluate_all(
            """
            els => els.map(e => e.src).filter(Boolean)
            """
        )

        scripts = list(dict.fromkeys(scripts))

        keywords = [
            "pagenum",
            "data-page",
            "page_num",
            "pagination"
        ]

        results = []

        print("")
        print("JSファイル:", len(scripts), "個")

        # --------------------------------
        # 外部JS
        # --------------------------------

        for src in scripts:

            try:

                response = await page.request.get(src)

                if not response.ok:
                    continue

                text = await response.text()

                for keyword in keywords:

                    pos = text.find(keyword)

                    if pos == -1:
                        continue

                    snippet = text[
                        max(0, pos - 700):
                        pos + 1500
                    ]

                    results.append({
                        "file": src,
                        "keyword": keyword,
                        "snippet": snippet
                    })

            except Exception:
                pass

        # --------------------------------
        # インラインJS
        # --------------------------------

        inline = await page.locator(
            "script:not([src])"
        ).evaluate_all(
            """
            els => els.map(e => e.textContent || "")
            """
        )

        for i, text in enumerate(inline):

            for keyword in keywords:

                pos = text.find(keyword)

                if pos == -1:
                    continue

                results.append({
                    "file": "INLINE_" + str(i),
                    "keyword": keyword,
                    "snippet": text[
                        max(0, pos - 700):
                        pos + 1500
                    ]
                })

        # --------------------------------
        # 結果
        # --------------------------------

        print("")
        print("=" * 60)
        print("重要な検索結果")
        print("=" * 60)

        print("件数:", len(results))

        for i, result in enumerate(results):

            print("")
            print("-" * 60)
            print("RESULT", i + 1)
            print("-" * 60)

            print("FILE:")
            print(result["file"])

            print("")
            print("KEYWORD:")
            print(result["keyword"])

            print("")
            print("SNIPPET:")
            print(result["snippet"])

        print("")
        print("=" * 60)
        print("調査終了")
        print("=" * 60)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
