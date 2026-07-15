#!/usr/bin/env python3
"""
fetch_tcg.py — pull Pokémon cards with market prices + card images
from the free Pokémon TCG API (pokemontcg.io) into Pawndle format.

Usage:
  python3 scripts/fetch_tcg.py            # ~60 cards spread across price bands
  python3 scripts/fetch_tcg.py --count 100

Optional: set POKEMONTCG_API_KEY env var (free key from dev.pokemontcg.io)
for much higher rate limits. Works without one, just slower.

Writes:
  out/tcg_items.json   (fragment for merge.py)
  images/tcg-<cardid>.png
Prices are TCGplayer USD market prices; soldDate is the price-updated date.
"""
import argparse
import json
import os
import random
import re
import sys
import time
import urllib.request

API = "https://api.pokemontcg.io/v2/cards"
CATEGORY = "pokemon"
# price bands (USD) — sampling across these guarantees interesting pairs
BANDS = [(1, 3), (3, 8), (8, 20), (20, 50), (50, 150), (150, 100000)]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(ROOT, "images")
OUT_DIR = os.path.join(ROOT, "out")

def http_get(url, headers=None, retries=3):
    req = urllib.request.Request(url, headers=headers or {})
    req.add_header("User-Agent", "Pawndle/1.0 (personal price-guessing game)")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 5 * (attempt + 1)
            print(f"  retrying in {wait}s ({e})")
            time.sleep(wait)

def fetch_pages(pages):
    headers = {}
    key = os.environ.get("POKEMONTCG_API_KEY")
    if key:
        headers["X-Api-Key"] = key
    cards = []
    for page in range(1, pages + 1):
        url = (f"{API}?page={page}&pageSize=250&orderBy=-set.releaseDate"
               f"&select=id,name,number,rarity,set,images,tcgplayer")
        print(f"fetching page {page}…")
        data = json.loads(http_get(url, headers))
        got = data.get("data", [])
        cards.extend(got)
        if len(got) < 250:
            break
        time.sleep(1.5 if key else 8)  # be polite without a key
    return cards

def market_price(card):
    """Best USD market price across the card's printings, or None."""
    prices = (card.get("tcgplayer") or {}).get("prices") or {}
    best = None
    for variant in prices.values():
        m = (variant or {}).get("market")
        if m and m >= 1:
            best = max(best or 0, m)
    return best

def to_iso(d):
    # tcgplayer updatedAt looks like "2026/07/14"
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", d or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else time.strftime("%Y-%m-%d")

def build_title(card):
    s = card.get("set") or {}
    bits = [card.get("name", "Unknown card")]
    setname = s.get("name")
    if setname:
        bits.append(f"— {setname}")
    num, total = card.get("number"), s.get("printedTotal")
    if num and total:
        bits.append(f"({num}/{total})")
    if card.get("rarity"):
        bits.append(card["rarity"].lower())
    return " ".join(bits)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=60, help="target number of cards")
    ap.add_argument("--pages", type=int, default=3, help="API pages to sample from (250 cards each)")
    ap.add_argument("--seed", type=int, default=None, help="random seed for repeatable sampling")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    os.makedirs(IMG_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    cards = fetch_pages(args.pages)
    print(f"got {len(cards)} cards; filtering for priced ones…")

    priced = []
    for c in cards:
        p = market_price(c)
        img = (c.get("images") or {}).get("large") or (c.get("images") or {}).get("small")
        if p and img:
            priced.append((c, p, img))
    print(f"{len(priced)} cards have a USD market price and an image")

    # sample evenly across bands
    per_band = max(1, args.count // len(BANDS))
    chosen = []
    for lo, hi in BANDS:
        pool = [x for x in priced if lo <= x[1] < hi]
        rng.shuffle(pool)
        take = pool[:per_band]
        chosen.extend(take)
        print(f"  band ${lo}–{hi}: {len(pool)} available, took {len(take)}")
    rng.shuffle(chosen)
    chosen = chosen[:args.count]

    items = []
    for i, (card, price, img_url) in enumerate(chosen, 1):
        cid = re.sub(r"[^a-zA-Z0-9-]", "", card["id"])
        fname = f"tcg-{cid}.png"
        fpath = os.path.join(IMG_DIR, fname)
        if not os.path.exists(fpath):
            print(f"[{i}/{len(chosen)}] image {fname}")
            try:
                with open(fpath, "wb") as f:
                    f.write(http_get(img_url))
            except Exception as e:
                print(f"  skipped (image failed: {e})")
                continue
            time.sleep(0.5)
        items.append({
            "id": f"tcg-{cid}",
            "title": build_title(card),
            "category": CATEGORY,
            "image": fname,
            "soldPrice": round(price, 2),
            "currency": "USD",
            "soldDate": to_iso((card.get("tcgplayer") or {}).get("updatedAt")),
            "condition": "near mint",
            "saleType": "buy-it-now",
            "shippingIncluded": False,
            "isLot": False,
            "listingUrl": (card.get("tcgplayer") or {}).get("url", "")
        })

    out = os.path.join(OUT_DIR, "tcg_items.json")
    with open(out, "w") as f:
        json.dump(items, f, indent=2)
    print(f"\nwrote {len(items)} items -> {out}")
    if len(items) < 20:
        print("WARNING: under 20 items — the category won't be playable yet. "
              "Re-run with more --pages or --count.")
        sys.exit(1)

if __name__ == "__main__":
    main()
