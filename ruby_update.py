"""既存カードの機械生成ルビをDM Wikiで再照合する専用ジョブ。"""
import json
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import scraper

CARDS_FILE = os.path.join("data", "cards.json")
RECHECK_MARKER = os.path.join("data", "ruby_recheck_started")
CURSOR_FILE = os.path.join("data", "ruby_recheck_cursor.json")
STATS_FILE = os.path.join("data", "ruby_recheck_stats.json")
BATCH_SIZE = 1000



def lookup_card_reading(name, group):
    """公式カード詳細の読みを最優先し、なければDM Wikiで確認する。"""
    for card in group:
        card_id = card.get("id")
        url = card.get("url")
        if card_id is None or not url:
            continue
        official = scraper.fetch_card((
            card_id, url, card.get("release_order", 0)
        ))
        if official:
            official_name = scraper.clean_card_name(official.get("name", ""))
            official_reading = official.get("card_ruby", "")
            if official_reading and official_name == scraper.clean_card_name(name):
                return official_reading, "official"
        # 公式詳細は代表の1版だけ確認し、負荷を抑えてWikiへ進む。
        break

    wiki_reading = scraper.fetch_wiki_reading(name)
    if wiki_reading:
        return wiki_reading, "dmwiki"
    return "", ""

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
    eligible_names = []
    source_counts = {}
    attempted_count = 0
    never_attempted_count = 0
    retry_due_count = 0
    eligible_card_count = 0
    due_names = []
    for name, group in groups.items():
        eligible = [
            card for card in group
            if not card.get("card_ruby")
            or card.get("ruby_source") in ("generated", "fallback", "not_found")
        ]
        if not eligible:
            continue
        eligible_names.append(name)
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
        if due:
            due_names.append(name)

    eligible_names.sort()
    due_names.sort()
    cursor_state = None
    if os.path.exists(CURSOR_FILE):
        with open(CURSOR_FILE, "r", encoding="utf-8") as f:
            cursor_state = json.load(f)
    catchup_active = not (cursor_state and cursor_state.get("complete"))
    if catchup_active:
        last_name = (cursor_state or {}).get("last_name", "")
        remaining = [name for name in eligible_names if name > last_name]
        candidates = remaining[:BATCH_SIZE]
        print(
            f"初回一括照合: 継続位置={last_name or '(先頭)'}, "
            f"残り={len(remaining)}種類",
            flush=True,
        )
    else:
        candidates = due_names[:BATCH_SIZE]
        print(f"定期再照合: 期限到来={len(due_names)}種類", flush=True)

    print(
        f"診断: 全カード={len(cards)}, ルビ対象カード={eligible_card_count}, "
        f"取得元={source_counts}, 取得試行日時あり={attempted_count}, "
        f"なし={never_attempted_count}, 再照合期限到来={retry_due_count}",
        flush=True,
    )
    print(f"ルビ再照合対象: {len(candidates)}種類 / 全{len(groups)}種類", flush=True)
    results = {}
    if candidates:
        with ThreadPoolExecutor(max_workers=scraper.WIKI_MAX_WORKERS) as pool:
            futures = {
                pool.submit(lookup_card_reading, name, groups[name]): name
                for name in candidates
            }
            for i, future in enumerate(as_completed(futures), 1):
                name = futures[future]
                try:
                    results[name] = future.result() or ("", "")
                except Exception as exc:
                    print(f"公式/Wiki読み取得失敗 {name}: {exc}", flush=True)
                    results[name] = ("", "")
                if i % 50 == 0 or i == len(futures):
                    found = sum(bool(v[0]) for v in results.values())
                    print(f"ルビ照合: {i}/{len(futures)} / 公式・Wiki確定{found}", flush=True)

    stamp = now.isoformat(timespec="seconds")
    official_confirmed_names = 0
    wiki_confirmed_names = 0
    fallback_names = 0
    not_found_names = 0
    affected_cards = 0
    for name, result in results.items():
        reading, reading_source = result
        targets = [
            card for card in groups[name]
            if not card.get("card_ruby")
            or card.get("ruby_source") in ("generated", "fallback", "not_found")
        ]
        affected_cards += len(targets)
        fallback = scraper.generate_fallback_reading(name) if not reading else ""
        if reading_source == "official":
            official_confirmed_names += 1
        elif reading_source == "dmwiki":
            wiki_confirmed_names += 1
        elif fallback:
            fallback_names += 1
        else:
            not_found_names += 1
        for card in targets:
            card["ruby_attempted_at"] = stamp
            if reading:
                card["card_ruby"] = reading
                card["ruby_checked"] = True
                card["ruby_source"] = reading_source
            elif fallback:
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

    os.makedirs(os.path.dirname(CURSOR_FILE), exist_ok=True)
    if catchup_active:
        if candidates and len(remaining) > len(candidates):
            cursor_state = {"last_name": candidates[-1], "complete": False}
        else:
            cursor_state = {
                "last_name": candidates[-1] if candidates else (cursor_state or {}).get("last_name", ""),
                "complete": True,
                "completed_at": stamp,
            }
        with open(CURSOR_FILE, "w", encoding="utf-8") as cursor:
            json.dump(cursor_state, cursor, ensure_ascii=False, indent=2)
        print(
            "初回一括照合の進捗: "
            + ("継続" if not cursor_state["complete"] else "全対象の処理完了"),
            flush=True,
        )

    remaining_name_count = (
        max(0, len(remaining) - len(candidates)) if catchup_active else None
    )
    completed_name_count = (
        len(eligible_names) - remaining_name_count
        if remaining_name_count is not None else None
    )
    stats = {
        "updated_at": stamp,
        "total_eligible_name_count": len(eligible_names),
        "completed_name_count": completed_name_count,
        "remaining_name_count": remaining_name_count,
        "batch_name_count": len(results),
        "official_confirmed_name_count": official_confirmed_names,
        "wiki_confirmed_name_count": wiki_confirmed_names,
        "fallback_name_count": fallback_names,
        "not_found_name_count": not_found_names,
        "affected_card_count": affected_cards,
        "cursor": cursor_state or {},
    }
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(
        f"今回の取得結果: 公式確定={official_confirmed_names}種類 / "
        f"Wiki確定={wiki_confirmed_names}種類 / "
        f"機械読み={fallback_names}種類 / 未取得={not_found_names}種類 / "
        f"更新対象カード={affected_cards}枚",
        flush=True,
    )
    print("ルビ再照合完了", flush=True)


if __name__ == "__main__":
    main()
