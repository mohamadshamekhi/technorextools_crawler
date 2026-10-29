#!/usr/bin/env python3
"""Create category attributes on the Technorex API from category_specs.py's output.

Every category (matched by slug) gets one attribute group titled «ویژگی فنی و ظاهری» (created if missing),
holding one attribute per crawled spec: title, unit, inputType (number / boolean / text), sortOrder = position
in the source list.

  ABZAR_TOKEN=... python3 import_category_attributes.py --dry-run   # show plan, write nothing
  ABZAR_TOKEN=... python3 import_category_attributes.py

Only adds: an attribute already in the group (same title) is left exactly as an admin set it, nothing is
deleted, so re-running is safe. Needs categories.view + categories.manage. The token (env ABZAR_TOKEN) is
never printed.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from import_categories import DEFAULT_BASE, DELAY, Api, existing_by_slug, read_token

SRC = Path("output/category_specs.json")
RESULT = Path("output/category_attributes_result.json")
GROUP_TITLE = "ویژگی فنی و ظاهری"


def norm(title):
    return " ".join(title.replace("ي", "ی").replace("ك", "ک").replace("‌", " ").split())


def ensure_attributes(api, category_id, specs, dry_run):
    """Make sure the category's «ویژگی فنی و ظاهری» group holds an attribute per spec (add-only).

    Returns (group status, {normalized title: attribute}, created labels, existing titles). In a dry run the
    attributes that would be created are in the map with id None.
    """
    groups = api.call("GET", f"/categories/{category_id}/attribute-groups")
    group = next((g for g in groups if norm(g["title"]) == norm(GROUP_TITLE)), None)
    status = "existing" if group else "created"
    if not group:
        group = {"id": None, "attributes": []}
        if not dry_run:
            group = api.call("POST", f"/categories/{category_id}/attribute-groups", {"title": GROUP_TITLE})
            time.sleep(DELAY)
    attrs = {norm(a["title"]): a for a in group["attributes"]}
    created, existing = [], []
    for i, s in enumerate(specs):
        if norm(s["title"]) in attrs:
            existing.append(s["title"])
            continue
        body = {"title": s["title"], "unit": s["unit"], "inputType": s["inputType"], "options": [], "sortOrder": i}
        attr = {"id": None, **body}
        if not dry_run:
            attr = api.call("POST", f"/attribute-groups/{group['id']}/attributes", body)
            time.sleep(DELAY)
        attrs[norm(s["title"])] = attr
        created.append(s["title"] + (f" ({s['unit']})" if s["unit"] else ""))
    return status, attrs, created, existing


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--src", type=Path, default=SRC, help=f"specs file (default {SRC})")
    args = ap.parse_args()

    token = read_token()
    if not args.src.exists():
        sys.exit(f"{args.src} not found — run: python3 category_specs.py")
    specs = {e["slug"]: e for e in json.loads(args.src.read_text(encoding="utf-8"))}

    api = Api(args.base, token)
    cats = existing_by_slug(api)
    print(f"{len(cats)} categories on {args.base}, specs for {sum(1 for e in specs.values() if e['specs'])}",
          file=sys.stderr)

    results, counts = [], {"created": 0, "existing": 0, "categories": 0, "no_specs": 0, "failed": 0}
    for slug, cat in cats.items():
        entry = specs.get(slug)
        res = {"slug": slug, "title": cat["title"], "group": None, "created": [], "existing": [], "error": None}
        if not entry or not entry["specs"]:
            counts["no_specs"] += 1
            print(f"  -        {cat['title']} [{slug}]  no specs crawled", file=sys.stderr)
            continue
        try:
            res["group"], _, res["created"], res["existing"] = ensure_attributes(api, cat["id"], entry["specs"],
                                                                               args.dry_run)
            counts["categories"] += 1
        except Exception as ex:
            res["error"] = str(ex)
            counts["failed"] += 1
        counts["created"] += len(res["created"])
        counts["existing"] += len(res["existing"])
        status = "failed" if res["error"] else f"+{len(res['created'])} ={len(res['existing'])}"
        print(f"  {status:<8} {cat['title']} [{slug}]  group={res['group']}"
              f"{'  — ' + res['error'] if res['error'] else ''}", file=sys.stderr)
        for t in res["created"]:
            print(f"             + {t}", file=sys.stderr)
        results.append(res)

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"\n{prefix}" + " ".join(f"{k}={v}" for k, v in counts.items()), file=sys.stderr)
    if not args.dry_run:
        RESULT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"result -> {RESULT}", file=sys.stderr)


if __name__ == "__main__":
    main()
