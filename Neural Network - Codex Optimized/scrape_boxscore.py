"""Scrape basketball box score from CCCMBCA page."""
import re
import json
from html.parser import HTMLParser


class BoxScoreParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_td = False
        self.in_th = False
        self.current_text = ""
        self.rows = []
        self.current_row = []
        self.in_stats_box = False
        self.current_team = None
        self.in_row_head = False
        self.teams = {}
        self.depth = 0
        self.stats_box_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        if tag == "div":
            self.depth += 1
            if "stats-box" in cls and "lineup" in cls:
                self.in_stats_box = True
                self.stats_box_depth = self.depth
                if "visitor" in cls:
                    self.current_team = "visitor"
                elif "home" in cls:
                    self.current_team = "home"
                self.rows = []

        if tag == "td":
            self.in_td = True
            self.current_text = ""
        if tag == "th":
            self.in_th = True
            self.current_text = ""
            if "row-head" in cls:
                self.in_row_head = True
        if tag == "tr":
            self.current_row = []

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_td = False
            self.current_row.append(self.current_text.strip())
        if tag == "th":
            self.in_th = False
            txt = self.current_text.strip()
            if txt:
                self.current_row.append(txt)
            self.in_row_head = False
        if tag == "tr" and self.current_row:
            self.rows.append(self.current_row)
        if tag == "div":
            if self.in_stats_box and self.depth == self.stats_box_depth:
                if self.current_team:
                    self.teams[self.current_team] = self.rows[:]
                self.in_stats_box = False
                self.current_team = None
            self.depth -= 1

    def handle_data(self, data):
        if self.in_td or self.in_th:
            self.current_text += data


def main():
    with open("/tmp/boxscore.html") as f:
        html = f.read()

    parser = BoxScoreParser()
    parser.feed(html)

    # Extract game score from the linescore section
    score_match = re.findall(
        r'<td class="score">(\d+)</td>', html
    )
    total_match = re.findall(
        r'<td class="score total">(\d+)</td>', html
    )

    team_names = {"visitor": "Irvine Valley", "home": "Moorpark"}
    headers = ["Player", "MIN", "FGM-A", "3PM-A", "FTM-A", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "PTS"]

    print("=" * 80)
    print("IRVINE VALLEY vs MOORPARK - Box Score - 2/25/2026")
    if score_match and total_match:
        print(f"Irvine Valley: {score_match[0]} + {score_match[1]} = {total_match[0]}")
        print(f"Moorpark:      {score_match[2]} + {score_match[3]} = {total_match[1]}")
    print("=" * 80)

    all_data = {}

    for team_key in ["visitor", "home"]:
        if team_key not in parser.teams:
            print(f"\nNo data found for {team_names[team_key]}")
            continue

        rows = parser.teams[team_key]
        name = team_names[team_key]
        print(f"\n{'=' * 80}")
        print(f"  {name.upper()}")
        print(f"{'=' * 80}")

        # Print header
        print(f"{'Player':<30} {'MIN':>4} {'FGM-A':>6} {'3PM-A':>6} {'FTM-A':>6} {'OREB':>4} {'DREB':>4} {'REB':>4} {'AST':>4} {'STL':>4} {'BLK':>4} {'TO':>4} {'PF':>4} {'PTS':>4}")
        print("-" * 120)

        team_players = []
        for row in rows:
            cleaned = [c.strip() for c in row if c.strip()]
            if not cleaned:
                continue

            # Section headers like STARTERS, RESERVES
            if len(cleaned) == 1 and cleaned[0] in ("STARTERS", "RESERVES", "TEAM"):
                print(f"\n  {cleaned[0]}")
                print("-" * 120)
                continue

            # Totals row
            if cleaned[0] in ("TOTALS", "Totals", "TOTAL"):
                print("-" * 120)
                vals = cleaned
                line = f"{'TOTALS':<30}"
                for i, v in enumerate(vals[1:]):
                    line += f" {v:>5}" if i == 0 else f" {v:>6}" if i < 4 else f" {v:>4}"
                print(line)
                continue

            # Player row: name + 13 stats
            if len(cleaned) >= 10:
                # First element is player name (possibly with number)
                player = cleaned[0]
                stats = cleaned[1:]
                line = f"{player:<30}"
                for i, v in enumerate(stats):
                    if i == 0:
                        line += f" {v:>4}"
                    elif i < 4:
                        line += f" {v:>6}"
                    else:
                        line += f" {v:>4}"
                print(line)
                team_players.append({"name": player, "stats": dict(zip(headers[1:], stats))})

        all_data[name] = team_players

    # Save as JSON
    output = {
        "game": "Irvine Valley vs Moorpark",
        "date": "2/25/2026",
        "score": {},
        "teams": all_data
    }
    if total_match:
        output["score"] = {
            "Irvine Valley": int(total_match[0]),
            "Moorpark": int(total_match[1])
        }

    with open("boxscore_data.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n\nData saved to boxscore_data.json")


if __name__ == "__main__":
    main()
