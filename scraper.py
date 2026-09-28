import requests
from bs4 import BeautifulSoup

URL = "https://dm.takaratomy.co.jp/card/"

data = {
    "suggest": "on",
    "keyword_type[]": "card_name",
    "keyword_type[]": "card_ruby",
    "keyword_type[]": "card_text",
    "culture_cond[]": "水",
    "pagenum": "2",
    "samename": "show",
    "sort": "release_new",
}

print("=" * 60)
print("ページ2 POST取得テスト")
print("=" * 60)

r = requests.post(
    URL,
    data=data,
    timeout=60,
)

print("HTTP:", r.status_code)
print("URL:", r.url)
print("文字数:", len(r.text))

soup = BeautifulSoup(r.text, "html.parser")

cards = soup.select('a[href*="/card/detail/?id="]')

ids = []

for a in cards:
    href = a.get("href", "")
    if "?id=" in href:
        card_id = href.split("?id=", 1)[1].split("&", 1)[0]
        if card_id not in ids:
            ids.append(card_id)

print("")
print("取得カード数:", len(ids))

print("")
print("カードID:")
for card_id in ids[:20]:
    print(card_id)

print("")
print("=" * 60)
print("テスト終了")
print("=" * 60)
