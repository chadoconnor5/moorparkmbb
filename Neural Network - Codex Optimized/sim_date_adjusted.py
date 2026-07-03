#!/usr/bin/env python3
"""
Simulate date-adjusted efficiency ratings (read-only, no files modified).

Result: Zero effect on NET RTG because the same date average is subtracted
from both ORTG and DRTG in each game, so the difference (NET) is unchanged.
Useful for showing the league efficiency curve over the season.
"""
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

STATS_DIR = Path("2025-26 Team Statistics")


def load_all_teams():
    """Load all game ratings from all teams."""
    all_games_by_date = defaultdict(list)
    team_game_ratings = {}

    for conf_dir in sorted(STATS_DIR.iterdir()):
        if not conf_dir.is_dir():
            continue
        for team_dir in sorted(conf_dir.iterdir()):
            if not team_dir.is_dir():
                continue
            adv_path = team_dir / "advanced_analytics.json"
            if not adv_path.exists():
                continue
            with open(adv_path) as f:
                adv = json.load(f)
            gr = adv.get("team", {}).get("game_ratings", [])
            team_game_ratings[team_dir.name] = gr
            for g in gr:
                if g.get("in_system"):
                    all_games_by_date[g["date"]].append(g["ortg"])
                    all_games_by_date[g["date"]].append(g["drtg"])

    return all_games_by_date, team_game_ratings


def main():
    all_games_by_date, team_game_ratings = load_all_teams()

    # Season-wide average
    all_effs = [v for vals in all_games_by_date.values() for v in vals]
    season_avg = sum(all_effs) / len(all_effs)
    print(f"Season average efficiency: {season_avg:.1f}")
    print(f"Total in-system efficiency observations: {len(all_effs)}")
    print(f"Unique game dates: {len(all_games_by_date)}")

    # Rolling 14-day window average by date
    dates_sorted = sorted(all_games_by_date.keys(),
                          key=lambda d: datetime.strptime(d, "%m/%d/%Y"))
    date_avg = {}
    for d in dates_sorted:
        d_dt = datetime.strptime(d, "%m/%d/%Y")
        window = []
        for d2 in dates_sorted:
            d2_dt = datetime.strptime(d2, "%m/%d/%Y")
            if abs((d_dt - d2_dt).days) <= 7:
                window.extend(all_games_by_date[d2])
        date_avg[d] = sum(window) / len(window) if window else season_avg

    # Efficiency curve by month
    print(f"\n--- League Avg Efficiency by Month ---")
    monthly = defaultdict(list)
    for d, avg in date_avg.items():
        dt = datetime.strptime(d, "%m/%d/%Y")
        monthly[dt.strftime("%Y-%m")].append(avg)
    for m in sorted(monthly.keys()):
        vals = monthly[m]
        print(f"  {m}: {sum(vals)/len(vals):.1f} ({len(vals)} game-dates)")

    # Recompute adjusted ratings
    results = []
    for team_name, gr in team_game_ratings.items():
        in_sys = [g for g in gr if g.get("in_system")]
        if not in_sys:
            continue
        curr_ortg = sum(g["ortg"] for g in in_sys) / len(in_sys)
        curr_drtg = sum(g["drtg"] for g in in_sys) / len(in_sys)
        curr_net = curr_ortg - curr_drtg

        adj_ortgs = []
        adj_drtgs = []
        for g in in_sys:
            avg_on_date = date_avg.get(g["date"], season_avg)
            adj_ortgs.append(g["ortg"] - avg_on_date + season_avg)
            adj_drtgs.append(g["drtg"] - avg_on_date + season_avg)

        adj_ortg = sum(adj_ortgs) / len(adj_ortgs)
        adj_drtg = sum(adj_drtgs) / len(adj_drtgs)
        adj_net = adj_ortg - adj_drtg

        results.append({
            "team": team_name,
            "curr_net": round(curr_net, 1),
            "adj_net": round(adj_net, 1),
            "net_delta": round(adj_net - curr_net, 1),
        })

    # Show that NET doesn't change
    deltas = [r["net_delta"] for r in results]
    print(f"\n--- RESULT ---")
    print(f"  Max change: {max(abs(d) for d in deltas):.4f}")
    print(f"  Date-adjustment has NO effect on NET RTG (ORTG-DRTG cancels)")
    print(f"  It only matters for evaluating offense/defense independently")


if __name__ == "__main__":
    main()
