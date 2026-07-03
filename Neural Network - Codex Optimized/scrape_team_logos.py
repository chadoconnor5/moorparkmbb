#!/usr/bin/env python3
"""Scrape official-looking school logo images and normalize them to PNG.

This is intentionally source-auditable: every downloaded image is recorded in
internal_data/team_logos/manifest.json so questionable matches can be reviewed
and replaced slowly.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import tempfile
import time
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError
import requests

from ccc_config import CONFERENCES


OUT_DIR = Path("internal_data/team_logos")
PNG_DIR = OUT_DIR / "png"
RAW_DIR = OUT_DIR / "raw"
MANIFEST_PATH = OUT_DIR / "manifest.json"
MANIFEST_CSV_PATH = OUT_DIR / "manifest.csv"
CCCMBCA_TEAMS_URL = "https://cccmbca.org/sports/mbkb/2025-26/teams?serverSide"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TIMEOUT = 25


COMMON_TEAM_DOMAINS = {
    "Allan Hancock": ["athletics.hancockcollege.edu"],
    "Antelope Valley": ["gomarauders.avc.edu"],
    "Barstow": ["barstowvikings.com", "www.barstowvikings.com"],
    "Butte": ["butteroadrunners.com", "www.butteroadrunners.com"],
    "Cabrillo": ["cabrilloseahawks.com", "www.cabrilloseahawks.com"],
    "Canyons": ["cocathletics.com", "www.cocathletics.com"],
    "Cerritos": ["cerritosfalcons.com", "www.cerritosfalcons.com"],
    "Chaffey": ["chaffeypanthers.com", "www.chaffeypanthers.com"],
    "Citrus": ["citrusowls.com", "www.citrusowls.com"],
    "Compton": ["comptontartars.com", "www.comptontartars.com"],
    "Cuesta": ["cuestaathletics.com", "www.cuestaathletics.com"],
    "Cypress": ["cypresschargers.com", "www.cypresschargers.com"],
    "East Los Angeles": ["elacathletics.com", "www.elacathletics.com"],
    "El Camino": ["eccwarriors.com", "www.eccwarriors.com"],
    "Feather River": ["athletics.frc.edu"],
    "Foothill": ["foothillowls.com", "www.foothillowls.com"],
    "Folsom Lake": ["flcfalcons.com", "www.flcfalcons.com"],
    "Fullerton": ["fchornets.com", "www.fchornets.com"],
    "Gavilan": ["gavilanrams.com", "www.gavilanrams.com"],
    "Glendale": ["glendaleathletics.com", "www.glendaleathletics.com"],
    "Grossmont": ["grossmontgriffins.com", "www.grossmontgriffins.com"],
    "Hartnell": ["hartnellpanthers.com", "www.hartnellpanthers.com"],
    "Imperial Valley": ["ivcarabs.com", "www.ivcarabs.com"],
    "Irvine Valley": ["ivclasers.com", "www.ivclasers.com"],
    "LA Harbor": ["laharborathletics.com", "www.laharborathletics.com"],
    "LA Pierce": ["lapierceathletics.com", "www.lapierceathletics.com"],
    "LA Trade Tech": ["lattcathletics.com", "www.lattcathletics.com"],
    "LA Valley": ["lavcathletics.com", "www.lavcathletics.com"],
    "Lassen": ["lassencougars.com", "www.lassencougars.com"],
    "Las Positas": ["laspositashawks.com", "www.laspositashawks.com"],
    "Long Beach": ["lbccvikings.com", "www.lbccvikings.com"],
    "Los Angeles City": ["lacitycubs.com", "www.lacitycubs.com"],
    "Marin": ["marinathletics.com", "www.marinathletics.com"],
    "Mendocino": ["mendocinoeagles.com", "www.mendocinoeagles.com"],
    "Merced": ["mercedblueprints.com", "www.mercedblueprints.com"],
    "Merritt": ["merrittathletics.com", "www.merrittathletics.com"],
    "MiraCosta": ["miracostaspartans.com", "www.miracostaspartans.com"],
    "Modesto": ["athletics.mjc.edu"],
    "Monterey Peninsula": ["mpclobos.com", "www.mpclobos.com"],
    "Moorpark": ["moorparkcollegeathletics.com", "www.moorparkcollegeathletics.com"],
    "Mt. San Antonio": ["mtsacathletics.com", "www.mtsacathletics.com"],
    "Mt. San Jacinto": ["msjcathletics.com", "www.msjcathletics.com"],
    "Napa Valley": ["napavalley1839.com", "www.napavalley1839.com"],
    "Ohlone": ["ohlonerenegades.com", "www.ohlonerenegades.com"],
    "Orange Coast": ["occathletics.com", "www.occathletics.com"],
    "Oxnard": ["oxnardcondors.com", "www.oxnardcondors.com"],
    "Palomar": ["palomarathletics.com", "www.palomarathletics.com"],
    "Pasadena City": ["pcclancers.com", "www.pcclancers.com"],
    "Porterville": ["portervillepirates.com", "www.portervillepirates.com"],
    "Redwoods": ["redwoodsathletics.com", "www.redwoodsathletics.com"],
    "Rio Hondo": ["riohondoathletics.com", "www.riohondoathletics.com"],
    "Riverside": ["rccathletics.com", "www.rccathletics.com"],
    "Sacramento City": ["sccpanthers.com", "www.sccpanthers.com"],
    "Saddleback": ["saddlebackbobcats.com", "www.saddlebackbobcats.com"],
    "San Bernardino Valley": ["sbvcathletics.com", "www.sbvcathletics.com"],
    "San Diego City": ["sdcityknights.com", "www.sdcityknights.com"],
    "San Diego Mesa": ["sdmesaathletics.com", "www.sdmesaathletics.com"],
    "San Diego Miramar": ["sdmiramarjets.com", "www.sdmiramarjets.com"],
    "San Francisco": ["ccsfathletics.com", "www.ccsfathletics.com"],
    "San Joaquin Delta": ["deltacollegeathletics.com", "www.deltacollegeathletics.com"],
    "San Jose": ["sjccjaguars.com", "www.sjccjaguars.com"],
    "San Mateo": ["smccd.edu", "collegeofsanmateo.edu"],
    "Santa Ana": ["sacdons.com", "www.sacdons.com"],
    "Santa Barbara": ["sbccvaqueros.com", "www.sbccvaqueros.com"],
    "Santa Monica": ["smccorsairs.com", "www.smccorsairs.com"],
    "Santa Rosa": ["santarosabearcubs.com", "www.santarosabearcubs.com"],
    "Santiago Canyon": ["sccollegeathletics.com", "www.sccollegeathletics.com"],
    "Shasta": ["shastaknights.com", "www.shastaknights.com"],
    "Sierra": ["sierracollegeathletics.com", "www.sierracollegeathletics.com"],
    "Siskiyous": ["siskiyouseagles.com", "www.siskiyouseagles.com"],
    "Solano": ["solanofalcons.com", "www.solanofalcons.com"],
    "Southwestern": ["southwesternjaguars.com", "www.southwesternjaguars.com"],
    "Ventura": ["ventura.prestosports.com"],
    "Victor Valley": ["vvcrams.com", "www.vvcrams.com"],
    "West LA": ["westlacollegeathletics.com", "www.westlacollegeathletics.com"],
    "West Valley": ["westvalleyvikings.com", "www.westvalleyvikings.com"],
    "Yuba": ["yubaathletics.com", "www.yubaathletics.com"],
}


class ImageCandidateParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.candidates: list[dict] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            prop = (attrs.get("property") or attrs.get("name") or "").lower()
            content = attrs.get("content")
            if content and prop in {"og:image", "twitter:image", "profile-site-logo"}:
                self.add(content, f"meta:{prop}", attrs.get("alt", ""))
        if tag == "img":
            src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-original")
            if src:
                self.add(src, "img", " ".join([attrs.get("alt", ""), attrs.get("class", ""), attrs.get("id", "")]))

    def add(self, url: str, source_type: str, context: str):
        full = urllib.parse.urljoin(self.base_url, url)
        text = f"{full} {context}".lower()
        score = 0
        if "logo" in text:
            score += 20
        if "logos" in text:
            score += 5
        if "primary" in text:
            score += 8
        if "secondary" in text:
            score += 4
        if "site-logo" in text or "navbar" in text:
            score += 5
        if any(x in text for x in ["thumbnail_default", "adobe", "footer", "nbca", "cccm", "3c2a", "aotw", "/photos/team/", "/photos/"]):
            score -= 30
        if any(full.lower().split("?")[0].endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".svg"]):
            score += 4
        self.candidates.append({"url": full, "source_type": source_type, "context": context, "score": score})


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def fetch_bytes(url: str) -> tuple[bytes, str]:
    resp = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("content-type", "")


def looks_like_image(data: bytes, content_type: str) -> bool:
    lowered = content_type.lower()
    if not data:
        return False
    if "image" in lowered:
        return True
    return (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"RIFF")
        or data.lstrip().startswith(b"<svg")
    )


def fetch_image_bytes(url: str, attempts: int = 5) -> tuple[bytes, str]:
    last_error = ""
    for attempt in range(attempts):
        try:
            data, content_type = fetch_bytes(url)
            if looks_like_image(data, content_type):
                return data, content_type
            last_error = f"non-image response ({content_type or 'unknown content type'}, {len(data)} bytes)"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1.0 + attempt * 0.75)
    raise ValueError(last_error or "image download failed")


def fetch_text(url: str) -> str:
    data, _ = fetch_bytes(url)
    return data.decode("utf-8", errors="replace")


def guess_ext(url: str, content_type: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for ext in [".png", ".jpg", ".jpeg", ".webp", ".svg"]:
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    if "svg" in content_type:
        return ".svg"
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    return ".img"


def normalize_to_png(raw_path: Path, png_path: Path) -> bool:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.suffix.lower() == ".svg":
        with tempfile.TemporaryDirectory() as td:
            preview = Path(td) / "preview.png"
            try:
                subprocess.run(["qlmanage", "-t", "-s", "512", "-o", td, str(raw_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                generated = next(Path(td).glob("*.png"), None)
                if generated:
                    with Image.open(generated) as im:
                        im.convert("RGBA").save(png_path)
                    return True
            except Exception:
                return False
            return preview.exists()
    try:
        with Image.open(raw_path) as im:
            im.convert("RGBA").save(png_path)
        return True
    except UnidentifiedImageError:
        pass
    except Exception:
        pass
    with tempfile.TemporaryDirectory() as td:
        converted = Path(td) / "converted.png"
        try:
            subprocess.run(
                ["sips", "-s", "format", "png", str(raw_path), "--out", str(converted)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with Image.open(converted) as im:
                im.convert("RGBA").save(png_path)
            return True
        except Exception:
            return False


def seed_urls(team: str) -> list[str]:
    urls = []
    for domain in COMMON_TEAM_DOMAINS.get(team, []):
        urls.extend([
            f"https://{domain}/",
            f"https://{domain}/sports/mbkb/index",
            f"https://{domain}/sports/mbkb/2025-26/roster",
        ])
    return urls


def best_logo_for_team(team: str, max_pages: int = 3) -> dict:
    candidates = []
    checked_pages = []
    for page_url in seed_urls(team)[:max_pages]:
        try:
            html = fetch_text(page_url)
            checked_pages.append(page_url)
        except Exception:
            continue
        parser = ImageCandidateParser(page_url)
        parser.feed(html)
        for c in parser.candidates:
            if team.lower().split()[0] in c["url"].lower() or c["score"] > 0:
                candidates.append(c)
        time.sleep(0.4)
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return {"team": team, "checked_pages": checked_pages, "candidates": candidates[:8]}


def scrape_team(team: str, force: bool = False) -> dict:
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_png = PNG_DIR / f"{slug(team)}.png"
    if out_png.exists() and not force:
        return {"team": team, "status": "exists", "png_path": str(out_png)}
    result = best_logo_for_team(team)
    for cand in result["candidates"]:
        try:
            data, content_type = fetch_image_bytes(cand["url"])
            ext = guess_ext(cand["url"], content_type)
            raw_path = RAW_DIR / f"{slug(team)}{ext}"
            raw_path.write_bytes(data)
            if normalize_to_png(raw_path, out_png):
                return {
                    "team": team,
                    "status": "ok",
                    "source_url": cand["url"],
                    "source_type": cand["source_type"],
                    "score": cand["score"],
                    "raw_path": str(raw_path),
                    "png_path": str(out_png),
                    "checked_pages": result["checked_pages"],
                }
        except Exception as exc:
            cand["error"] = str(exc)
            continue
    return {"team": team, "status": "missing", **result}


def cccmbca_logo_map() -> dict[str, dict]:
    html = fetch_text(CCCMBCA_TEAMS_URL)
    soup = BeautifulSoup(html, "html.parser")
    logos: dict[str, dict] = {}
    configured = set(all_teams())
    for link in soup.select('a[href*="/sports/mbkb/2025-26/teams/"]'):
        img = link.find("img")
        if not img:
            continue
        team = (img.get("alt") or link.get_text(" ", strip=True)).strip()
        if team not in configured:
            continue
        src = img.get("src")
        if not src:
            continue
        source_url = urllib.parse.urljoin(CCCMBCA_TEAMS_URL, src)
        parsed = urllib.parse.urlparse(source_url)
        if parsed.netloc == "cdn.prestosports.com":
            source_url = urllib.parse.urlunparse(("https", "cccmbca.org", parsed.path, "", parsed.query, ""))
        logos[team] = {
            "team": team,
            "source_url": source_url,
            "team_page_url": urllib.parse.urljoin(CCCMBCA_TEAMS_URL, link.get("href", "")),
            "source_type": "cccmbca_teams_table",
        }
    return logos


def scrape_team_from_cccmbca(team: str, logo_row: dict, force: bool = False) -> dict:
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_png = PNG_DIR / f"{slug(team)}.png"
    if out_png.exists() and not force:
        return {"team": team, "status": "exists", "png_path": str(out_png), **logo_row}
    if not logo_row and out_png.exists():
        return {"team": team, "status": "exists", "png_path": str(out_png)}
    if not logo_row:
        return {"team": team, "status": "missing_from_cccmbca_table"}
    try:
        data, content_type = fetch_image_bytes(logo_row["source_url"])
        ext = guess_ext(logo_row["source_url"], content_type)
        raw_path = RAW_DIR / f"{slug(team)}{ext}"
        raw_path.write_bytes(data)
        if normalize_to_png(raw_path, out_png):
            return {
                "team": team,
                "status": "ok",
                "source_url": logo_row["source_url"],
                "team_page_url": logo_row.get("team_page_url", ""),
                "source_type": logo_row.get("source_type", "cccmbca_teams_table"),
                "raw_path": str(raw_path),
                "png_path": str(out_png),
            }
        if out_png.exists():
            return {"team": team, "status": "kept_existing_after_convert_failed", **logo_row, "raw_path": str(raw_path), "png_path": str(out_png)}
        return {"team": team, "status": "convert_failed", **logo_row, "raw_path": str(raw_path)}
    except Exception as exc:
        if out_png.exists():
            return {"team": team, "status": "kept_existing_after_download_failed", **logo_row, "error": str(exc), "png_path": str(out_png)}
        return {"team": team, "status": "download_failed", **logo_row, "error": str(exc)}


def all_teams() -> list[str]:
    teams = []
    for names in CONFERENCES.values():
        teams.extend(names)
    return sorted(set(teams))


def normalize_requested_teams(tokens: list[str]) -> list[str]:
    configured = set(all_teams())
    if not tokens:
        return []
    joined = " ".join(tokens)
    if joined in configured:
        return [joined]
    teams = []
    i = 0
    while i < len(tokens):
        match = None
        for j in range(len(tokens), i, -1):
            candidate = " ".join(tokens[i:j])
            if candidate in configured:
                match = candidate
                i = j
                break
        if match:
            teams.append(match)
        else:
            teams.append(tokens[i])
            i += 1
    return teams


def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape team logo assets and normalize to PNG")
    ap.add_argument("--teams", nargs="+", help="Specific team names to scrape")
    ap.add_argument("--all", action="store_true", help="Scrape all configured teams")
    ap.add_argument("--force", action="store_true", help="Overwrite existing PNGs")
    ap.add_argument("--source", choices=["cccmbca", "official"], default="cccmbca", help="Logo source strategy")
    args = ap.parse_args()

    teams = normalize_requested_teams(args.teams or []) or (all_teams() if args.all else [])
    if not teams:
        ap.error("Pass --all or --teams Team Name ...")

    manifest = []
    if MANIFEST_PATH.exists():
        try:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = []
    configured = set(all_teams())
    by_team = {row.get("team"): row for row in manifest if row.get("team") in configured}

    ccc_logos = cccmbca_logo_map() if args.source == "cccmbca" else {}

    for idx, team in enumerate(teams, 1):
        print(f"[{idx}/{len(teams)}] {team}")
        if args.source == "cccmbca":
            logo_row = ccc_logos.get(team)
            row = scrape_team_from_cccmbca(team, logo_row, force=args.force)
        else:
            row = scrape_team(team, force=args.force)
        by_team[team] = row
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps([by_team[t] for t in sorted(by_team)], indent=2), encoding="utf-8")
        write_manifest_csv(by_team)
        print(f"  {row.get('status')} {row.get('png_path', '')}")

    ok = sum(1 for row in by_team.values() if row.get("status") in {"ok", "exists", "kept_existing_after_download_failed", "kept_existing_after_convert_failed"})
    print(f"logo PNGs available: {ok}/{len(by_team)}")


def write_manifest_csv(by_team: dict[str, dict]) -> None:
    MANIFEST_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["team", "status", "png_path", "raw_path", "source_url", "source_type", "score"],
        )
        writer.writeheader()
        for team in sorted(by_team):
            row = by_team[team]
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})


if __name__ == "__main__":
    main()
