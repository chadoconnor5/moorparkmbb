"""Synergy roles: a player's offensive role from his Synergy play-type mix (a player page's scoring summary), split by
position: 8 guard / wing roles and 4 big roles, modeled on a published NBA role framework (BBall Index-inspired role
profiles). Each role is its typical play-type mix (PROFILES, share of all his possessions) plus hard gates that rule a
role out (a big who never spots up can't be a Versatile Big; a Shot Creator lives in isolation, not the pick-and-roll).
A player gets the closest role (sum of the differences from its mix) among the roles his gates allow.

Position: the box-score position (hoop-explorer: S-PF, PF/C, C are bigs), else the roster's listed position (C, PF, F/C),
else the mix itself (post-ups, rolls and putbacks against ball handling, isolation, off-screen and handoff plays).
"""
import re

KEYS = ("pnr_bh", "iso", "transition", "spotup", "offscreen", "handoff", "cut", "roll", "putback", "postup")

GUARD = {
    "Primary Ball Handler": {"pnr_bh": 30, "transition": 20, "iso": 12, "spotup": 8, "handoff": 6, "postup": 2},
    "Secondary Ball Handler": {"pnr_bh": 18, "spotup": 18, "transition": 15, "iso": 7, "handoff": 7},
    "Shot Creator": {"iso": 25, "pnr_bh": 20, "transition": 15, "handoff": 8, "spotup": 8, "postup": 5},
    "Slasher": {"transition": 25, "cut": 18, "iso": 15, "pnr_bh": 10, "spotup": 8, "offscreen": 2},
    "Athletic Finisher": {"cut": 28, "transition": 18, "putback": 15, "roll": 12, "spotup": 8, "iso": 3},
    "Off Screen Shooter": {"offscreen": 28, "spotup": 20, "handoff": 18, "transition": 10, "iso": 3, "pnr_bh": 3},
    "Movement Shooter": {"spotup": 28, "offscreen": 12, "transition": 12, "handoff": 10, "cut": 10, "iso": 3},
    "Stationary Shooter": {"spotup": 42, "transition": 8, "offscreen": 6, "handoff": 6, "cut": 3, "iso": 3},
}
BIG = {
    "Versatile Big": {"spotup": 18, "postup": 18, "roll": 16, "cut": 12, "putback": 10, "handoff": 8, "pnr_bh": 6},
    "Post Scorer": {"postup": 30, "roll": 14, "cut": 12, "putback": 12, "transition": 10, "spotup": 6},
    "Stretch Big": {"spotup": 38, "roll": 14, "putback": 6, "cut": 6, "postup": 4, "pnr_bh": 2},
    "Roll & Cut Big": {"roll": 30, "cut": 25, "putback": 18, "transition": 12, "postup": 4, "spotup": 3},
}
PROFILES = {**GUARD, **BIG}
DESCRIBE = {
    "Primary Ball Handler": "Primary initiator through the pick-and-roll and transition",
    "Secondary Ball Handler": "Complementary creator: some pick-and-roll, less initiation than a primary",
    "Shot Creator": "Creates his own shot; isolation over the pick-and-roll",
    "Slasher": "Gets to the rim through drives and transition",
    "Athletic Finisher": "Off-ball damage: cutting, crashing the glass, activity without the ball",
    "Off Screen Shooter": "Runs off designed screens to get open",
    "Movement Shooter": "Relocates to find space; shots come from movement",
    "Stationary Shooter": "Catch-and-shoot specialist who waits for the ball",
    "Versatile Big": "Does everything: shoots, posts, rolls, cuts; no single play type dominates",
    "Post Scorer": "Post-ups dominate his offense",
    "Stretch Big": "Floor-spacing big: spot-ups dominate",
    "Roll & Cut Big": "No perimeter game: rolling, cutting and crashing",
}

BIG_POS = {"S-PF", "PF/C", "C"}                       # box-score positions (compute_positions_from_boxscore)
GUARD_POS = {"PG", "s-PG", "CG", "WG", "WF", "G", "SG", "G/F", "W"}
ROSTER_BIG = {"C", "PF", "F/C", "C/F", "PF/C", "POST", "B"}
ROSTER_GUARD = {"G", "PG", "SG", "G/F", "W", "WING", "GUARD"}

_PATS = [("spotup", r"spot ?ups?|spots up"), ("pnr_bh", r"p&?r bh|pick.?and.?roll bh|p&?r ball ?handler"),
         ("postup", r"post.?ups?"), ("iso", r"isolation|iso\b"), ("transition", r"transition"),
         ("offscreen", r"off.?screens?"), ("handoff", r"hand.?offs?|dho"), ("cut", r"\bcuts?"),
         ("roll", r"roll man|p&?r man|p&?r roll"), ("putback", r"put.?backs?")]


