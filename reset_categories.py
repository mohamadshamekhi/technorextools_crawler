#!/usr/bin/env python3
"""Delete EVERY category on the Technorex API (children first), with its images.

  ABZAR_TOKEN=... python3 reset_categories.py --dry-run     # list what would go, and what is blocked
  ABZAR_TOKEN=... python3 reset_categories.py --yes         # really delete

The API refuses (409) to delete a category that still has products — those, and their ancestors, are
reported as blocked and kept; move or delete the products first. Each deleted category's media rows
(ownerType=CATEGORY) are deleted too, so no orphan images are left in storage.
Needs categories.view, categories.manage, media.manage. The token (env ABZAR_TOKEN) is never printed.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from import_categories import DEFAULT_BASE, DELAY, Api, read_token

RESULT = Path("output/categories_reset_result.json")


def all_categories(api):
    """Flat list with productsCount (the paged list has counts, the tree doesn't)."""
    out, skip = [], 0
    while True:
        page = api.call("GET", f"/categories?skip={skip}&take=100")
        out += page["items"]
        skip += len(page["items"])
        if not page["items"] or skip >= page["total"]:
            return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="confirm: really delete every category")
    args = ap.parse_args()
    if not args.dry_run and not args.yes:
        sys.exit("this deletes every category — re-run with --dry-run to preview or --yes to confirm")

    api = Api(args.base, read_token(), perms="categories.view / categories.manage / media.manage")
    cats = {c["id"]: c for c in all_categories(api)}
    print(f"{len(cats)} categories on {args.base}", file=sys.stderr)

    def depth(c):
        d = 0
        while c["parentId"] in cats:
            c, d = cats[c["parentId"]], d + 1
        return d

    # children first; a blocked category blocks every ancestor
    blocked, results, counts = set(), [], {"deleted": 0, "blocked": 0, "failed": 0}
    for c in sorted(cats.values(), key=depth, reverse=True):
        res = {"id": c["id"], "slug": c["slug"], "title": c["title"], "status": None, "media": 0, "error": None}
        try:
            if c["id"] in blocked:
                res["status"], res["error"] = "blocked", "has a blocked sub-category"
            elif c["productsCount"]:
                res["status"], res["error"] = "blocked", f"{c['productsCount']} products attached"
            else:
                media = api.call("GET", f"/media?ownerType=CATEGORY&ownerId={c['id']}")
                res["media"] = len(media)
                if not args.dry_run:
                    api.call("DELETE", f"/categories/{c['id']}")
                    for m in media:
                        api.call("DELETE", f"/media/{m['id']}")
                    time.sleep(DELAY)
                res["status"] = "deleted"
        except Exception as ex:
            res["status"], res["error"] = "failed", str(ex)
        if res["status"] != "deleted" and c["parentId"]:
            p = c["parentId"]
            while p in cats:
                blocked.add(p)
                p = cats[p]["parentId"]
        counts[res["status"]] += 1
        print(f"  {res['status']:<8} {'  ' * depth(c)}{c['title']} [{c['slug']}]  media={res['media']}"
              f"{'  — ' + res['error'] if res['error'] else ''}", file=sys.stderr)
        results.append(res)

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"\n{prefix}" + " ".join(f"{k}={v}" for k, v in counts.items()), file=sys.stderr)
    if not args.dry_run:
        RESULT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"result -> {RESULT}", file=sys.stderr)


if __name__ == "__main__":
    main()
