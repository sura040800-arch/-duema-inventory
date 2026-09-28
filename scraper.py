import asyncio
from playwright.async_api import async_playwright


BASE_URL = "https://dm.takaratomy.co.jp/card/"


async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=True)

        page = await browser.new_page()

        print("=" * 70)
        print("公式サイト JavaScript 調査")
        print("=" * 70)

        await page.goto(
            BASE_URL,
            wait_until="domcontentloaded",
            timeout=120000
        )

        await page.wait_for_timeout(7000)

        print("")
        print("ページ読み込み完了")
        print("URL:", page.url)

        # ----------------------------------------
        # JavaScriptファイル一覧
        # ----------------------------------------

        scripts = await page.locator("script[src]").evaluate_all(
            """
            els => els.map(e => e.src).filter(Boolean)
            """
        )

        scripts = list(dict.fromkeys(scripts))

        print("")
        print("=" * 70)
        print("JavaScriptファイル")
        print("=" * 70)

        print("総数:", len(scripts))

        for i, src in enumerate(scripts):
            print(i, src)

        # ----------------------------------------
        # JavaScriptの中からページ送り関連を探す
        # ----------------------------------------

        print("")
        print("=" * 70)
        print("ページ送り関連JavaScriptを検索")
        print("=" * 70)

        results = await page.evaluate(
            """
            async (scripts) => {

                const keywords = [
                    "data-page",
                    "pagenum",
                    "ajax",
                    "XMLHttpRequest",
                    "fetch(",
                    "pagination",
                    "page_num",
                    "card-list"
                ];

                const results = [];

                for (const src of scripts) {

                    try {

                        const response = await fetch(src);

                        if (!response.ok) {
                            continue;
                        }

                        const text = await response.text();

                        for (const keyword of keywords) {

                            let start = 0;
                            let count = 0;

                            while (true) {

                                const pos =
                                    text.indexOf(
                                        keyword,
                                        start
                                    );

                                if (pos === -1) {
                                    break;
                                }

                                const from =
                                    Math.max(
                                        0,
                                        pos - 500
                                    );

                                const to =
                                    Math.min(
                                        text.length,
                                        pos + 1000
                                    );

                                results.push({
                                    src: src,
                                    keyword: keyword,
                                    snippet: text.slice(
                                        from,
                                        to
                                    )
                                });

                                start =
                                    pos + keyword.length;

                                count++;

                                // 同じファイルの同じキーワードを
                                // 最大3件まで
                                if (count >= 3) {
                                    break;
                                }
                            }
                        }

                    } catch (e) {

                        results.push({
                            src: src,
                            keyword: "FETCH_ERROR",
                            snippet: String(e)
                        });
                    }
                }

                return results;
            }
            """,
            scripts
        )

        print("")
        print("検索結果:", len(results), "件")

        # ----------------------------------------
        # 結果表示
        # ----------------------------------------

        for i, result in enumerate(results):

            print("")
            print("-" * 70)
            print("RESULT", i + 1)
            print("-" * 70)

            print("FILE:")
            print(result["src"])

            print("")
            print("KEYWORD:")
            print(result["keyword"])

            print("")
            print("SNIPPET:")
            print(result["snippet"])

        # ----------------------------------------
        # インラインJavaScriptも調査
        # ----------------------------------------

        inline_results = await page.locator(
            "script:not([src])"
        ).evaluate_all(
            """
            els => els.map(e => e.textContent || "")
            """
        )

        print("")
        print("=" * 70)
        print("インラインJavaScript調査")
        print("=" * 70)

        for i, text in enumerate(inline_results):

            for keyword in [
                "data-page",
                "pagenum",
                "pagination"
            ]:

                pos = text.find(keyword)

                if pos != -1:

                    print("")
                    print("INLINE", i)
                    print("KEYWORD:", keyword)

                    print(
                        text[
                            max(0, pos - 500):
                            pos + 1500
                        ]
                    )

        print("")
        print("=" * 70)
        print("調査終了")
        print("=" * 70)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
