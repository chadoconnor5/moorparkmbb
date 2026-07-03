#!/usr/bin/env python3
"""
Scrape CCCMBCA 2024-25 standings and output per-conference CSVs and a master JSON.

Usage:
  python scrape_cccmbca_standings_2024.py
"""
import csv
import json
import re
from pathlib import Path
from typing import List, Dict
import requests
from bs4 import BeautifulSoup

URL = "https://cccmbca.prestosports.com/sports/mbkb/2024-25/standings?jsRendering=true"
OUT_DIR = Path("2024-25 Team Statistics")


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_standings_table(table) -> List[Dict]:
    headers = [clean(th.text) for th in table.select("thead th")]
    teams = []
    for row in table.select("tbody tr"):
        cells = [clean(td.text) for td in row.select("td")]
        if not cells or len(cells) < 2 or not cells[0]:
            continue
        team = dict(zip(headers, cells))
        teams.append(team)
    return headers, teams


def main():
    OUT_DIR.mkdir(exist_ok=True)
    resp = requests.get(URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    all_tables = soup.select(".standings-table")
    all_data = {}
    for table in all_tables:
        conf_name = clean(table.find_previous("h3").text if table.find_previous("h3") else "Unknown Conference")
        headers, teams = parse_standings_table(table)
        all_data[conf_name] = teams
        # Write per-conference CSV
        out_csv = OUT_DIR / f"{conf_name.replace(' ', '_')}.csv"
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(teams)
    # Write master JSON
    with (OUT_DIR / "all_conferences.json").open("w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print(f"Wrote standings for {len(all_tables)} conferences to {OUT_DIR}")

if __name__ == "__main__":
    main()
