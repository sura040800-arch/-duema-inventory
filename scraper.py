from playwright.sync_api import sync_playwright


URL = "https://dm.takaratomy.co.jp/card/"


with sync_playwright() as p:

    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    print("公式ページを開いています...", flush=True)

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=120000
    )

    page.wait_for_timeout(5000)

    print()
    print("==============================")
    print("ページ情報")
    print("==============================")

    # ページネーションを探す
    elements = page.locator(
        "#cardlist .wp-pagenavi a"
    )

    count = elements.count()

    print(
        "ページリンク数:",
        count,
        flush=True
    )

    for i in range(count):

        el = elements.nth(i)

        print()
        print("LINK", i)

        print(
            el.evaluate(
                "(e) => e.outerHTML"
            )
        )

    print()
    print("==============================")
    print("data-page確認")
    print("==============================")

    data_pages = page.locator(
        "[data-page]"
    )

    count = data_pages.count()

    print(
        "data-page数:",
        count,
        flush=True
    )

    for i in range(
        min(count, 30)
    ):

        el = data_pages.nth(i)

        print(
            el.evaluate(
                """e => ({
                    tag: e.tagName,
                    text: e.innerText,
                    page: e.getAttribute("data-page"),
                    href: e.getAttribute("href"),
                    className: e.className
                })"""
            )
        )

    print()
    print("==============================")
    print("フォーム確認")
    print("==============================")

    form = page.locator(
        "#search_cond"
    )

    print(
        "フォーム数:",
        form.count()
    )

    if form.count():

        print(
            form.evaluate(
                "(e) => e.outerHTML"
            )[:10000]
        )

    print()
    print("==============================")
    print("完了")
    print("==============================")

    browser.close()
