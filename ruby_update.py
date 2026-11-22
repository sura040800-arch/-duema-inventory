"""既存カードの機械生成ルビをDM Wikiで再照合する専用ジョブ。"""
import json
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import scraper

CARDS_FILE = os.path.join("data", "cards.json")
RECHECK_MARKER = os.path.join("data", "ruby_recheck_started")
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
    initial_batch = not os.path.exists(RECHECK_MARKER)
    candidates = []
    source_counts = {}
    attempted_count = 0
    never_attempted_count = 0
    retry_due_count = 0
    eligible_card_count = 0
    for name, group in groups.items():
        eligible = [
            c for c in group
            if not c.get("card_ruby")
            or c.get("ruby_source") in ("generated", "fallback", "not_found")
        ]
        if not eligible:
            continue
        eligible_card_count += len(eligible)
        due = False
        for card in eligible:
            source = card.get("ruby_source") or "(none)"
            source_counts[source] = source_counts.get(source, 0) + 1
            if card.get("ruby_attempted_at"):
                attempted_count += 1
            else:
                never_attempted_count += 1
            if not scraper.ruby_attempt_is_recent({**card, "ruby_source": "generated"}, now):
                retry_due_count += 1
                due = True
        if initial_batch or due:
            candidates.append(name)

    print(
        f"診断: 初回={initial_batch}, 全カード={len(cards)}, "
        f"ルビ対象カード={eligible_card_count}, 取得元={source_counts}, "
        f"取得試行日時あり={attempted_count}, なし={never_attempted_count}, "
        f"再照合期限到来={retry_due_count}",
        flush=True,
    )
    print(f"候補種類(上限適用前): {len(candidates)}", flush=True)
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
        targets = [
            card for card in groups[name]
            if not card.get("card_ruby")
            or card.get("ruby_source") in ("generated", "fallback", "not_found")
        ]
        for card in targets:
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
    os.makedirs(os.path.dirname(RECHECK_MARKER), exist_ok=True)
    with open(RECHECK_MARKER, "w", encoding="utf-8") as marker:
        marker.write("started\n")

    print(f"Wiki確定ルビ: {sum(bool(v) for v in results.values())}/{len(results)}種類", flush=True)
    print("ルビ再照合完了", flush=True)


if __name__ == "__main__":
    main()
