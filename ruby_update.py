"""既存カードの機械生成ルビをDM Wikiで再照合する専用ジョブ。"""
import json
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import scraper

CARDS_FILE = os.path.join("data", "cards.json")
BATCH_SIZE = 1000


def main():
    # 固有名の実ルビがWikiから取得できるかを毎回確認し、取得元の障害を早期検知する。
    smoke_reading = scraper.fetch_wiki_reading("“龍装”チュリス")
    print(f"Wikiルビ動作確認: {smoke_reading or '取得できず'}", flush=True)

    with open(CARDS_FILE, "r", encoding="utf-8") as f:
        cards = json.load(f)
    if not isinstance(cards, list):
        raise RuntimeError("cards.jsonが配列形式ではありません")

    groups = {}
    for card in cards:
        name = scraper.clean_card_name(card.get("name", ""))
        if name:
            groups.setdefault(name, []).append(card)

    now = datetime.now(timezone.utc)
    candidates = []
    for name, group in groups.items():
        if any(
            c.get("card_ruby")
            and c.get("ruby_source") not in ("generated", "fallback", "not_found")
            for c in group
        ):
            continue
        if not any(scraper.ruby_attempt_is_recent(c, now) for c in group):
            candidates.append(name)

    candidates = sorted(candidates)[:BATCH_SIZE]
    print(f"ルビ再照合対象: {len(candidates)}種類 / 全{len(groups)}種類", flush=True)
    results = {}
    if candidates:
        with ThreadPoolExecutor(max_workers=scraper.WIKI_MAX_WORKERS) as pool:
            futures = {
                pool.submit(scraper.fetch_wiki_reading, name): name
                for name in candidates
            }
            for i, future in enumerate(as_completed(futures), 1):
                name = futures[future]
                try:
                    results[name] = future.result() or ""
                except Exception as exc:
                    print(f"Wiki取得失敗 {name}: {exc}", flush=True)
                    results[name] = ""
                if i % 50 == 0 or i == len(futures):
                    found = sum(bool(v) for v in results.values())
                    print(f"ルビ照合: {i}/{len(futures)} / Wiki確定{found}", flush=True)

    stamp = now.isoformat(timespec="seconds")
    for name, reading in results.items():
        for card in groups[name]:
            card["ruby_attempted_at"] = stamp
            if reading:
                card["card_ruby"] = reading
                card["ruby_checked"] = True
                card["ruby_source"] = "dmwiki"
            else:
                fallback = scraper.generate_fallback_reading(name)
                if fallback:
                    card["card_ruby"] = fallback
                    card["ruby_checked"] = True
                    card["ruby_source"] = "generated"
                else:
                    card["ruby_checked"] = False
                    card["ruby_source"] = "not_found"

    tmp = CARDS_FILE + ".ruby.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CARDS_FILE)

    print(f"Wiki確定ルビ: {sum(bool(v) for v in results.values())}/{len(results)}種類", flush=True)
    print("ルビ再照合完了", flush=True)


if __name__ == "__main__":
    main()
