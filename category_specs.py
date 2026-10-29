#!/usr/bin/env python3
"""pumaair.ir spec crawler: the technical-spec list of the first product of every category.

For each source category that has products, opens its first product (category-page order) and reads the
bullet list in its description («میزان برش استیل: 1.6 میلی متر», «وزن دستگاه 1.08kg», …) into key/value
pairs, then shapes each pair as one of *our* category attributes (title, unit, inputType — see the API's
createAttributeSchema). If the first product has no spec list, the next ones are tried (up to --tries).

  python3 category_specs.py                  # -> output/category_specs.json
  python3 category_specs.py --tries 10

Lines that aren't key/value (the product type, «کاربرد در …», the warranty sentence) are kept under
`skipped` so you can see what was left out. Keys our product already has a field for (brand) are dropped.
import_category_attributes.py turns the result into attributes on our API.
"""
import argparse
import json
import re
import sys
import urllib.error
from html import unescape
from pathlib import Path

from categories import SITE, fetch_all, get, to_slug

OUT = Path("output/category_specs.json")
PRODUCTS = f"{SITE}/wp-json/wc/store/v1/products"

# Keys that map to a dedicated product field on our side, not to an attribute.
SKIP_KEYS = {"برند", "نام برند", "برند محصول", "نام کالا", "نام محصول", "کد", "کد کالا", "کد محصول", "مشخصات",
             "مشخصات فنی", "قیمت"}
# Different wordings of one spec across products → one attribute per category.
ALIASES = {
    "مدل دستگاه": "مدل", "مدل محصول": "مدل", "شماره مدل": "مدل",
    "وزن": "وزن دستگاه", "وزن محصول": "وزن دستگاه", "طول": "طول دستگاه", "طول محصول": "طول دستگاه",
    "کشور تولید کننده": "کشور سازنده", "کشور سازنده محصول": "کشور سازنده", "ساخت": "کشور سازنده",
    "ساحت": "کشور سازنده", "مصرف باد": "میزان مصرف باد", "هوای مصرفی": "میزان مصرف باد",
    "مدت گارانتی": "گارانتی",
}
# Values that make a yes/no attribute.
BOOL_VALUES = {"دارد", "ندارد", "بله", "خیر", "دارای", "فاقد"}

FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789.")
PERSIAN = re.compile(r"[؀-ۿ]")
INCH = re.compile(r"اینچ|inch|\"|″|''", re.I)
NUM_UNIT = re.compile(r"^(\d+(?:\.\d+)?)\s*([^\d\s][^\d]{0,29})?$")
# «مدل AT-6112», «وزن دستگاه 1.08kg»: a Persian key, then a value with no Persian in it.
NO_COLON = re.compile(r"^([؀-ۿ‌ ]{2,40}?)\s+([0-9A-Za-z][^؀-ۿ]*)$")


def clean(text):
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    text = text.replace("ي", "ی").replace("ك", "ک").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip(" \t-–—•·*")


def spec_lines(html):
    """The description's list items; falls back to <br>/<p>/newline-separated lines."""
    items = re.findall(r"<li[^>]*>(.*?)</li>", html or "", flags=re.S | re.I)
    if not items:
        items = re.split(r"<br\s*/?>|</p>|</div>|\n", html or "", flags=re.I)
    return [line for line in (clean(i) for i in items) if line]


def split_pair(line):
    """(key, value) or None for a line that isn't a key/value spec."""
    for sep in (":", "："):
        if sep in line:
            key, value = (p.strip() for p in line.split(sep, 1))
            if key and value and len(key) <= 40 and len(value) <= 80:  # longer = a prose sentence
                return key, value
            return None
    m = NO_COLON.match(line)
    return (m.group(1).strip(), m.group(2).strip()) if m else None


def to_attribute(key, value):
    """Our attribute shape for one spec pair: number+unit when the value is «1.6 میلی متر» / «5000BPM»."""
    v = value.translate(FA_DIGITS).strip()
    if not INCH.search(v):
        v = re.sub(r"(\d)/(\d)", r"\1.\2", v)  # Persian decimal slash: «6/3psi» = 6.3 (not inch fractions)
    m = NUM_UNIT.match(v)
    if m:
        return {"inputType": "number", "unit": (m.group(2) or "").strip() or None, "sample": m.group(1)}
    if v in BOOL_VALUES:
        return {"inputType": "boolean", "unit": None, "sample": v}
    return {"inputType": "text", "unit": None, "sample": v}


def parse_specs(html):
    specs, skipped, seen = [], [], set()
    for line in spec_lines(html):
        pair = split_pair(line)
        if not pair:
            skipped.append(line)
            continue
        key, value = pair
        key = ALIASES.get(key, key)
        if key in SKIP_KEYS or key in seen:
            skipped.append(line)
            continue
        seen.add(key)
        specs.append({"title": key[:120], "value": value, **to_attribute(key, value)})
    return specs, skipped


ORDER = ["&orderby=menu_order&order=asc"]  # emptied once the site rejects it


def first_products(category_id, tries):
    """Products in category-page order (menu_order), falling back to the API default if unsupported."""
    url = f"{PRODUCTS}?category={category_id}&per_page={tries}"
    if ORDER:
        try:
            return get(url + ORDER[0])[0]
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            ORDER.clear()
    return get(url)[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tries", type=int, default=5, help="products to try per category when one has no spec list")
    args = ap.parse_args()

    cats = [c for c in fetch_all() if c.get("count")]
    print(f"{len(cats)} categories with products", file=sys.stderr)
    out = []
    for c in cats:
        slug, _ = to_slug(c["slug"])
        title = clean(c["name"])
        entry = {"slug": slug, "title": title, "sourceId": c["id"], "product": None, "specs": [], "skipped": []}
        try:
            for p in first_products(c["id"], args.tries):
                best = max((parse_specs(p.get(f) or "") for f in ("short_description", "description")),
                           key=lambda r: len(r[0]))
                if len(best[0]) >= 2:
                    entry["product"] = {"name": clean(p["name"]), "url": p.get("permalink")}
                    entry["specs"], entry["skipped"] = best
                    break
        except Exception as e:  # one bad category must not stop the crawl
            entry["error"] = str(e)
        out.append(entry)
        status = f"{len(entry['specs'])} specs from {entry['product']['name']}" if entry["product"] else \
            entry.get("error") or "no spec list found"
        print(f"  {title} [{slug}]: {status}", file=sys.stderr)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    found = sum(1 for e in out if e["specs"])
    print(f"\n{found}/{len(out)} categories with specs -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
