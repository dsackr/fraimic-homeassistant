#!/usr/bin/env python3
"""Maintainer tool: build/refresh Fraimic scene packs.

NOT loaded by the integration -- this is a one-off content-curation script
for whoever maintains this repo's scene_packs/ directory. It queries
Wikimedia Commons for candidate paintings, keeps only files whose license
metadata explicitly says "public domain", downsizes them (the running
integration converts to per-frame .bin at install time -- it never needs
full museum-scan resolution), and writes scene_packs/<pack_id>/*.jpg plus
scene_packs/index.json.

Usage:
    python3 scripts/build_scene_pack.py

Add a new pack by adding an entry to PACKS below and re-running -- existing
packs are rebuilt too (Commons occasionally reshuffles which scan is the
"best" one for a search query), so review `git diff` before committing.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

from PIL import Image

# Raised (not disabled) from Pillow's ~89MP default: legitimate museum scans
# routinely exceed that, and MAX_SOURCE_PIXELS below already rejects anything
# apt to be slow/huge before it's ever downloaded -- this is just a backstop
# in case width/height from the Commons API ever disagrees with the actual
# file (e.g. a redirect), so decoding still fails fast instead of hanging.
Image.MAX_IMAGE_PIXELS = 200_000_000

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS_DIR = os.path.join(REPO_ROOT, "scene_packs")

MAX_LONG_EDGE = 2400  # comfortably covers the largest current frame, 2560x1440
JPEG_QUALITY = 85
MIN_SOURCE_DIM = 1000  # reject thumbnails/detail crops that are too small to be useful
# Some Commons "Google Art Project" ultra-zoom scans run to multiple
# gigapixels (one Night Watch scan is 2.8 billion). Decoding those takes
# minutes and gigabytes of RAM for zero quality benefit once downsized to
# MAX_LONG_EDGE -- reject candidates above this before ever downloading them.
# Matches Image.MAX_IMAGE_PIXELS above, so nothing that clears this filter
# can still trip Pillow's own guard.
MAX_SOURCE_PIXELS = 200_000_000
IMAGES_PER_PACK_TARGET = 8

USER_AGENT = (
    "FraimicScenePackBuilder/1.0 "
    "(https://github.com/dsackr/fraimic-homeassistant; maintainer tooling)"
)

API_URL = "https://commons.wikimedia.org/w/api.php"

_EXCLUDE_TITLE_PATTERNS = re.compile(
    r"\bdetail\b|\bcropp?ed\b|replica|after |sketch for|study for|forgery|restoration|"
    r"x-?ray|infrared|conservation|photograph of the|frame\b|"
    r"-x\d+-y\d+",  # a single zoomify tile from a Google Art Project scan, not the whole work
    re.IGNORECASE,
)

# No well-known painting is this elongated -- anything past this is almost
# certainly a tile fragment or a panoramic detail crop, not the full work
# (bit us once already: a Van Gogh "Starry Night" query's top-scoring hit by
# raw pixel count was a 29696x5595 zoomify tile strip).
MAX_ASPECT_RATIO = 2.5


def _api_get(params: dict) -> dict:
    params = {**params, "format": "json"}
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _search_candidates(query: str, limit: int = 6) -> list[str]:
    data = _api_get(
        {
            "action": "query",
            "list": "search",
            "srnamespace": 6,
            "srlimit": limit,
            "srsearch": query,
        }
    )
    return [hit["title"] for hit in data.get("query", {}).get("search", [])]


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def _imageinfo(titles: list[str]) -> dict[str, dict]:
    """Return {title: {url, width, height, mime, license_ok, artist_text}}."""
    if not titles:
        return {}
    data = _api_get(
        {
            "action": "query",
            "titles": "|".join(titles),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
        }
    )
    out: dict[str, dict] = {}
    for page in data.get("query", {}).get("pages", {}).values():
        title = page.get("title")
        infos = page.get("imageinfo") or []
        if not title or not infos:
            continue
        info = infos[0]
        meta = info.get("extmetadata", {}) or {}
        license_name = str(meta.get("LicenseShortName", {}).get("value", "")).lower()
        usage_terms = str(meta.get("UsageTerms", {}).get("value", "")).lower()
        license_ok = "public domain" in license_name or "public domain" in usage_terms
        artist_text = _strip_accents(
            _strip_html(str(meta.get("Artist", {}).get("value", "")))
        ).lower()
        out[title] = {
            "url": info.get("url"),
            "width": info.get("width", 0),
            "height": info.get("height", 0),
            "mime": info.get("mime"),
            "license_ok": license_ok,
            "page_url": info.get("descriptionurl"),
            "artist_text": artist_text,
        }
    return out


def _pick_best(query: str, artist_keyword: str, seen_urls: set[str]) -> dict | None:
    candidates = _search_candidates(query, limit=8)
    candidates = [c for c in candidates if not _EXCLUDE_TITLE_PATTERNS.search(c)]
    if not candidates:
        return None
    infos = _imageinfo(candidates)
    keyword = _strip_accents(artist_keyword).lower()

    scored = []
    for title in candidates:
        info = infos.get(title)
        if not info or not info["license_ok"]:
            continue
        if info["mime"] not in ("image/jpeg", "image/png"):
            continue
        if info["width"] < MIN_SOURCE_DIM or info["height"] < MIN_SOURCE_DIM:
            continue
        if info["width"] * info["height"] > MAX_SOURCE_PIXELS:
            continue
        if max(info["width"], info["height"]) / min(info["width"], info["height"]) > MAX_ASPECT_RATIO:
            continue
        if info["url"] in seen_urls:
            continue
        # Commons full-text search matches page content, not just the
        # title, so an unrelated painting can outrank the real one (bit us
        # once already: a "van Gogh Self-Portrait" query's top hit was a
        # Malczewski painting). Trust the file's own Artist metadata when
        # present; only fall back to a title-keyword check when a file
        # genuinely has no structured Artist field.
        artist_text = info["artist_text"]
        haystack = artist_text if artist_text else _strip_accents(title).lower()
        if keyword not in haystack:
            continue
        scored.append((info["width"] * info["height"], title, info))

    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    _, title, info = scored[0]
    return {"title": title, **info}


def _slugify(text: str) -> str:
    text = re.sub(r"^File:", "", text)
    text = re.sub(r"\.(jpg|jpeg|png)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text[:60] or "image"


def _download_and_resize(url: str, dest_path: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()

    from io import BytesIO

    with Image.open(BytesIO(raw)) as img:
        img = img.convert("RGB")
        w, h = img.size
        scale = MAX_LONG_EDGE / max(w, h)
        if scale < 1:
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        img.save(dest_path, "JPEG", quality=JPEG_QUALITY, optimize=True)


def build_pack(pack: dict) -> dict:
    pack_id = pack["id"]
    out_dir = os.path.join(PACKS_DIR, pack_id)
    os.makedirs(out_dir, exist_ok=True)

    images = []
    seen_urls: set[str] = set()

    for query_spec in pack["queries"]:
        query, display_title, artist_keyword = query_spec
        try:
            best = _pick_best(query, artist_keyword, seen_urls)
        except Exception as err:  # noqa: BLE001
            print(f"  ! query failed ({query!r}): {err}", file=sys.stderr)
            continue
        if not best:
            print(f"  - no valid candidate for {query!r}", file=sys.stderr)
            continue

        seen_urls.add(best["url"])
        slug = _slugify(display_title)
        filename = f"{len(images) + 1:02d}_{slug}.jpg"
        dest_path = os.path.join(out_dir, filename)
        try:
            _download_and_resize(best["url"], dest_path)
        except Exception as err:  # noqa: BLE001
            print(f"  ! download/resize failed for {best['title']!r}: {err}", file=sys.stderr)
            continue

        images.append(
            {
                "filename": filename,
                "path": f"scene_packs/{pack_id}/{filename}",
                "title": display_title,
                "source": "Wikimedia Commons",
                "commons_url": best["page_url"],
            }
        )
        print(f"  + {filename}  <-  {best['title']}")
        time.sleep(0.3)  # be polite to the Commons API

    if not images:
        raise RuntimeError(f"Pack '{pack_id}' ended up with zero images")

    return {
        "id": pack_id,
        "name": pack["name"],
        "description": pack["description"],
        "license": "Public domain (verified per-image via Wikimedia Commons)",
        "cover": images[0]["path"],
        "images": images,
    }


PACKS = [
    {
        "id": "monet",
        "name": "Claude Monet",
        "description": "Impressionist gardens, water lilies, and shifting light.",
        "queries": [
            ("Claude Monet Impression Sunrise painting", "Impression, Sunrise", "Monet"),
            ("Claude Monet Water Lilies Google Art Project", "Water Lilies", "Monet"),
            ("Claude Monet Woman with a Parasol painting", "Woman with a Parasol", "Monet"),
            ("Claude Monet Poppy Field Argenteuil painting", "Poppy Field near Argenteuil", "Monet"),
            ("Claude Monet Rouen Cathedral painting", "Rouen Cathedral", "Monet"),
            ("Claude Monet The Magpie painting", "The Magpie", "Monet"),
            ("Claude Monet Wheatstacks painting", "Wheatstacks", "Monet"),
            ("Claude Monet Japanese Bridge Giverny painting", "The Japanese Footbridge", "Monet"),
            ("Claude Monet Garden at Sainte-Adresse painting", "Garden at Sainte-Adresse", "Monet"),
            ("Claude Monet Bridge over a Pond of Water Lilies", "Bridge over a Pond of Water Lilies", "Monet"),
        ],
    },
    {
        "id": "davinci",
        "name": "Leonardo da Vinci",
        "description": "Renaissance portraits, studies, and sacred scenes.",
        "queries": [
            ("Leonardo da Vinci Mona Lisa painting", "Mona Lisa", "Vinci"),
            ("Leonardo da Vinci The Last Supper painting", "The Last Supper", "Vinci"),
            ("Leonardo da Vinci Vitruvian Man drawing", "Vitruvian Man", "Vinci"),
            ("Leonardo da Vinci Lady with an Ermine painting", "Lady with an Ermine", "Vinci"),
            ("Leonardo da Vinci Virgin of the Rocks painting", "Virgin of the Rocks", "Vinci"),
            ("Leonardo da Vinci Ginevra de Benci painting", "Ginevra de' Benci", "Vinci"),
            ("Leonardo da Vinci Annunciation painting Uffizi", "The Annunciation", "Vinci"),
            ("Leonardo da Vinci Saint John the Baptist painting", "Saint John the Baptist", "Vinci"),
        ],
    },
    {
        "id": "van_gogh",
        "name": "Vincent van Gogh",
        "description": "Bold color and brushwork from Post-Impressionism's icon.",
        "queries": [
            ("Vincent van Gogh Starry Night painting MoMA", "The Starry Night", "Gogh"),
            ("Vincent van Gogh Sunflowers painting National Gallery", "Sunflowers", "Gogh"),
            ("Vincent van Gogh Cafe Terrace at Night painting", "Café Terrace at Night", "Gogh"),
            ("Vincent van Gogh Bedroom in Arles painting", "The Bedroom", "Gogh"),
            ("Vincent van Gogh Wheatfield with Crows painting", "Wheatfield with Crows", "Gogh"),
            ("Vincent van Gogh Irises painting Getty", "Irises", "Gogh"),
            ("Vincent van Gogh Self-Portrait painting Orsay", "Self-Portrait", "Gogh"),
            ("Vincent van Gogh The Potato Eaters painting", "The Potato Eaters", "Gogh"),
            ("Vincent van Gogh Almond Blossoms painting", "Almond Blossoms", "Gogh"),
        ],
    },
    {
        "id": "classic_art",
        "name": "Classic Art",
        "description": "Famous public-domain masterworks spanning centuries and continents.",
        "queries": [
            ("Johannes Vermeer Girl with a Pearl Earring painting", "Girl with a Pearl Earring", "Vermeer"),
            ("Katsushika Hokusai Great Wave off Kanagawa print", "The Great Wave off Kanagawa", "Hokusai"),
            ("Sandro Botticelli Birth of Venus painting", "The Birth of Venus", "Botticelli"),
            ("Rembrandt Night Watch painting", "The Night Watch", "Rembrandt"),
            ("Hieronymus Bosch Garden of Earthly Delights painting", "The Garden of Earthly Delights", "Bosch"),
            ("Jan van Eyck Arnolfini Portrait painting", "The Arnolfini Portrait", "Eyck"),
            ("Diego Velazquez Las Meninas painting", "Las Meninas", "Velazquez"),
            ("Gustav Klimt The Kiss painting", "The Kiss", "Klimt"),
            ("Katsushika Hokusai Fine Wind Clear Morning print", "Fine Wind, Clear Morning", "Hokusai"),
        ],
    },
]


def main() -> None:
    os.makedirs(PACKS_DIR, exist_ok=True)
    index_packs = []
    for pack in PACKS:
        print(f"Building pack '{pack['id']}'...")
        index_packs.append(build_pack(pack))

    index_path = os.path.join(PACKS_DIR, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"packs": index_packs}, f, indent=2)
        f.write("\n")
    print(f"Wrote {index_path}")

    print("\nSanity check (flag anything worth a manual look):")
    for pack in index_packs:
        for image in pack["images"]:
            path = os.path.join(REPO_ROOT, image["path"])
            with Image.open(path) as img:
                w, h = img.size
            ratio = max(w, h) / min(w, h)
            flag = " <-- unusual aspect ratio" if ratio > 2.0 else ""
            print(f"  {pack['id']}/{image['filename']}: {w}x{h} ({ratio:.2f}:1){flag}")


if __name__ == "__main__":
    main()
