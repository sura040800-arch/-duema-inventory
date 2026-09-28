import asyncio
from playwright.async_api import async_playwright


BASE_URL = "https://dm.takaratomy.co.jp/card/"


async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("=" * 70)
        print("公式カード検索 JavaScript 絞り込み調査")
        print("=" * 70)

        await page.goto(
            BASE_URL,
            wait_until="domcontentloaded",
            timeout=120000
        )

        await page.wait_for_timeout(7000)

        # ----------------------------------------
        # 公式ドメインのJSだけ取得
        # ----------------------------------------

        scripts = await page.locator(
            'script[src]'
        ).evaluate_all(
            """
            els => els
                .map(e => e.src)
                .filter(src =>
                    src.startsWith("https://dm.takaratomy.co.jp/")
                )
            """
        )

        scripts = list(dict.fromkeys(scripts))

        print("")
        print("公式ドメインJS:", len(scripts), "個")

        # ----------------------------------------
        # 検索する単語
        # ----------------------------------------

        keywords = [
            "data-page",
            "pagenum",
            "ajax",
            "pagination",
            "card-list",
            "card_list",
            "page_num",
            "search"
        ]

        results = []

        # ----------------------------------------
        # JSを調査
        # ----------------------------------------

        for src in scripts:

            try:

                response = await page.request.get(src)

                if not response.ok:
                    continue

                text = await response.text()

                for keyword in keywords:

                    pos = 0
                    found = 0

                    while True:

                        index = text.find(
                            keyword,
                            pos
                        )

                        if index == -1:
                            break

                        start = max(
                            0,
                            index - 350
                        )

                        end = min(
                            len(text),
                            index + 700
                        )

                        snippet = text[start:end]

                        results.append({
                            "file": src,
                            "keyword": keyword,
                            "snippet": snippet
                        })

                        pos = index + len(keyword)

                        found += 1

                        # 同じJSの同じ単語は最大2件
                        if found >= 2:
                            break

            except Exception:
                continue

        # ----------------------------------------
        # インラインJSも調査
        # ----------------------------------------

        inline_scripts = await page.locator(
            "script:not([src])"
        ).evaluate_all(
            """
            els => els
                .map(e => e.textContent || "")
                .filter(x => x.trim().length > 0)
            """
        )

        for number, text in enumerate(inline_scripts):

            for keyword in keywords:

                index = text.find(keyword)

                if index != -1:

                    results.append({
                        "file": "INLINE_" + str(number),
                        "keyword": keyword,
                        "snippet": text[
                            max(0, index - 350):
                            index + 700
                        ]
                    })

        # ----------------------------------------
        # 結果
        # ----------------------------------------

        print("")
        print("=" * 70)
        print("検索結果")
        print("=" * 70)

        print("該当:", len(results), "件")

        # 最大30件だけ表示
        for i, result in enumerate(results[:30]):

            print("")
            print("-" * 70)
            print("RESULT", i + 1)
            print("-" * 70)

            print("FILE:")
            print(result["file"])

            print("")
            print("KEYWORD:")
            print(result["keyword"])

            print("")
            print("SNIPPET:")
            print(result["snippet"])

        print("")
        print("=" * 70)
        print("調査終了")
        print("=" * 70)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
