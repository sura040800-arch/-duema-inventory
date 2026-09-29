import requests
import re

URL = "https://dm.takaratomy.co.jp/common/js/search.js"

print("search.jsを取得中...", flush=True)

js = requests.get(
    URL,
    timeout=60,
    headers={
        "User-Agent": "Mozilla/5.0"
    }
).text

print("取得完了:", len(js), "文字", flush=True)


# 改行を入れて見やすくする
js_pretty = js.replace(";", ";\n")


patterns = [
    r".{0,1000}data-page.{0,3000}",
    r".{0,1000}pagenum.{0,3000}",
    r".{0,1000}nextpostslink.{0,3000}",
    r".{0,1000}\.page.{0,3000}",
    r".{0,1000}pageNum.{0,3000}",
    r".{0,1000}location\.href.{0,3000}",
]


found = 0


for pattern in patterns:

    matches = re.findall(
        pattern,
        js_pretty,
        re.IGNORECASE | re.DOTALL
    )

    for match in matches[:5]:

        found += 1

        print(
            "\n" + "=" * 80,
            flush=True
        )

        print(
            "PAGE処理候補",
            flush=True
        )

        print(
            "=" * 80,
            flush=True
        )

        print(
            match,
            flush=True
        )


print(
    "\n" + "=" * 80,
    flush=True
)

print(
    "候補:",
    found,
    flush=True
)

print(
    "=" * 80,
    flush=True
)