def play_types(summary):
    """{'spotup': 34, 'transition': 17, ...} from a player page's scoring summary ("Spot Up 22% (0.875 PPP) · ...")."""
    s = (summary or "").lower()
    out = {}
    for part in re.split(r"·|·|;", s):
        for k, pat in _PATS:
            m = re.search("(?:" + pat + r")[^0-9%]{0,24}?~?(\d+(?:\.\d+)?)\s*%", part)
            if m and k not in out:
                out[k] = float(m.group(1))
                break
    return out


def is_big(pos=None, roster_pos=None, pt=None):
    p = (pos or "").strip()
    if p in BIG_POS:
        return True
    if p in GUARD_POS:
        return False
    r = (roster_pos or "").strip().upper()
    if r in ROSTER_BIG:
        return True
    if r in ROSTER_GUARD:
        return False
    g = lambda k: (pt or {}).get(k, 0)
    return g("postup") + g("roll") + g("putback") > g("pnr_bh") + g("iso") + g("offscreen") + g("handoff") + 0.5 * g("spotup")


def _creation(c):
    """From the play-by-play counts (pbp_creation): (share of his makes unassisted, share of made threes assisted,
    share of rim makes assisted, putback share of his shots), each None below its sample (10 makes, 5 threes, 5 rim)."""
    if not c:
        return None, None, None, None
    ua = 100.0 * c["unast_m"] / c["fgm"] if c.get("fgm", 0) >= 10 else None
    a3 = 100.0 * c["three_ast"] / c["three_m"] if c.get("three_m", 0) >= 5 else None
    arim = 100.0 * c["rim_ast"] / c["rim_m"] if c.get("rim_m", 0) >= 5 else None
    pb = 100.0 * c["putback_a"] / c["fga"] if c.get("fga", 0) >= 15 else None
    return ua, a3, arim, pb


def _gates(pt, big, ast_rate=None, rim=None, three_par=None, drive_rate=None, spot_drive=None, pbp=None):
    """The roles his mix allows (hard disqualifiers). three_par: 3PA / FGA (%, box score); drive_rate: drives / his
    possessions (%, player page); spot_drive: share of his spot-ups that are drives, not shots (%, player page)."""
    g = lambda k: pt.get(k, 0)
    # Shoot or drive: a low 3PA rate with a real rim share or drive rate, or spot-ups that are mostly drives, is a slasher's
    # profile; his spot-ups are attacks off the catch, not shots, so he is no shooter.
    driver = (three_par is not None and three_par <= 25 and ((rim or 0) >= 45 or (drive_rate or 0) >= 30)) \
        or (spot_drive is not None and spot_drive >= 50)
    shooter_ok = not driver and (three_par is None or three_par >= 30)
    # Who creates the shot (play-by-play): creators make shots on their own (the state: 51% of makes unassisted),
    # shooters are set up (83% of made threes assisted). Not used for finishers: their putbacks are unassisted rim makes
    # and the play-by-play misses most putbacks (4% of the state's shots; 11/11 Michael Baba, 27% putbacks by Synergy,
    # 1 by the play-by-play).
    ua, a3, arim, pb = _creation(pbp)
    creator_ok = ua is None or ua >= 55
    shooter_ok = shooter_ok and (a3 is None or a3 >= 70)
    half = {k: g(k) for k in KEYS if k != "transition"}   # half-court play types
    top = max(half, key=half.get) if half else None
    ok = set()
    if big:
        if g("spotup") >= 8 and g("postup") + g("roll") + g("cut") + g("putback") >= 15 and max(half.values() or [0]) < 30:
            ok.add("Versatile Big")
        if top == "postup" and g("postup") >= 15:
            ok.add("Post Scorer")
        if top == "spotup" and g("spotup") >= 25 and (a3 is None or a3 >= 70):
            ok.add("Stretch Big")
        if (g("roll") + g("cut") + g("putback") >= 30 and g("spotup") < 15 and g("roll") + g("cut") + g("putback") > g("postup")
                ):
            ok.add("Roll & Cut Big")
        return ok
    create = g("pnr_bh") + g("iso")
    if g("pnr_bh") >= 22 and g("pnr_bh") >= g("iso") and (ast_rate is None or ast_rate >= 18) and creator_ok:
        ok.add("Primary Ball Handler")
    if g("pnr_bh") >= 10 and g("pnr_bh") >= g("iso") * 0.75 and "Primary Ball Handler" not in ok:
        ok.add("Secondary Ball Handler")   # a primary's initiation (P&R 22%+, assist rate 18+) decides it over secondary
    if g("iso") >= 15 and g("iso") >= 0.75 * g("pnr_bh") and create >= 25 and creator_ok:
        ok.add("Shot Creator")
    if (g("transition") + g("cut") + g("iso") >= 35 and g("spotup") < 30 and (rim is None or rim >= 35)
            and (three_par is None or three_par < 45 or (spot_drive or 0) >= 50)) or driver:
        ok.add("Slasher")
    if g("cut") + g("putback") + g("roll") >= 25 and create < 15:
        ok.add("Athletic Finisher")
    if g("offscreen") >= 15 and shooter_ok:
        ok.add("Off Screen Shooter")
    if g("spotup") >= 20 and g("offscreen") + g("handoff") + g("cut") >= 15 and create < 25 and shooter_ok:
        ok.add("Movement Shooter")
    if g("spotup") >= 30 and g("offscreen") + g("handoff") < 15 and create < 20 and shooter_ok:
        ok.add("Stationary Shooter")
    return ok


