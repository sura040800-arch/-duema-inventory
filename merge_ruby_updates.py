"""Merge ruby-only updates onto the latest cards.json without overwriting card metadata."""
import json
import sys

SOURCE = sys.argv[1]
TARGET = sys.argv[2]
FIELDS = ("card_ruby", "ruby_checked", "ruby_source", "ruby_attempted_at")
PROTECTED = {"dmwiki", "official", "manual", "identity", "existing"}

with open(SOURCE, encoding="utf-8") as f:
    source_cards = json.load(f)
with open(TARGET, encoding="utf-8") as f:
    target_cards = json.load(f)

source_by_id = {str(c.get("id")): c for c in source_cards if c.get("id") is not None}
updated = 0
for card in target_cards:
    cid = card.get("id")
    src = source_by_id.get(str(cid)) if cid is not None else None
    if not src or not src.get("ruby_attempted_at"):
        continue
    current_source = card.get("ruby_source")
    if current_source in PROTECTED:
        continue
    old_stamp = card.get("ruby_attempted_at") or ""
    new_stamp = src.get("ruby_attempted_at") or ""
    if new_stamp >= old_stamp:
        for field in FIELDS:
            if field in src:
                card[field] = src[field]
        updated += 1

tmp = TARGET + ".merge.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(target_cards, f, ensure_ascii=False, indent=2)
import os
os.replace(tmp, TARGET)
print(f"最新cards.jsonへルビ情報を統合: {updated}枚")
