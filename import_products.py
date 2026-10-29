#!/usr/bin/env python3
"""Put the products of output/products.json (from products.py) on the Technorex API.

  ABZAR_TOKEN=... python3 import_products.py --dry-run     # show plan, write nothing
  ABZAR_TOKEN=... python3 import_products.py
  ABZAR_TOKEN=... python3 import_products.py --update      # also refresh price/text/specs of existing ones

Per product:
  1. POST /products — category = the most specific of its categories that exists on our side (run the
     category import first), brand = the first of its brands/tags that is one of our brands (by slug),
     basePrice = the current selling price. No price on the source («تماس بگیرید») → price 0 and inactive.
  2. POST /products/:id/variants — one variant: the source SKU (or one derived from the slug if it's missing,
     not latin, or taken), stock = the source quantity if shown, else --default-stock when in stock, else 0.
  3. Specs → the category's «ویژگی فنی و ظاهری» attributes (missing ones are added, as
     import_category_attributes.py does) → PUT /products/:id/attribute-values.
  4. Images → POST /media/upload (PRODUCT / GALLERY), the first one main.
A product that already exists (same slug) only gets what it is missing (variant, specs, images), so a run that
stopped half-way can simply be re-run. Needs products.manage, categories.manage, media.manage. The token (env
ABZAR_TOKEN) is never printed.
"""
import argparse
import json
import mimetypes
import re
import sys
import time
import urllib.parse
from pathlib import Path

from import_categories import DEFAULT_BASE, DELAY, Api, existing_by_slug, read_token
from import_category_attributes import ensure_attributes, norm
from import_category_images import http_get, multipart
from category_specs import to_attribute

SRC = Path("output/products.json")
RESULT = Path("output/products_import_result.json")
SKU_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")  # createVariantSchema.sku


def fallback_sku(slug):
    return ("PA-" + slug.upper())[:64].rstrip("-")


def find_product(api, slug):
    page = api.call("GET", f"/products?search={urllib.parse.quote(slug)}&take=100")
    hit = next((p for p in page["items"] if p["slug"] == slug), None)
    return api.call("GET", f"/products/{hit['id']}") if hit else None


def brand_in_title(title, brands):
    """«پرچ بادی هیدرولیک MTT مدل AT-6015» has no brand tag: find our brand's slug or name as a word in the title."""
    words = set(re.findall(r"[\w\u0600-\u06FF]+", title.lower()))
    return next((b for b in brands.values() if b["slug"].lower() in words or b["title"].lower() in words), None)


def pick_category(row, cats):
    """The deepest of the product's categories that exists on our side."""
    def depth(c):
        d = 0
        while c["parentId"]:
            c, d = next((x for x in cats.values() if x["id"] == c["parentId"]), {"parentId": None}), d + 1
        return d
    found = [cats[s] for s in row["categories"] if s in cats]
    return max(found, key=depth) if found else None


def weight_grams(row):
    """«وزن دستگاه: 1.08kg» → 1080, for the variant's shipping weight."""
    for s in row["specs"]:
        if "وزن" not in s["title"]:
            continue
        a = to_attribute(s["title"], s["value"])
        unit = (a["unit"] or "").lower().replace(" ", "")
        if a["inputType"] == "number" and unit in ("kg", "کیلوگرم", "کیلو", "g", "gr", "گرم"):
            return int(round(float(a["sample"]) * (1000 if unit in ("kg", "کیلوگرم", "کیلو") else 1)))
    return None


def attribute_values(row, attrs):
    values, used = [], set()
    for s in row["specs"]:
        a = attrs.get(norm(s["title"]))
        if not a or not a.get("id") or a["id"] in used:  # the API takes each attribute once
            continue
        used.add(a["id"])
        parsed = to_attribute(s["title"], s["value"])
        number = a["inputType"] == "number" and parsed["inputType"] == "number"
        values.append({"attributeId": a["id"], "value": (parsed["sample"] if number else s["value"])[:500]})
    return values