def _vetoed(three_par, pbp, rim=None, drive_rate=None, spot_drive=None):
    """Roles his shooting rules out even when no role's gate passes: no shooter without the threes (or with them
    unassisted), no creator whose makes are set up for him."""
    ua, a3, _, _ = _creation(pbp)
    out = set()
    driver = (three_par is not None and three_par <= 25 and ((rim or 0) >= 45 or (drive_rate or 0) >= 30)) or (spot_drive or 0) >= 50
    if driver or (three_par is not None and three_par < 30) or (a3 is not None and a3 < 70):
        out |= {"Off Screen Shooter", "Movement Shooter", "Stationary Shooter"}
    if a3 is not None and a3 < 70:
        out.add("Stretch Big")
    if ua is not None and ua < 55:
        out |= {"Primary Ball Handler", "Shot Creator"}
    return out


def _dist(pt, prof):
    return sum(abs(pt.get(k, 0) - prof.get(k, 0)) for k in KEYS)


def role(summary, pos=None, roster_pos=None, ast_rate=None, rim=None, three_par=None, drive_rate=None, spot_drive=None,
         pbp=None):
    """The player's role from his scoring summary, or None without a play-type mix. ast_rate (assist rate) is the
    initiation check for a Primary Ball Handler; rim (share of his shots at the rim), three_par, drive_rate and
    spot_drive tell a Slasher from a shooter; pbp (pbp_creation counts) who creates his shots (see _gates)."""
    pt = play_types(summary)
    if sum(pt.values()) < 20:
        return None
    big = is_big(pos, roster_pos, pt)
    group = BIG if big else GUARD
    allowed = _gates(pt, big, ast_rate, rim, three_par, drive_rate, spot_drive, pbp) or (set(group) - _vetoed(three_par, pbp, rim, drive_rate, spot_drive))
    allowed = allowed or set(group)
    return min(allowed, key=lambda r: _dist(pt, group[r]))


def roster_positions(team, season):
    """{player name: listed position} from the typed-in roster (<season> Rosters/<conf>/<team>/roster.json), for
    players without a box-score position yet."""
    import json
    from pathlib import Path
    here = Path(__file__).resolve().parent
    out = {}
    for f in here.glob(f"{season} Rosters/*/{team}/roster.json"):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for p in (d.get("players") if isinstance(d, dict) else d) or []:
            nm = f"{p.get('first', '')} {p.get('last', '')}".strip() or p.get("name") or ""
            if nm:
                out[nm] = p.get("site_position") or p.get("pos") or ""
    return out


def page_inputs(sa, tot=None):
    """(three_par, drive_rate, spot_drive) from a player page (sa) and his box-score totals."""
    tot = tot or {}
    fga = tot.get("FGA") or 0
    three_par = 100.0 * (tot.get("3PA") or 0) / fga if fga >= 10 else None
    dd, ov = (sa or {}).get("drive_direction") or {}, (sa or {}).get("overall") or {}
    drives = dd.get("drives_poss") or sum((dd.get(k) or 0) for k in ("drives_left_poss", "drives_right_poss", "drives_straight_poss"))
    drive_rate = 100.0 * drives / ov["poss"] if drives and ov.get("poss") else None
    su = (sa or {}).get("spot_up") or {}
    return three_par, drive_rate, su.get("drive_pct")


def creation_line(c):
    """The report's play-by-play line: "Play-by-play (9 makes): 67% of makes unassisted · 3 of 4 threes assisted · ..."."""
    if not c or not c.get("fga"):
        return ""
    parts = []
    if c["fgm"]:
        parts.append(f'{round(100 * c["unast_m"] / c["fgm"])}% of makes unassisted')
    if c["rim_m"]:
        parts.append(f'{c["rim_ast"]} of {c["rim_m"]} rim makes assisted')
    if c["three_m"]:
        parts.append(f'{c["three_ast"]} of {c["three_m"]} made threes assisted')
    parts.append(f'{round(100 * c["trans_a"] / c["fga"])}% of shots in transition')
    if c["putback_a"]:
        parts.append(f'{c["putback_a"]} putback{"s" if c["putback_a"] != 1 else ""}')
    return f'Play-by-play ({c["games"]} games, {c["fga"]} shots): ' + " · ".join(parts)
