#!/usr/bin/env python3
"""pumaair.ir category crawler (WooCommerce Store API).

  python3 categories.py        # writes output/categories.json (flat) + output/categories_tree.json
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

SITE = "https://pumaair.ir"
API = f"{SITE}/wp-json/wc/store/v1/products/categories"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36"
OUT_DIR = Path("output")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # same rule as api categories.schemas.ts

# Hand-picked latin slugs for categories whose source slug is Persian.
SLUG_OVERRIDES = {
    "ابزار-بادی-روکول": "rocol-air-tools",
    "ابزار-شارژی-روکول": "rocol-cordless-tools",
}

# Fallback for any other Persian slug: plain letter-by-letter transliteration.
FA = dict(zip("ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهیيكآأإءئؤة",
              ["a", "b", "p", "t", "s", "j", "ch", "h", "kh", "d", "z", "r", "z", "zh", "s", "sh", "s", "z", "t", "z",
               "a", "gh", "f", "gh", "k", "g", "l", "m", "n", "v", "h", "y", "y", "k", "a", "a", "e", "", "y", "o", "h"]))


def get(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r), int(r.headers.get("X-WP-TotalPages") or 1)
        except Exception as e:
            if attempt == 3:
                raise
            print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)


def to_slug(raw):
    s = urllib.parse.unquote(raw).lower()
    if s in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[s], True
    if SLUG_RE.match(s):
        return s, False
    s = "".join(FA.get(ch, ch) for ch in s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s, True


def fetch_all():
    cats, page, pages = [], 1, 1
    while page <= pages:
        items, pages = get(f"{API}?per_page=100&page={page}")
        cats += items
        page += 1
    return cats


def main():
    raw = fetch_all()
    byid = {c["id"]: c for c in raw}

    def depth(c):
        d = 0
        while c["parent"] in byid:
            c, d = byid[c["parent"]], d + 1
        return d

    flat = []
    for i, c in enumerate(raw):
        slug, generated = to_slug(c["slug"])
        parent = byid.get(c["parent"])
        flat.append({
            "sourceId": c["id"],
            "title": unescape(c["name"]).strip(),
            "slug": slug,
            "slugGenerated": generated,
            "sourceSlug": urllib.parse.unquote(c["slug"]),
            "parentSourceId": parent["id"] if parent else None,
            "parentSlug": to_slug(parent["slug"])[0] if parent else None,
            "depth": depth(c),
            "sortOrder": i,
            "productCount": c["count"],
            "description": re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", c.get("description") or ""))).strip() or None,
            "imageUrl": (c.get("image") or {}).get("src"),
            "url": c["permalink"],
        })
    # Parents before children, so an importer can create them in order.
    flat.sort(key=lambda c: (c["depth"], c["sortOrder"]))

    nodes = {c["sourceId"]: {**c, "children": []} for c in flat}
    tree = []
    for c in flat:
        (nodes[c["parentSourceId"]]["children"] if c["parentSourceId"] in nodes else tree).append(nodes[c["sourceId"]])

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "categories.json").write_text(json.dumps(flat, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "categories_tree.json").write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")

    def show(ns, ind=0):
        for n in ns:
            flag = "  (slug generated)" if n["slugGenerated"] else ""
            print(f"{'  ' * ind}- {n['title']}  [{n['slug']}]  {n['productCount']}{flag}")
            show(n["children"], ind + 1)
    show(tree)
    print(f"\n{len(flat)} categories ({len(tree)} top-level) -> output/categories.json, output/categories_tree.json", file=sys.stderr)


if __name__ == "__main__":
    main()
