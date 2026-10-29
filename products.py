#!/usr/bin/env python3
"""pumaair.ir product crawler (WooCommerce Store API).

  python3 products.py                                     # every product of every category
  python3 products.py --limit 3                           # a test run: the first 3 products
  python3 products.py --product saw-perpendicular-at-6112 # one product by its source slug
  python3 products.py --category air-saw --limit 5        # one category (source or our slug)

Writes output/products.json — one row per product (a product listed in several categories appears once):
  title, slug (latin, see categories.py), sku, price (Toman; null = «تماس بگیرید»), inStock, stockQty,
  categories (our slugs, most specific last), tags, images (source URLs, main first), shortDesc / description
  (plain text; our admin edits them in a textarea), specs (key/value parsed like category_specs.py).
import_products.py puts them on our API.
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
from html import unescape
from pathlib import Path

from categories import SITE, fetch_all, get, to_slug
from category_specs import ORDER, clean, parse_specs

OUT = Path("output/products.json")
PRODUCTS = f"{SITE}/wp-json/wc/store/v1/products"
SHORT_MAX = 500  # createProductSchema.shortDesc


def html_to_text(html):
    """Readable plain text: list items become «• …» lines, blocks are separated by a blank line."""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html or "", flags=re.S | re.I)
    s = re.sub(r"<li[^>]*>", "\n• ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|h[1-6]|ul|ol|table|tr)>", "\n\n", s, flags=re.I)
    s = unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ").replace("ي", "ی").replace("ك", "ک")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in s.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def short_text(html):
    text = html_to_text(html)
    if len(text) <= SHORT_MAX:
        return text or None
    cut = text[:SHORT_MAX]
    return cut[:cut.rfind("\n")].strip() if "\n" in cut else cut[:SHORT_MAX - 1] + "…"


def toman(prices, key):
    """Store API prices are strings in minor units of the shop currency; Rial is converted to Toman."""
    raw = (prices or {}).get(key)
    if raw in (None, "", "0"):
        return None
    value = int(raw) / 10 ** int(prices.get("currency_minor_unit") or 0)
    if (prices.get("currency_code") or "").upper() == "IRR":
        value /= 10
    return int(round(value))


def merged_specs(product):
    """Spec pairs from the short description, then any extra ones the full description adds."""
    specs, skipped = parse_specs(product.get("short_description") or "")
    more, more_skipped = parse_specs(product.get("description") or "")
    seen = {s["title"] for s in specs}
    specs += [s for s in more if s["title"] not in seen]
    return specs, skipped + [line for line in more_skipped if len(line) <= 120]


def to_row(p):
    slug, _ = to_slug(p["slug"])
    specs, skipped = merged_specs(p)
    low = p.get("low_stock_remaining")
    return {
        "sourceId": p["id"],
        "url": p.get("permalink"),
        "title": clean(p["name"]),
        "slug": slug,
        "sku": (p.get("sku") or "").strip() or None,
        "price": toman(p.get("prices"), "price"),
        "regularPrice": toman(p.get("prices"), "regular_price"),
        "inStock": bool(p.get("is_in_stock")),
        "stockQty": int(low) if isinstance(low, int) else None,
        "categories": [to_slug(c["slug"])[0] for c in p.get("categories") or []],
        "tags": [to_slug(t["slug"])[0] for t in p.get("tags") or []],
        "brands": [to_slug(b["slug"])[0] for b in p.get("brands") or []],
        "images": [i["src"] for i in p.get("images") or [] if i.get("src")],
        "shortDesc": short_text(p.get("short_description")),
        "description": html_to_text(p.get("description")) or None,
        "specs": specs,
        "skipped": skipped,
    }


def category_products(category_id):
    page, pages = 1, 1
    while page <= pages:
        url = f"{PRODUCTS}?category={category_id}&per_page=100&page={page}"
        try:
            items, pages = get(url + (ORDER[0] if ORDER else ""))
        except urllib.error.HTTPError as e:
            if e.code != 400 or not ORDER:
                raise
            ORDER.clear()  # site doesn't accept menu_order: use its default order
            items, pages = get(url)
        yield from items
        page += 1
        time.sleep(0.3)  # be gentle with pumaair.ir


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="stop after this many products (test runs)")
    ap.add_argument("--product", help="only this product (source slug, as in its URL)")
    ap.add_argument("--category", help="only this category (source slug or our slug)")
    args = ap.parse_args()

    rows, seen = [], set()
    if args.product:
        slug = urllib.parse.unquote(args.product.rstrip("/").rsplit("/", 1)[-1])  # a full URL works too
        items, _ = get(f"{PRODUCTS}?slug={urllib.parse.quote(slug)}")
        if not items:
            sys.exit(f"product {args.product} not found on {SITE}")
        rows.append(to_row(items[0]))
    else:
        cats = [c for c in fetch_all() if c.get("count")]
        if args.category:
            cats = [c for c in cats if args.category in (c["slug"], to_slug(c["slug"])[0])]
            if not cats:
                sys.exit(f"category {args.category} not found (or empty) on {SITE}")
        for c in cats:
            print(f"{clean(c['name'])} ({c['count']})", file=sys.stderr)
            for p in category_products(c["id"]):
                if p["id"] in seen:
                    continue
                seen.add(p["id"])
                rows.append(to_row(p))
                if args.limit and len(rows) >= args.limit:
                    break
            if args.limit and len(rows) >= args.limit:
                break

    for r in rows:
        price = f"{r['price']:,} T" if r["price"] else "no price"
        print(f"  {r['title']} [{r['slug']}]  sku={r['sku']}  {price}  "
              f"{'in stock' if r['inStock'] else 'out of stock'}  specs={len(r['specs'])} images={len(r['images'])}",
              file=sys.stderr)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(rows)} products -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
