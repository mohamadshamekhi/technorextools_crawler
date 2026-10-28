#!/usr/bin/env python3
"""Import output/brands.json (from brands.py) into the Technorex API, logos included.

  ABZAR_TOKEN=... python3 import_brands.py --dry-run     # show plan, write nothing
  ABZAR_TOKEN=... python3 import_brands.py               # create missing brands + upload missing logos
  ABZAR_TOKEN=... python3 import_brands.py --replace     # also swap logos of brands that already have one

1. POST /backoffice/brands/import — creates brands by slug; existing ones are left as they are.
2. Per brand with a logo: POST /backoffice/media/upload (ownerType=BRAND, purpose=LOGO), then
   DELETE the brand's previous LOGO media when replacing.
Needs brands.manage + media.manage. Re-running is safe. The token (env ABZAR_TOKEN) is never printed.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from import_categories import DEFAULT_BASE, DELAY, Api, read_token
from import_category_images import multipart

SRC = Path("output/brands.json")
RESULT = Path("output/brands_import_result.json")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace", action="store_true", help="overwrite logos of brands that already have one")
    args = ap.parse_args()

    api = Api(args.base, read_token(), perms="brands.manage / media.manage")
    brands = json.loads(SRC.read_text(encoding="utf-8"))

    report = api.call("POST", "/brands/import", {
        "source": "pumaair.ir",
        "dryRun": args.dry_run,
        "brands": [{"title": b["title"], "slug": b["slug"]} for b in brands],
    })
    rows = {r["slug"]: r for r in report["items"]}
    print(f"brands: created={report['created']} updated={report['updated']} "
          f"unchanged={report['unchanged']} failed={report['failed']}", file=sys.stderr)

    results, counts = [], {"uploaded": 0, "skipped": 0, "none": 0, "failed": 0}
    for b in brands:
        row = rows.get(b["slug"], {})
        res = {"slug": b["slug"], "title": b["title"], "brand": row.get("status"),
               "brandId": row.get("brandId"), "logo": None, "logoUrl": None, "error": row.get("error")}
        try:
            if res["error"]:
                res["logo"] = "failed"
            elif not b.get("logo"):
                res["logo"] = "none"
            else:
                old = []
                if res["brandId"]:
                    media = api.call("GET", f"/media?ownerType=BRAND&ownerId={res['brandId']}")
                    old = [m for m in media if m["purpose"] == "LOGO"]
                if old and not args.replace:
                    res["logo"], res["logoUrl"] = "skipped", old[0]["url"]
                else:
                    if not args.dry_run:
                        content = (Path("output") / b["logo"]).read_bytes()
                        body, mp_type = multipart({
                            "ownerType": "BRAND", "ownerId": res["brandId"], "purpose": "LOGO",
                            "isMain": "true", "folder": "brands", "alt": b["title"],
                        }, f"{b['slug']}.png", content, "image/png")
                        res["logoUrl"] = api.call("POST", "/media/upload", raw=body, content_type=mp_type)["url"]
                        for m in old:
                            api.call("DELETE", f"/media/{m['id']}")
                        time.sleep(DELAY)
                    res["logo"] = "uploaded"
        except Exception as ex:
            res["logo"], res["error"] = "failed", str(ex)
        counts[res["logo"]] += 1
        print(f"  {res['brand'] or '-':<9} logo={res['logo']:<8} {b['title']} [{b['slug']}]  {res['error'] or ''}",
              file=sys.stderr)
        results.append(res)

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"\n{prefix}logos: " + " ".join(f"{k}={v}" for k, v in counts.items()), file=sys.stderr)
    if not args.dry_run:
        RESULT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"result -> {RESULT}", file=sys.stderr)


if __name__ == "__main__":
    main()
