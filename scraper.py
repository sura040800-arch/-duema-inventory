from playwright.sync_api import sync_playwright
import json


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

    def on_request(request):

        if request.resource_type in ["xhr", "fetch"]:
            print("\n========== REQUEST ==========")
            print("METHOD :", request.method)
            print("URL    :", request.url)

            if request.post_data:
                print("POST   :", request.post_data)

    def on_response(response):

        if response.request.resource_type in ["xhr", "fetch"]:
            print("\n========== RESPONSE ==========")
            print("STATUS :", response.status)
            print("URL    :", response.url)

    page.on("request", on_request)
    page.on("response", on_response)

    # =========================
    # 公式ページ
    # =========================

    print("公式ページを開きます...", flush=True)

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(5000)

    print("\n========== BEFORE ==========")

    print("URL:", page.url)

    print(
        "カード数:",
        page.locator(
            'a[href*="/card/detail/"]'
        ).count()
    )

    # =========================
    # data-page=2
    # =========================

    target = page.locator(
        '[data-page="2"]'
    ).first

    print("\n========== TARGET ==========")

    if not target.count():

        print("data-page=2 が見つかりません")

    else:

        print(
            target.evaluate(
                """
                el => ({
                    outerHTML: el.outerHTML,
                    tag: el.tagName,
                    className: el.className,
                    href: el.getAttribute("href"),
                    onclick: el.getAttribute("onclick"),
                    dataPage: el.getAttribute("data-page"),
                    text: el.textContent
                })
                """
            )
        )

        # =========================
        # jQueryイベント調査
        # =========================

        print("\n========== EVENTS ==========")

        events = page.evaluate(
            """
            () => {

                const el =
                    document.querySelector(
                        '[data-page="2"]'
                    );

                if (!el) {
                    return null;
                }

                const result = {};

                if (
                    window.jQuery &&
                    window.jQuery._data
                ) {

                    const events =
                        window.jQuery._data(
                            el,
                            "events"
                        );

                    if (events) {

                        for (
                            const type in events
                        ) {

                            result[type] =
                                events[type].map(
                                    e => ({
                                        type: e.type,
                                        namespace:
                                            e.namespace || "",
                                        selector:
                                            e.selector || "",
                                        handler:
                                            e.handler
                                                ? String(
                                                    e.handler
                                                ).substring(
                                                    0,
                                                    1000
                                                )
                                                : ""
                                    })
                                );

                        }

                    }
                }

                return result;
            }
            """
        )

        print(
            json.dumps(
                events,
                ensure_ascii=False,
                indent=2
            )
        )

        # =========================
        # クリック
        # =========================

        print(
            "\n========== CLICK PAGE 2 ==========\n"
        )

        target.scroll_into_view_if_needed()

        target.click(
            force=True
        )

        print(
            "クリックしました",
            flush=True
        )

        # JS/AJAX待ち
        page.wait_for_timeout(8000)

        # =========================
        # AFTER
        # =========================

        print(
            "\n========== AFTER ==========\n"
        )

        print(
            "URL:",
            page.url,
            flush=True
        )

        print(
            "カード数:",
            page.locator(
                'a[href*="/card/detail/"]'
            ).count(),
            flush=True
        )

        print(
            "現在のdata-page:",
            page.evaluate(
                """
                () => {

                    const el =
                        document.querySelector(
                            '.current[data-page]'
                        );

                    return el
                        ? el.getAttribute("data-page")
                        : null;
                }
                """
            ),
            flush=True
        )

        # =========================
        # 現在のページャー
        # =========================

        print(
            "\n========== PAGER AFTER ==========\n"
        )

        print(
            page.locator(
                '[data-page]'
            ).evaluate_all(
                """
                els => els.map(
                    e => e.outerHTML
                )
                """
            )
        )

    browser.close()