def upload_images(api, product_id, row):
    urls = []
    for i, src in enumerate(row["images"]):
        content, ctype = http_get(src)
        if not ctype.startswith("image/"):
            raise RuntimeError(f"not an image ({ctype}): {src}")
        name = urllib.parse.unquote(src.rsplit("/", 1)[-1])
        ext = Path(name).suffix or mimetypes.guess_extension(ctype) or ".jpg"
        body, mp_type = multipart({
            "ownerType": "PRODUCT", "ownerId": product_id, "purpose": "GALLERY", "isMain": str(i == 0).lower(),
            "sortOrder": str(i), "folder": "products", "alt": row["title"],
        }, f"{row['slug']}-{i + 1}{ext}", content, ctype)
        urls.append(api.call("POST", "/media/upload", raw=body, content_type=mp_type)["url"])
        time.sleep(DELAY)
    return urls


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--update", action="store_true", help="refresh price, texts and specs of existing products")
    ap.add_argument("--default-stock", type=int, default=10,
                    help="stock for an in-stock product whose quantity the source doesn't show (default 10)")
    ap.add_argument("--src", type=Path, default=SRC, help=f"products file (default {SRC})")
    args = ap.parse_args()

    token = read_token()
    if not args.src.exists():
        sys.exit(f"{args.src} not found — run: python3 products.py")
    rows = json.loads(args.src.read_text(encoding="utf-8"))

    api = Api(args.base, token, perms="products.manage / categories.manage / media.manage")
    cats = existing_by_slug(api)
    brands = {b["slug"]: b for b in api.call("GET", "/brands")}
    print(f"{len(rows)} products to import into {args.base} "
          f"({len(cats)} categories, {len(brands)} brands there)", file=sys.stderr)

    results, counts = [], {"created": 0, "completed": 0, "unchanged": 0, "failed": 0}
    attr_cache = {}
    for row in rows:
        res = {"slug": row["slug"], "title": row["title"], "status": None, "id": None, "category": None,
               "brand": None, "done": [], "error": None}
        try:
            cat = pick_category(row, cats)
            if not cat:
                raise RuntimeError(f"none of its categories {row['categories']} is on the API — import categories first")
            res["category"] = cat["slug"]
            brand = next((brands[s] for s in row["brands"] + row["tags"] if s in brands), None) or brand_in_title(
                row["title"], brands)
            res["brand"] = brand["slug"] if brand else None

            fields = {
                "title": row["title"][:200], "categoryId": cat["id"], "brandId": brand["id"] if brand else None,
                "shortDesc": row["shortDesc"], "description": (row["description"] or "")[:50000] or None,
                "basePrice": row["price"] or 0, "isActive": row["price"] is not None,
            }
            product = find_product(api, row["slug"])
            if product:
                res["status"] = "unchanged"
                if args.update:
                    if not args.dry_run:
                        api.call("PATCH", f"/products/{product['id']}", fields)
                    res["done"].append("fields")
            else:
                res["status"] = "created"
                product = {"id": None, "variants": [], "attributeValues": [], "images": []}
                if not args.dry_run:
                    product = api.call("POST", "/products", {**fields, "slug": row["slug"],
                                                             "isAmazingDeal": False, "isFeatured": False})
                    time.sleep(DELAY)
                res["done"].append("product")
            res["id"] = product["id"]
            if not row["price"]:
                res["error"] = "no price on the source — created inactive with price 0"

            if not product["variants"]:
                stock = row["stockQty"] if row["stockQty"] is not None else args.default_stock if row["inStock"] else 0
                sku = row["sku"] if row["sku"] and SKU_RE.match(row["sku"]) else fallback_sku(row["slug"])
                body = {"sku": sku, "colorName": None, "stockQty": stock, "priceOverride": None,
                        "weightGrams": weight_grams(row), "isActive": True}
                if not args.dry_run:
                    try:
                        api.call("POST", f"/products/{product['id']}/variants", body)
                    except RuntimeError as ex:
                        if "409" not in str(ex) or sku == fallback_sku(row["slug"]):
                            raise
                        body["sku"] = fallback_sku(row["slug"])  # source SKU already used by another product
                        api.call("POST", f"/products/{product['id']}/variants", body)
                    time.sleep(DELAY)
                res["done"].append(f"variant sku={body['sku']} stock={stock}")

            if row["specs"] and (not product["attributeValues"] or args.update):
                if cat["id"] not in attr_cache:
                    attr_cache[cat["id"]] = ensure_attributes(api, cat["id"], [], args.dry_run)[1]
                attrs = attr_cache[cat["id"]]
                missing = [s for s in row["specs"] if norm(s["title"]) not in attrs]
                if missing:
                    _, attrs, created, _ = ensure_attributes(api, cat["id"], missing, args.dry_run)
                    attr_cache[cat["id"]].update(attrs)
                    res["done"].append(f"new attributes: {', '.join(created)}")
                values = attribute_values(row, attr_cache[cat["id"]])
                if not args.dry_run and values:
                    api.call("PUT", f"/products/{product['id']}/attribute-values", {"values": values})
                    time.sleep(DELAY)
                res["done"].append(f"specs={len(values) if not args.dry_run else len(row['specs'])}")

            if row["images"] and not product["images"]:
                if not args.dry_run:
                    upload_images(api, product["id"], row)
                res["done"].append(f"images={len(row['images'])}")

            if res["status"] == "unchanged" and res["done"]:
                res["status"] = "completed"
        except Exception as ex:
            res["status"], res["error"] = "failed", str(ex)
        counts[res["status"]] += 1
        print(f"  {res['status']:<9} {row['title']} [{row['slug']}]  category={res['category']} brand={res['brand']}"
              f"{'  — ' + res['error'] if res['error'] else ''}", file=sys.stderr)
        if res["done"]:
            print(f"            {' · '.join(res['done'])}", file=sys.stderr)
        results.append(res)

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"\n{prefix}" + " ".join(f"{k}={v}" for k, v in counts.items()), file=sys.stderr)
    if not args.dry_run:
        RESULT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"result -> {RESULT}", file=sys.stderr)


if __name__ == "__main__":
    main()
