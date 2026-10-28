#!/usr/bin/env python3
"""pumaair.ir brand crawler.

pumaair.ir has no brand taxonomy: brands are product tags (/product-tag/<slug>/) and their logos
are inline <svg>s in the header mega-menu (plus a few plain <img>s). This script reads the homepage,
pulls every logo out, and writes:

  output/brands.json              [{title, slug, sourceUrl, logo}]   logo = file under output/ (or null)
  output/brand_logos/<slug>.svg   raw logo as served
  output/brand_logos/<slug>.png   transparent 512px raster (the API takes PNG/JPEG/WebP, not SVG)

  python3 brands.py
  python3 brands.py --list-unlinked   # dump logos it can't attribute (to extend LOGO_OWNERS)

Rasterising uses `sharp` from ../api/node_modules (needs `pnpm install` there).
"""
import hashlib
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

SITE = "https://pumaair.ir"
TAGS_API = f"{SITE}/wp-json/wc/store/v1/products/tags?per_page=100"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36"
OUT_DIR = Path("output")
LOGO_DIR = OUT_DIR / "brand_logos"
API_DIR = Path(__file__).resolve().parent.parent / "api"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # same rule as api brands.schemas.ts

# Display names as pumaair.ir writes them on /brands/; anything else falls back to the tag name.
TITLES = {
    "puma": "Puma", "kilews": "Kilews", "mtt": "MTT", "rocol": "Rocol", "rotake": "Rotake",
    "sumake": "Sumake", "vessel": "Vessel", "bsd": "BSD", "thb": "THB", "olfa": "Olfa",
    "worx": "Worx", "torqnado": "Torqnado",
}
# Logos the site links to the wrong tag, or shows with no link at all, keyed by a sha1 prefix of
# the logo file. Run with --list-unlinked to dump unknown ones into output/brand_logos/ after a redesign.
LOGO_OWNERS = {
    "54e6466f8965": "worx",      # WORX logo linked to /product-tag/kilews/
    "be2198304c27": "torqnado",  # no link
    "e9595fc4705c": "olfa",      # <img>, no link
}
# Listed on /brands/ but no logo anywhere on the site — imported without one.
LOGOLESS = ["sumake"]

VOID = {"img", "br", "hr", "meta", "link", "input", "source", "wbr", "area", "col", "embed", "param", "track"}


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


class Tree(HTMLParser):
    """Tiny DOM: enough to know which <a> each logo sits in."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.html = html
        self.root = {"tag": "#root", "a": {}, "kids": []}
        self.stack = [self.root]
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", html)]
        self.feed(html)

    def char_offset(self):
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "a": dict(attrs), "kids": []}
        if tag == "svg":
            # HTMLParser lower-cases names (viewBox, clipPath) — keep the original markup instead.
            start = self.char_offset()
            end = self.html.find("</svg>", start)
            node["source"] = self.html[start:end + len("</svg>")]
        self.stack[-1]["kids"].append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1]["kids"].append({"tag": tag, "a": dict(attrs), "kids": []})

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return


def logos(node, href=None):
    """Yield (href, kind, payload) for every brand logo: inline svg (not icon-font svgs) or img."""
    if node["tag"] == "a":
        href = node["a"].get("href")
    if node["tag"] == "svg":
        if "e-font-icon-svg" not in (node["a"].get("class") or ""):
            yield href, "svg", node["source"]
        return
    if node["tag"] == "img":
        src = node["a"].get("src") or node["a"].get("data-src") or ""
        if re.search(r"logo", src, re.I):
            yield href, "img", src
        return
    for kid in node.get("kids", []):
        yield from logos(kid, href)


def tag_slug(href):
    m = re.search(r"/product-tag/([^/]+)/?$", href or "")
    return urllib.parse.unquote(m.group(1)).lower() if m else None


def rasterise(src, dst):
    js = (
        "const sharp=require('sharp');"
        "sharp(process.argv[1],{density:300}).trim().resize({width:512,height:512,fit:'inside',withoutEnlargement:false})"
        ".png().toFile(process.argv[2]).catch(e=>{console.error(e.message);process.exit(1)})"
    )
    subprocess.run(["node", "-e", js, str(src.resolve()), str(dst.resolve())], cwd=API_DIR, check=True)


def main():
    list_unlinked = "--list-unlinked" in sys.argv
    tags = {t["slug"]: t["name"] for t in json.loads(http_get(TAGS_API))}
    tree = Tree(http_get(SITE + "/").decode("utf-8", "replace"))
    LOGO_DIR.mkdir(parents=True, exist_ok=True)

    # slug -> {fingerprint: [count, kind, content, sourceUrl]}; a logo repeated in the menu wins
    candidates, unknown = {}, {}
    for href, kind, payload in logos(tree.root):
        content = payload.encode() if kind == "svg" else http_get(payload)
        fp = hashlib.sha1(content).hexdigest()[:12]
        ext = "svg" if kind == "svg" else Path(urllib.parse.urlparse(payload).path).suffix.lstrip(".")
        slug = LOGO_OWNERS.get(fp) or tag_slug(href)
        if not slug or not SLUG_RE.match(slug):
            unknown[fp] = (ext, content)
            continue
        entry = candidates.setdefault(slug, {}).setdefault(fp, [0, ext, content, href or SITE])
        entry[0] += 1

    if list_unlinked:
        for fp, (ext, content) in unknown.items():
            (LOGO_DIR / f"_unlinked-{fp}.{ext}").write_bytes(content)
        print(f"{len(unknown)} unlinked logos -> output/brand_logos/_unlinked-*")
        return

    brands = []
    for slug, variants in candidates.items():
        _, ext, content, source = max(variants.values(), key=lambda v: v[0])
        raw = LOGO_DIR / f"{slug}.{ext}"
        raw.write_bytes(content)
        png = LOGO_DIR / f"{slug}.png"
        rasterise(raw, png)
        brands.append({
            "title": TITLES.get(slug) or tags.get(slug) or slug,
            "slug": slug,
            "sourceUrl": source,
            "logo": str(png.relative_to(OUT_DIR)),
        })
    for slug in LOGOLESS:
        if slug not in candidates:
            brands.append({"title": TITLES.get(slug, slug), "slug": slug, "sourceUrl": f"{SITE}/brands/", "logo": None})

    brands.sort(key=lambda b: b["slug"])
    (OUT_DIR / "brands.json").write_text(json.dumps(brands, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(brands)} brands -> output/brands.json")
    for b in brands:
        print(f"  {b['slug']:10} {b['title']:10} {b['logo'] or '(no logo)'}")


if __name__ == "__main__":
    main()
