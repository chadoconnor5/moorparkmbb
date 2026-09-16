#!/usr/bin/env python3
"""Print the shots that still have no shot-clock reading, practice by practice.

Shot-clock values are not captured by the Live Tracker. They get added to
tracker/pt_data.json by hand afterwards, by scrubbing the film to each shot and
reading the clock off the screen - which is why the commit log is full of things
like "Shot clock: the four unreadable shots in Fall Workout #14". The slow part
of that job is not typing the number, it is finding the shots that are still
untagged inside a 470-KB JSON file.

So this walks every session, keeps the field-goal attempts (free throws have no
shot clock, and a turnover has no shot to read), drops the ones that already
carry a shotClock, and lays the rest out as a worksheet: film timestamp first,
because that is what you scrub to, then enough about the shot - player, result,
type, spot on the floor - to be sure the film is showing the right possession.
The last column is deliberately blank, to write the number in.

Each row is labelled with the event id it came from, so a filled-in sheet maps
straight back to the entry in eventLog that needs the value.

    python3 tools/shot_clock_worklist.py                 # -> shot_clock_worklist.pdf
    python3 tools/shot_clock_worklist.py --out foo.pdf
    python3 tools/shot_clock_worklist.py --csv foo.csv   # same rows, for a spreadsheet
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "tracker" / "pt_data.json"

# A shot clock only means something on a field-goal attempt.
FGA = {"2fg_make", "2fg_miss", "3fg_make", "3fg_miss"}

CONTEST = {"contested": "Contested", "uncontested": "Open"}

RESULT = {
    "2fg_make": "2PT make",
    "2fg_miss": "2PT miss",
    "3fg_make": "3PT make",
    "3fg_miss": "3PT miss",
}

# eventLog stores region codes; these are the names the app shows for them.
ZONE = {
    "paint_ul": "Paint upper-left",
    "paint_ur": "Paint upper-right",
    "paint_ll": "Paint lower-left",
    "paint_lr": "Paint lower-right",
    "ft": "Free-throw area",
    "mr_left_high": "Mid-range left high",
    "mr_left_low": "Mid-range left low",
    "mr_right_high": "Mid-range right high",
    "mr_right_low": "Mid-range right low",
    "w3_left": "Left wing 3",
    "w3_right": "Right wing 3",
    "c3_left": "Left corner 3",
    "c3_right": "Right corner 3",
    "ab3": "Above the break 3",
}

NAVY = colors.HexColor("#1f2a44")
RULE = colors.HexColor("#c9d1e0")
BAND = colors.HexColor("#eef2f9")


def film_time(seconds: float | None) -> str:
    """Film position as h:mm:ss - what you type into the player's seek box."""
    if seconds is None:
        return "--"
    total = int(round(seconds))
    return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def pretty_date(iso: str) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%a %b %-d, %Y")
    except ValueError:
        return iso


def collect(data: dict, skip_hidden: bool = False) -> list[dict]:
    """One entry per practice, newest first, carrying its untagged attempts."""
    hidden = {p["name"] for p in data.get("roster", []) if p.get("hidden")}
    practices = []
    for session in sorted(data["sessions"], key=lambda s: s.get("date", ""), reverse=True):
        teams = {"a": session.get("teamAName", "A"), "b": session.get("teamBName", "B")}
        attempts = [e for e in session["eventLog"] if e.get("stat") in FGA]
        rows = []
        for event in attempts:
            if event.get("shotClock") is not None:
                continue
            # Players hidden from the published site are usually no longer around;
            # their shots are still listed, just flagged, unless you ask to drop them.
            is_hidden = event.get("player") in hidden
            if is_hidden and skip_hidden:
                continue
            types = event.get("shotTypes") or ([event["shotType"]] if event.get("shotType") else [])
            rows.append(
                {
                    "session": session.get("title", ""),
                    "date": session.get("date", ""),
                    "event_id": event.get("id"),
                    "quarter": event.get("quarter"),
                    "video_ts": event.get("videoTs"),
                    "team": teams.get(event.get("team"), event.get("team")),
                    "player": event.get("player") or "",
                    "result": RESULT.get(event["stat"], event["stat"]),
                    "shot_type": ", ".join(t.replace("_", " ") for t in types),
                    "spot": ZONE.get(event.get("zone"), event.get("zone") or ""),
                    "distance_ft": event.get("shotFt"),
                    "contest": event.get("shotContest") or "",
                    "hidden": is_hidden,
                }
            )
        rows.sort(key=lambda r: (r["quarter"] or 0, r["video_ts"] or 0))
        practices.append(
            {
                "title": session.get("title", ""),
                "date": session.get("date", ""),
                "attempts": len(attempts),
                "tagged": sum(1 for e in attempts if e.get("shotClock") is not None),
                "hidden": sum(1 for r in rows if r["hidden"]),
                "rows": rows,
            }
        )
    return practices


