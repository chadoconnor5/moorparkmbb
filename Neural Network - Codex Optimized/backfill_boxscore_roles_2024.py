"""Backfill starter/reserve roles into saved 2024-25 box score JSON files."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from scrape_team_2024 import fetch, parse_boxscore


BASE_DIR = Path("2024-25 Teams Schedules")
PROGRESS_PATH = Path("outputs/bench_role_backfill_progress_2024_25.json")
REPORT_PATH = Path("outputs/bench_role_backfill_report_2024_25.json")


def game_id_for(date_str: str, opponent: str) -> str:
    dt = datetime.strptime(date_str.strip() + " 2024", "%b %d %Y")
    if dt.month <= 6:
        dt = dt.replace(year=2025)
    safe_opp = re.sub(r"[^a-zA-Z0-9]", "_", opponent).lower().strip("_")
    return f"{dt:%Y%m%d}_{safe_opp}"


def player_roles_present(path: Path, team_name: str) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    players = data.get("teams", {}).get(team_name, [])
    return bool(players) and all(p.get("role") in {"starter", "reserve"} for p in players)


def load_progress() -> set[str]:
    if not PROGRESS_PATH.exists():
        return set()
    try:
        data = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return set(data.get("completed_urls", []))


def save_progress(completed_urls: set[str]) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(
        json.dumps({"completed_urls": sorted(completed_urls)}, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    url_targets: dict[str, list[dict]] = defaultdict(list)
    skipped_ready = 0
    bad_rows = []

    for schedule_path in sorted(BASE_DIR.glob("*/*/schedule.json")):
        team_dir = schedule_path.parent
        team_name = team_dir.name
        conference = team_dir.parent.name
        schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
        for game in schedule.get("games", []):
            url = game.get("boxscore_url")
            if not url:
                continue
            try:
                game_id = game_id_for(game.get("date", ""), game.get("opponent", "unknown"))
            except ValueError as exc:
                bad_rows.append(
                    {
                        "team": team_name,
                        "conference": conference,
                        "date": game.get("date", ""),
                        "opponent": game.get("opponent", ""),
                        "error": str(exc),
                    }
                )
                continue
            out_path = team_dir / game_id / f"{game_id}.json"
            if player_roles_present(out_path, team_name):
                skipped_ready += 1
                continue
            full_url = url if url.startswith("http") else f"https://cccmbca.org{url}"
            url_targets[full_url].append(
                {
                    "team": team_name,
                    "conference": conference,
                    "out_path": str(out_path),
                    "game_id": game_id,
                }
            )

    completed_urls = load_progress()
    total_urls = len(url_targets)
    fetched = 0
    written = 0
    failed = []

    print(f"ready team-game files skipped: {skipped_ready}")
    print(f"unique URLs needing refresh: {total_urls}")
    print(f"previously completed URLs in checkpoint: {len(completed_urls)}")

    for idx, (url, targets) in enumerate(url_targets.items(), 1):
        if url in completed_urls and all(
            player_roles_present(Path(t["out_path"]), t["team"]) for t in targets
        ):
            continue
        try:
            html = fetch(url)
            boxscore = parse_boxscore(html)
            fetched += 1
            for target in targets:
                out_path = Path(target["out_path"])
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(boxscore, indent=2), encoding="utf-8")
                written += 1
            completed_urls.add(url)
            save_progress(completed_urls)
            if fetched == 1 or fetched % 25 == 0:
                print(
                    f"fetched {fetched} this run / {total_urls} queued "
                    f"(index {idx}); wrote {written} team-game files"
                )
        except Exception as exc:
            failed.append({"url": url, "targets": targets, "error": str(exc)})
            print(f"FAILED {url}: {exc}")

    report = {
        "skipped_ready_team_games": skipped_ready,
        "queued_unique_urls": total_urls,
        "fetched_this_run": fetched,
        "written_team_games": written,
        "failed": failed,
        "bad_schedule_rows": bad_rows,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
