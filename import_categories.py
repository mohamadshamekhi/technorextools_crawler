#!/usr/bin/env python3
"""Import output/categories.json (from categories.py) into the Technorex API.

  ABZAR_TOKEN=... python3 import_categories.py --dry-run     # show plan, write nothing
  ABZAR_TOKEN=... python3 import_categories.py               # create missing categories
  ABZAR_TOKEN=... python3 import_categories.py --update      # also fix title/parent/order of existing ones
  ABZAR_TOKEN=... python3 import_categories.py --src output/menu_categories.json   # from menu_categories.py

Uses POST/PATCH /api/v1/backoffice/categories (needs categories.view + categories.manage).
Existing categories are matched by slug, so re-running is safe. The token (env ABZAR_TOKEN) is never printed.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://api.technorextools.com"
SRC = Path("output/categories.json")
RESULT = Path("output/categories_import_result.json")
DELAY = 0.4  # API limit is 120 req/min


class Api:
    def __init__(self, base, token, perms="categories.view / categories.manage"):
        self.base = base.rstrip("/") + "/api/v1/backoffice"
        self.token = token
        self.perms = perms

    def call(self, method, path, body=None, raw=None, content_type=None):
        data = raw if raw is not None else json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if data:
            headers["Content-Type"] = content_type or "application/json"
        for attempt in range(4):
            req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                if e.code == 401:
                    sys.exit("401: token expired or invalid — get a fresh one and re-run (already-imported rows are skipped)")
                if e.code == 403:
                    sys.exit(f"403: this user lacks {self.perms}")
                if e.code == 429 or e.code >= 500:
                    print(f"    HTTP {e.code}, retry {attempt + 1}", file=sys.stderr)
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError(f"HTTP {e.code}: {detail[:500]}")
            except urllib.error.URLError as e:
                print(f"    network error {e.reason}, retry {attempt + 1}", file=sys.stderr)
                time.sleep(2 ** (attempt + 1))
        raise RuntimeError("gave up after retries")


def read_token():
    token = (os.environ.get("ABZAR_TOKEN") or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        sys.exit("set ABZAR_TOKEN (admin access token)")
    if not token.isascii() or token.count(".") != 2:
        sys.exit("ABZAR_TOKEN doesn't look like a JWT — replace the placeholder with the real access token")
    return token


def existing_by_slug(api):
    out = {}

    def walk(nodes, parent_id):
        for n in nodes:
            out[n["slug"]] = {**n, "parentId": parent_id}
            walk(n["children"], n["id"])
    walk(api.call("GET", "/categories/tree"), None)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--update", action="store_true", help="PATCH existing categories whose title/parent/order differ")
    ap.add_argument("--src", type=Path, default=SRC, help=f"categories file (default {SRC})")
    args = ap.parse_args()

    token = read_token()
    if not args.src.exists():
        sys.exit(f"{args.src} not found — run: python3 categories.py (or menu_categories.py)")

    cats = json.loads(args.src.read_text(encoding="utf-8"))
    cats.sort(key=lambda c: (c["depth"], c["sortOrder"]))  # parents first

    # sortOrder = position among siblings, as on the source site
    sibling_idx = {}
    for c in sorted(cats, key=lambda c: c["sortOrder"]):
        k = c["parentSlug"]
        c["_order"] = sibling_idx[k] = sibling_idx.get(k, -1) + 1

    api = Api(args.base, token)
    existing = existing_by_slug(api)
    print(f"{len(existing)} categories already on {args.base}", file=sys.stderr)

    ids = {s: e["id"] for s, e in existing.items()}
    results, counts = [], {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    for c in cats:
        slug, parent_slug = c["slug"], c["parentSlug"]
        parent_id = ids.get(parent_slug) if parent_slug else None
        label = f"{'  ' * c['depth']}{c['title']} [{slug}]"
        res = {"slug": slug, "title": c["title"], "sourceId": c["sourceId"], "id": None, "status": None, "error": None}
        try:
            if parent_slug and not parent_id and not args.dry_run:
                raise RuntimeError(f"parent {parent_slug} missing")
            if slug in existing:
                e = existing[slug]
                res["id"] = e["id"]
                diff = {}
                if e["title"] != c["title"]:
                    diff["title"] = c["title"]
                if e["parentId"] != parent_id and (parent_id or not parent_slug):
                    diff["parentId"] = parent_id
                if e["sortOrder"] != c["_order"]:
                    diff["sortOrder"] = c["_order"]
                if diff and args.update:
                    if not args.dry_run:
                        api.call("PATCH", f"/categories/{e['id']}", diff)
                        time.sleep(DELAY)
                    res["status"] = "updated"
                else:
                    res["status"] = "unchanged"
                    if diff:
                        res["error"] = f"differs ({', '.join(diff)}); use --update"
            else:
                body = {"title": c["title"], "slug": slug, "sortOrder": c["_order"], "isActive": True}
                if parent_id:
                    body["parentId"] = parent_id
                if not args.dry_run:
                    created = api.call("POST", "/categories", body)
                    ids[slug] = res["id"] = created["id"]
                    time.sleep(DELAY)
                else:
                    ids[slug] = f"<new:{slug}>"
                res["status"] = "created"
        except Exception as ex:
            res["status"], res["error"] = "failed", str(ex)
        counts[res["status"]] += 1
        note = f"  — {res['error']}" if res["error"] else ""
        print(f"  {res['status']:<9} {label}{note}", file=sys.stderr)
        results.append(res)

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"\n{prefix}created={counts['created']} updated={counts['updated']} "
          f"unchanged={counts['unchanged']} failed={counts['failed']}", file=sys.stderr)
    if not args.dry_run:
        RESULT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"result -> {RESULT}", file=sys.stderr)


if __name__ == "__main__":
    main()
