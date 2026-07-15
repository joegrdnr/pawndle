#!/usr/bin/env python3
"""
merge.py — merge fetched fragments (out/*.json) into items.json.

- Keeps everything already in items.json
- Dedupes by id (existing items win)
- Writes the public file WITHOUT listingUrl and a private backup WITH it
- Reports per-category counts and which category is today's daily

Usage:
  python3 scripts/merge.py                 # merge all out/*.json
  python3 scripts/merge.py --fresh         # discard old items.json first
  python3 scripts/merge.py --drop cooking clothes   # remove categories
"""
import argparse
import datetime
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS = os.path.join(ROOT, "items.json")
OUT_GLOB = os.path.join(ROOT, "out", "*.json")
BACKUP = os.path.join(ROOT, "out", "backup-with-urls.json")
MIN_ITEMS = 20

def load_existing():
    if not os.path.exists(ITEMS):
        return {"minPriceGap": 5}, []
    with open(ITEMS) as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"minPriceGap": 5}, data
    return data.get("settings", {"minPriceGap": 5}), data.get("items", [])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="ignore existing items.json")
    ap.add_argument("--drop", nargs="*", default=[], help="categories to remove")
    args = ap.parse_args()

    settings, items = ({"minPriceGap": 5}, []) if args.fresh else load_existing()
    ids = {i["id"] for i in items}

    added = 0
    for path in sorted(glob.glob(OUT_GLOB)):
        if os.path.basename(path) == os.path.basename(BACKUP):
            continue
        with open(path) as f:
            frag = json.load(f)
        for item in frag:
            if item["id"] in ids:
                continue
            ids.add(item["id"])
            items.append(item)
            added += 1
        print(f"merged {path}")

    if args.drop:
        before = len(items)
        items = [i for i in items if i["category"] not in args.drop]
        print(f"dropped {before - len(items)} items from categories: {', '.join(args.drop)}")

    # private backup keeps listingUrl
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with open(BACKUP, "w") as f:
        json.dump({"settings": settings, "items": items}, f, indent=2)

    # public file strips it
    public = [{k: v for k, v in i.items() if k != "listingUrl"} for i in items]
    with open(ITEMS, "w") as f:
        json.dump({"settings": settings, "items": public}, f, indent=2)

    cats = sorted({i["category"] for i in items})
    print(f"\n+{added} new, {len(items)} total")
    for c in cats:
        n = sum(1 for i in items if i["category"] == c)
        flag = "" if n >= MIN_ITEMS else f"  <- NOT PLAYABLE ({n}/{MIN_ITEMS})"
        print(f"  {c}: {n}{flag}")

    # today's daily, matching the game's UTC-date math
    today = datetime.date.today()
    day_num = (today - datetime.date(1970, 1, 1)).days
    if cats:
        daily = cats[day_num % len(cats)]
        print(f"\ntoday's ({today}) daily category: {daily}")
        for offset in range(1, 4):
            d = today + datetime.timedelta(days=offset)
            dn = (d - datetime.date(1970, 1, 1)).days
            print(f"  {d}: {cats[dn % len(cats)]}")
    print(f"\npublic file:  {ITEMS}")
    print(f"private file: {BACKUP}  (has listing urls — do not commit)")

if __name__ == "__main__":
    main()
