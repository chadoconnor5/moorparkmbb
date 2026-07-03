#!/usr/bin/env python3
"""Run the standard scrape -> stats -> analytics pipeline."""

import argparse
import subprocess
import sys

from ccc_config import DEFAULT_SEASON


def run_step(cmd: list[str]) -> None:
    print("\n$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CCCMBCA data pipeline")
    parser.add_argument("--season", default=DEFAULT_SEASON, help="Season prefix, e.g. 2025-26")
    parser.add_argument("--teams", nargs="+", help="Specific team names to scrape/process")
    parser.add_argument("--all", action="store_true", help="Scrape/process every available team")
    parser.add_argument("--no-boxscores", action="store_true", help="Refresh schedules without box scores")
    parser.add_argument("--prior-season", help="Prior season to blend into advanced analytics")
    args = parser.parse_args()

    if not args.all and not args.teams:
        parser.error("choose --all or --teams")

    team_args = ["--all"] if args.all else ["--teams", *args.teams]
    scrape_cmd = [sys.executable, "scrape_team.py", "--season", args.season, *team_args]
    if args.no_boxscores:
        scrape_cmd.append("--no-boxscores")

    run_step(scrape_cmd)
    run_step([sys.executable, "generate_team_stats.py", "--season", args.season, *team_args])

    analytics_cmd = [sys.executable, "update_advanced_analytics.py", "--season", args.season, *team_args]
    if args.prior_season:
        analytics_cmd.extend(["--prior-season", args.prior_season])
    run_step(analytics_cmd)


if __name__ == "__main__":
    main()
