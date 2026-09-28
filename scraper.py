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
    "\nJavaScript:",
    len(scripts),
    "個\n",
    flush=True
)


words = [
    "data-page",
    "nextpostslink",
    "pagenum",
    "pagination",
    "ajax",
    "page/"
]


found = False


for i, script in enumerate(scripts, 1):

    src = script.get("src")

    if not src:
        continue

    js_url = urljoin(
        URL,
        src
    )

    try:

        print(
            f"[{i}/{len(scripts)}] {js_url}",
            flush=True
        )

        js = requests.get(
            js_url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        ).text

    except Exception as e:

        print(
            "取得失敗:",
            e,
            flush=True
        )

        continue


    for word in words:

        if word not in js:
            continue

        found = True

        print(
            "\n========================================",
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
            "========================================",
            flush=True
        )


        start = 0

        count = 0

        while True:

            pos = js.find(
                word,
                start
            )

            if pos == -1:
                break

            count += 1

            print(
                "\n--- 発見", count, "---",
                flush=True
            )

            print(
                js[
                    max(0, pos - 1000):
                    min(len(js), pos + 3000)
                ],
                flush=True
            )

            start = pos + len(word)

            if count >= 5:
                break


print(
    "\n========================================",
    flush=True
)

if found:

    print(
        "ページ切り替え関連のJavaScriptが見つかりました。",
        flush=True
    )

else:

    print(
        "関連文字列が見つかりませんでした。",
        flush=True
    )

print(
    "========================================",
    flush=True
)
