import json
import re
from urllib.parse import quote

from playwright.sync_api import sync_playwright


BASE = "https://dm.takaratomy.co.jp"
SEARCH = BASE + "/card/"


def make_url():

    state = {
        "suggest": "on",
        "keyword": "",
        "keyword_type": [
            "card_name",
            "card_ruby",
            "card_text",
            "race",
            "flavor",
            "illustrator"
        ],
        "culture_cond": [
            "単色",
            "多色"
        ],
        "pagenum": "1",
        "samename": "show",
        "sort": "release_new"
    }

    return (
        SEARCH
        + "?v="
        + quote(
            json.dumps(
                state,
                ensure_ascii=False,
                separators=(",", ":")
            )
        )
    )


with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=True
    )

    page = browser.new_page(
        viewport={
            "width": 1280,
            "height": 1000
        }
    )

    print("公式ページを開きます...", flush=True)

    page.goto(
        make_url(),
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(5000)

    print("\n========== PAGE INFO ==========\n")

    print(
        "URL:",
        page.url,
        flush=True
    )

    # -----------------------------------------------------
    # data-pageを全部調査
    # -----------------------------------------------------

    controls = page.locator(
        "[data-page]"
    )

    count = controls.count()

    print(
        "data-page elements:",
        count,
        flush=True
    )

    for i in range(
        min(count, 15)
    ):

        el = controls.nth(i)

        try:

            print(
                "\n--- CONTROL", i, "---",
                flush=True
            )

            print(
                el.evaluate(
                    "el => el.outerHTML"
                ),
                flush=True
            )

        except Exception as e:

            print(
                "ERROR:",
                e,
                flush=True
            )

    # -----------------------------------------------------
    # ページャー周辺HTML
    # -----------------------------------------------------

    print(
        "\n========== PAGER HTML ==========\n",
        flush=True
    )

    pager = page.locator(
        ".wp-pagenavi"
    )

    if pager.count():

        print(
            pager.first.evaluate(
                "el => el.outerHTML"
            ),
            flush=True
        )

    else:

        print(
            "wp-pagenavi が見つかりません",
            flush=True
        )

    # -----------------------------------------------------
    # script一覧
    # -----------------------------------------------------

    print(
        "\n========== SCRIPT SRC ==========\n",
        flush=True
    )

    scripts = page.locator(
        "script[src]"
    ).evaluate_all(
        """
        els => els.map(
            e => e.src
        )
        """
    )

    for src in scripts:

        print(
            src,
            flush=True
        )

    # -----------------------------------------------------
    # ページャー関連JS文字列を検索
    # -----------------------------------------------------

    print(
        "\n========== JS TEXT SEARCH ==========\n",
        flush=True
    )

    result = page.evaluate(
        """
        () => {

            const scripts =
                Array.from(
                    document.scripts
                );

            const words = [
                "nextpostslink",
                "data-page",
                "pagenum",
                "ajax",
                "pagination",
                "wp-pagenavi"
            ];

            const result = [];

            for (
                const script of scripts
            ) {

                if (!script.src &&
                    script.textContent) {

                    const text =
                        script.textContent;

                    for (
                        const word of words
                    ) {

                        if (
                            text.includes(word)
                        ) {

                            result.push({
                                word: word,
                                text:
                                    text.substring(
                                        Math.max(
                                            0,
                                            text.indexOf(word) - 500
                                        ),
                                        Math.min(
                                            text.length,
                                            text.indexOf(word) + 1500
                                        )
                                    )
                            });

                        }

                    }

                }

            }

            return result;
        }
        """
    )

    for item in result:

        print(
            "\nWORD:",
            item["word"],
            flush=True
        )

        print(
            item["text"],
            flush=True
        )

    print(
        "\n========== END ==========\n",
        flush=True
    )

    browser.close()
