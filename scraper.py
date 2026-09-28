import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


URL = "https://dm.takaratomy.co.jp/card/"


print("公式ページを取得中...", flush=True)

html = requests.get(
    URL,
    timeout=60,
    headers={
        "User-Agent": "Mozilla/5.0"
    }
).text

soup = BeautifulSoup(
    html,
    "html.parser"
)

scripts = soup.find_all(
    "script",
    src=True
)

print(
    "JavaScript:",
    len(scripts),
    "個",
    flush=True
)


# ページ切り替え調査に必要な文字だけ
words = [
    "data-page",
    "nextpostslink",
    "pagenum",
    "search_cond_add",
    "location.href",
    ".page"
]


found = 0


for i, script in enumerate(scripts, 1):

    src = script.get("src")

    if not src:
        continue

    js_url = urljoin(
        URL,
        src
    )

    try:

        js = requests.get(
            js_url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        ).text

    except Exception:
        continue


    # 関係ない外部JSは飛ばす
    if "dm.takaratomy.co.jp" not in js_url:
        continue


    for word in words:

        positions = []
        start = 0

        while True:

            pos = js.find(
                word,
                start
            )

            if pos == -1:
                break

            positions.append(pos)

            start = pos + len(word)

            if len(positions) >= 3:
                break


        for pos in positions:

            found += 1

            print(
                "\n"
                + "=" * 70,
                flush=True
            )

            print(
                "発見:",
                word,
                flush=True
            )

            print(
                "JS:",
                js_url,
                flush=True
            )

            print(
                "=" * 70,
                flush=True
            )

            snippet = js[
                max(0, pos - 1200):
                min(len(js), pos + 2500)
            ]

            print(
                snippet,
                flush=True
            )


print(
    "\n"
    + "=" * 70,
    flush=True
)

print(
    "重要部分:",
    found,
    "件",
    flush=True
)

print(
    "=" * 70,
    flush=True
)
