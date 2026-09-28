import asyncio
from playwright.async_api import async_playwright


BASE_URL = "https://dm.takaratomy.co.jp/card/"


async def get_card_ids(page):
    links = await page.locator('a[href*="/card/detail/?id="]').evaluate_all(
        """
        els => els.map(e => {
            const href = e.getAttribute('href') || '';
            const m = href.match(/[?&]id=([^&]+)/);
            return m ? m[1] : null;
        }).filter(Boolean)
        """
    )

    # 重複削除
    return list(dict.fromkeys(links))


async def show_page(page, page_number):
    print("")
    print("=" * 60)
    print(f"ページ {page_number} を確認中")
    print("=" * 60)

    ids = await get_card_ids(page)

    print(f"取得URL数: {len(ids)}")
    print("先頭5枚:")

    for card_id in ids[:5]:
        print("  ", card_id)

    return ids


async def main():
    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        page = await browser.new_page()

        print("公式カード検索を開いています...")
        await page.goto(
            BASE_URL,
            wait_until="domcontentloaded",
            timeout=120000
        )

        await page.wait_for_timeout(5000)

        # ページ1
        page1_ids = await show_page(page, 1)

        if not page1_ids:
            print("ERROR: ページ1のカードが取得できませんでした")
            await browser.close()
            return

        # ページ2
        print("")
        print("ページ2へ移動します...")

        selector = 'a[data-page="2"]:visible'

        count = await page.locator(selector).count()

        print(f'ページ2ボタン数: {count}')

        if count == 0:
            print("ERROR: ページ2ボタンが見つかりません")
            await browser.close()
            return

        await page.locator(selector).first.click(
            force=True,
            timeout=30000
        )

        await page.wait_for_timeout(5000)

        page2_ids = await show_page(page, 2)

        # ページ3
        print("")
        print("ページ3へ移動します...")

        selector = 'a[data-page="3"]:visible'

        count = await page.locator(selector).count()

        print(f'ページ3ボタン数: {count}')

        if count == 0:
            print("ERROR: ページ3ボタンが見つかりません")
            await browser.close()
            return

        await page.locator(selector).first.click(
            force=True,
            timeout=30000
        )

        await page.wait_for_timeout(5000)

        page3_ids = await show_page(page, 3)

        # 比較
        print("")
        print("=" * 60)
        print("結果確認")
        print("=" * 60)

        print(f"ページ1: {len(page1_ids)}枚")
        print(f"ページ2: {len(page2_ids)}枚")
        print(f"ページ3: {len(page3_ids)}枚")

        overlap12 = set(page1_ids) & set(page2_ids)
        overlap23 = set(page2_ids) & set(page3_ids)

        print(f"1→2 重複: {len(overlap12)}枚")
        print(f"2→3 重複: {len(overlap23)}枚")

        if (
            len(page1_ids) >= 40
            and len(page2_ids) >= 40
            and len(page3_ids) >= 40
            and len(overlap12) == 0
            and len(overlap23) == 0
        ):
            print("")
            print("★ 成功 ★")
            print("ページ1・2・3で別々のカードを取得できています！")
        else:
            print("")
            print("★ 失敗 ★")
            print("ページ移動後もカードが変わっていません。")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
