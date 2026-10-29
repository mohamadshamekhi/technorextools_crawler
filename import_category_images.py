#!/usr/bin/env python3
"""Give every imported category an image on the Technorex API.

Image per category, best first: its menu icon (output/category_icons/, from menu_categories.py),
its own image on pumaair.ir, then — pumaair.ir has almost none — the main image of its most popular
product there. Use --only-real to skip that last fallback.

  ABZAR_TOKEN=... python3 import_category_images.py --dry-run
  ABZAR_TOKEN=... python3 import_category_images.py
  ABZAR_TOKEN=... python3 import_category_images.py --replace     # also overwrite existing images
  ABZAR_TOKEN=... python3 import_category_images.py --src output/menu_categories.json

Per category: download image from pumaair.ir -> POST /backoffice/media/upload
(ownerType=CATEGORY, purpose=COVER) -> PATCH /backoffice/categories/:id { imageUrl }.
Needs categories.view, categories.manage, media.manage.
"""
import argparse
import json
import mimetypes
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from import_categories import DEFAULT_BASE, DELAY, SRC, Api, existing_by_slug, read_token

STORE = "https://pumaair.ir/wp-json/wc/store/v1/products"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36"
RESULT = Path("output/category_images_result.json")


def http_get(url):
    url = urllib.parse.quote(url, safe=":/?&=%#,")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://pumaair.ir/"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), r.headers.get_content_type()


def source_images(cat, only_real):
    """Candidate (url or local file, origin) pairs, best first: menu icon, own image, top product's image."""
    if cat.get("icon"):
        yield Path("output") / cat["icon"], "menu icon"
    if cat.get("imageUrl"):
        yield cat["imageUrl"], "category"
    if only_real or not cat.get("sourceId"):
        return
    raw, _ = http_get(f"{STORE}?category={cat['sourceId']}&per_page=1&orderby=popularity&order=desc")
    items = json.loads(raw)
    if items and items[0]["images"]:
        yield items[0]["images"][0]["src"], f"product: {items[0]['name']}"


def download(cat, only_real):
    """First candidate image that actually downloads -> (url, origin, bytes, content type)."""
    err = None
    for src, origin in source_images(cat, only_real):
        try:
            if isinstance(src, Path):
                return src.name, origin, src.read_bytes(), mimetypes.guess_type(src.name)[0] or "image/png"
            content, ctype = http_get(src)
            if ctype.startswith("image/"):
                return src, origin, content, ctype
            err = f"not an image ({ctype})"
        except Exception as ex:
            err = f"{ex} ({origin})"
    if err:
        raise RuntimeError(err)
    return None


def multipart(fields, filename, content, ctype):
    boundary = uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    out += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n").encode() + content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return out, f"multipart/form-data; boundary={boundary}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace", action="store_true", help="overwrite categories that already have an image")
    ap.add_argument("--only-real", action="store_true", help="only use real category images (no product fallback)")
    ap.add_argument("--src", type=Path, default=SRC, help=f"categories file (default {SRC})")
    args = ap.parse_args()

    api = Api(args.base, read_token())
    cats = json.loads(args.src.read_text(encoding="utf-8"))
    existing = existing_by_slug(api)

    results, counts = [], {"uploaded": 0, "skipped": 0, "missing": 0, "failed": 0}
    for c in sorted(cats, key=lambda c: (c["depth"], c["sortOrder"])):
        res = {"slug": c["slug"], "title": c["title"], "status": None, "source": None, "imageUrl": None, "error": None}
        e = existing.get(c["slug"])
        try:
            if not e:
                res["status"], res["error"] = "missing", "category not on API — run import_categories.py first"
            elif e.get("imageUrl") and not args.replace:
                res["status"], res["imageUrl"] = "skipped", e["imageUrl"]
            else:
                found = download(c, args.only_real)
                if not found:
                    res["status"], res["error"] = "missing", "no image on source"
                else:
                    src, origin, content, ctype = found
                    res["source"] = f"{origin} | {src}"
                    if not args.dry_run:
                        name = urllib.parse.unquote(src.rsplit("/", 1)[-1]) or "image"
                        ext = Path(name).suffix or mimetypes.guess_extension(ctype) or ".jpg"
                        body, mp_type = multipart({
                            "ownerType": "CATEGORY", "ownerId": e["id"], "purpose": "COVER",
                            "isMain": "true", "folder": "categories", "alt": c["title"],
                        }, f"{c['slug']}{ext}", content, ctype)
                        media = api.call("POST", "/media/upload", raw=body, content_type=mp_type)
                        api.call("PATCH", f"/categories/{e['id']}", {"imageUrl": media["url"]})
                        res["imageUrl"] = media["url"]
                        time.sleep(DELAY)
                    res["status"] = "uploaded"
                time.sleep(0.3)  # be gentle with pumaair.ir
        except Exception as ex:
            res["status"], res["error"] = "failed", str(ex)
        counts[res["status"]] += 1
        info = res["error"] or (res["source"] or "").split(" | ")[0]
        print(f"  {res['status']:<8} {'  ' * c['depth']}{c['title']} [{c['slug']}]  {info}", file=sys.stderr)
        results.append(res)

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"\n{prefix}" + " ".join(f"{k}={v}" for k, v in counts.items()), file=sys.stderr)
    if not args.dry_run:
        RESULT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"result -> {RESULT}", file=sys.stderr)


if __name__ == "__main__":
    main()