def build_pdf(practices: list[dict], out: Path, published_at: str) -> None:
    sheet = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=sheet["BodyText"], fontSize=9, leading=12)
    cell = ParagraphStyle("cell", parent=sheet["BodyText"], fontSize=7.5, leading=9.5)
    head = ParagraphStyle(
        "head", parent=sheet["Heading2"], fontSize=13, leading=16, textColor=NAVY, spaceAfter=2
    )
    sub = ParagraphStyle("sub", parent=sheet["BodyText"], fontSize=8.5, leading=11,
                         textColor=colors.HexColor("#5b6478"))
    qhead = ParagraphStyle("qhead", parent=sheet["BodyText"], fontSize=9.5, leading=12,
                           textColor=NAVY, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=2)
    centered = ParagraphStyle("centered", parent=cell, alignment=TA_CENTER)

    outstanding = sum(len(p["rows"]) for p in practices)
    hidden_total = sum(p["hidden"] for p in practices)

    def furniture(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#8b93a5"))
        canvas.drawString(0.6 * inch, 0.45 * inch, "Moorpark MBB - shot-clock readings still needed")
        canvas.drawRightString(7.9 * inch, 0.45 * inch, f"page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc = BaseDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.7 * inch,
        title="Shot-clock readings still needed",
        author="Moorpark MBB practice tracker",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=furniture)])

    story = [
        Paragraph("Shot-clock readings still needed", sheet["Title"]),
        Paragraph(
            f"Every field-goal attempt in the practice tracker that has no shot clock on it yet - "
            f"<b>{outstanding}</b> shots across {len(practices)} practices. Free throws are left out "
            f"(no clock to read) and so is anything already tagged. Scrub the film to the time in the "
            f"first column, read the clock, and write it in the last one. "
            f"The # column is the event id inside that practice's eventLog, so a filled-in sheet "
            f"maps straight back to the entry that needs the value. Data snapshot published "
            f"{published_at[:10]}.",
            body,
        ),
        Spacer(1, 6),
        Paragraph(
            f"<i>{hidden_total} of those shots belong to players hidden from the published site; "
            f"they are marked (hidden) in the Player column. Re-run with --skip-hidden to leave "
            f"them out.</i>" if hidden_total else "",
            body,
        ),
        Spacer(1, 14),
        Paragraph("What each practice still owes", qhead),
    ]

    summary = [["Practice", "Date", "Attempts", "Tagged", "Still needed"]]
    for p in practices:
        summary.append(
            [
                Paragraph(p["title"], cell),
                pretty_date(p["date"]),
                str(p["attempts"]),
                str(p["tagged"]),
                str(len(p["rows"])),
            ]
        )
    summary.append(
        [
            "TOTAL",
            "",
            str(sum(p["attempts"] for p in practices)),
            str(sum(p["tagged"] for p in practices)),
            str(outstanding),
        ]
    )
    table = Table(summary, colWidths=[2.9 * inch, 1.6 * inch, 0.9 * inch, 0.8 * inch, 1.1 * inch],
                  repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (2, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, RULE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BAND]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)

    widths = [0.65 * inch, 0.4 * inch, 0.55 * inch, 1.35 * inch, 0.65 * inch, 1.1 * inch,
              1.25 * inch, 0.72 * inch, 0.63 * inch]
    header = ["Film", "#", "Team", "Player", "Result", "Shot type", "Spot", "Contest", "Clock"]

    for practice in practices:
        story.append(PageBreak())
        story.append(Paragraph(practice["title"], head))
        story.append(
            Paragraph(
                f"{pretty_date(practice['date'])} &nbsp;·&nbsp; "
                f"{len(practice['rows'])} of {practice['attempts']} attempts still need a reading"
                + (f" &nbsp;·&nbsp; {practice['tagged']} already tagged" if practice["tagged"] else ""),
                sub,
            )
        )
        if not practice["rows"]:
            story.append(Spacer(1, 10))
            story.append(Paragraph("Nothing outstanding - every attempt is tagged.", body))
            continue

        quarters = sorted({r["quarter"] for r in practice["rows"]}, key=lambda q: q or 0)
        for quarter in quarters:
            rows = [r for r in practice["rows"] if r["quarter"] == quarter]
            story.append(Paragraph(f"Period {quarter} &nbsp;—&nbsp; {len(rows)} shots", qhead))
            body_rows = [header]
            for r in rows:
                dist = f" · {r['distance_ft']:.0f} ft" if r["distance_ft"] is not None else ""
                body_rows.append(
                    [
                        Paragraph(film_time(r["video_ts"]), cell),
                        Paragraph(str(r["event_id"]), centered),
                        Paragraph(r["team"], cell),
                        Paragraph(r["player"] + (" (hidden)" if r["hidden"] else ""), cell),
                        Paragraph(r["result"], cell),
                        Paragraph(r["shot_type"], cell),
                        Paragraph(f"{r['spot']}{dist}", cell),
                        Paragraph(CONTEST.get(r["contest"], r["contest"]), cell),
                        "",
                    ]
                )
            t = Table(body_rows, colWidths=widths, repeatRows=1)
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
                        ("BACKGROUND", (-1, 1), (-1, -1), colors.HexColor("#fffdf2")),
                        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                    ]
                )
            )
            story.append(t)

    doc.build(story)


def write_csv(practices: list[dict], out: Path) -> None:
    fields = ["session", "date", "event_id", "quarter", "video_ts", "film_time", "team",
              "player", "hidden", "result", "shot_type", "spot", "distance_ft", "contest",
              "shot_clock"]
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for practice in practices:
            for row in practice["rows"]:
                writer.writerow({**row, "film_time": film_time(row["video_ts"]), "shot_clock": ""})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--out", type=Path, default=REPO / "shot_clock_worklist.pdf")
    ap.add_argument("--csv", type=Path, help="also write the same rows as CSV")
    ap.add_argument("--skip-hidden", action="store_true",
                    help="leave out shots by players hidden from the published site")
    args = ap.parse_args()

    data = json.loads(args.data.read_text())
    practices = collect(data, skip_hidden=args.skip_hidden)
    build_pdf(practices, args.out, data.get("publishedAt", ""))
    print(f"{sum(len(p['rows']) for p in practices)} shots still need a reading -> {args.out}")
    if args.csv:
        write_csv(practices, args.csv)
        print(f"rows also written to {args.csv}")


if __name__ == "__main__":
    main()
