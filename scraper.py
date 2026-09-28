import json
import os
import time
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

URL = "https://dm.takaratomy.co.jp/card/"
OUTPUT = "data/card_ids.json"
MAX_PAGES = 600

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Referer": URL,
})


def get_page(page_number):

    data = [
        ("suggest", "on"),
        ("keyword_type[]", "card_name"),
        ("keyword_type[]", "card_ruby"),
        ("keyword_type[]", "card_text"),
        ("pagenum", str(page_number)),
        ("samename", "show"),
        ("sort", "release_new"),
    ]

    for attempt in range(3):

        try:

            response = session.post(
                URL,
                data=data,
                timeout=60,
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            ids = []

            for a in soup.select(
                'a[href*="/card/detail/?id="]'
            ):

                href = a.get("href", "")

                query = parse_qs(
                    urlparse(href).query
                )

                card_id = query.get(
                    "id",
                    [""]
                )[0]

                if card_id and card_id not in ids:
                    ids.append(card_id)

            return ids

        except requests.RequestException as e:

            print(
                f"ページ{page_number} エラー: {e}",
                flush=True
            )

            time.sleep(3)

    raise RuntimeError(
        f"ページ{page_number}を取得できませんでした"
    )


def main():

    print("=" * 60)
    print("公式カードIDの全ページ取得を開始")
    print("=" * 60)

    all_ids = []
    seen = set()

    for page in range(1, MAX_PAGES + 1):

        ids = get_page(page)

        if not ids:

            print(
                f"ページ{page}: カードなし",
                flush=True
            )

            break

        new_ids = [
            card_id
            for card_id in ids
            if card_id not in seen
        ]

        if not new_ids:

            print(
                f"ページ{page}: 新規IDなし",
                flush=True
            )

            break

        all_ids.extend(new_ids)
        seen.update(new_ids)

        print(
            f"ページ{page}: "
            f"{len(ids)}件 / "
            f"新規{len(new_ids)}件 / "
            f"累計{len(all_ids)}件",
            flush=True
        )

        time.sleep(0.2)

    os.makedirs("data", exist_ok=True)

    with open(
        OUTPUT,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            all_ids,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("=" * 60)
    print("取得終了")
    print("カードID合計:", len(all_ids))
    print("保存先:", OUTPUT)
    print("=" * 60)


if __name__ == "__main__":
    main()
