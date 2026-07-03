#!/usr/bin/env python3
"""
lint_scouting_prose.py — guardrail for the data scouting reports.

Scans a report generator's source for (a) COACHING DIRECTIVES (telling the
opponent what to do) and (b) FILM INFERENCES (asserting scheme / structure /
intent the box score can't see). Both are banned: the reports are descriptive
data only. Prints every offending line; exits non-zero if any are found, so it
can gate a build.  Run: /usr/local/bin/python3 lint_scouting_prose.py [file ...]
"""
import re, sys

# Coaching directives — imperative "what the opponent should do" language.
DIRECTIVE = [
    r'\bsag off\b', r'\bstay attached\b', r'\bsend traps?\b', r'\bcontest (?:his|their|the)\b',
    r'\btrack(?:ed)? (?:him|them|\w+) off.?ball\b', r'\bdisrupt (?:his|the|castaniero)',
    r'\bget into the paint\b', r'\bbox[- ]?out\b', r'\binvite (?:him|them)\b',
    r'\bcut off (?:his|the)\b', r'\bdouble the\b', r'\bwall up\b', r'\byou should\b',
    r'\byou can afford\b', r'\bthe blueprint\b', r'\bmust be tracked\b', r'\bscheme to\b',
    r'\bforce (?:him|them|his|moorpark) (?:into|off|right|to|out)\b', r'\battack the rim\b',
    r'\bpush (?:in|the) (?:transition|pace|game)\b', r'\brun him off\b', r'\bfunnel\b',
    r'\bshade (?:help|left|right|to)\b', r'\bexploit (?:it|this|him|the|that)\b',
    r'\bmake (?:him|them|castaniero) (?:a scorer|beat)\b', r'\bdraw fouls on\b',
    r'\bassign (?:a|specific)\b', r'\bpush the pace\b',
]
# Film inferences — scheme/structure/intent the box score cannot see.
FILM = [
    r'\bdefensive structure\b', r'\bdefensive DNA\b', r'\bdefensive identity\b',
    r'\bset[- ]?up oriented\b', r'\bby design\b', r'\bdesigned to\b', r'\bneutraliz\w+\b',
    r'\bin rhythm\b', r'\btheir scheme\b',
]
# Hedge filler — narrating what the data CAN'T do. State the fact and stop.
HEDGE = [
    r'\bfilm question\b', r'\bneeds? film\b', r'\bwould need film\b', r'\bmechanism needs\b',
    r'\bthese numbers cannot\b', r'\bnot something these numbers\b', r'\bneed film to confirm\b',
    r'\bbut not (?:the cause|why)\b', r'\bregardless of cause\b',
]
SAFE = ('forces', 'forced into', 'enforce', 'reinforce')   # allowed contexts

def lint(path):
    hits = []
    for i, line in enumerate(open(path, encoding='utf-8'), 1):
        s = line.strip()
        if s.startswith('#') or 'DIRECTIVE = [' in line or 'FILM = [' in line:
            continue
        low = line.lower()
        if any(w in low for w in SAFE) and 'defensive' not in low:
            continue
        for kind, pats in (('DIRECTIVE', DIRECTIVE), ('FILM', FILM), ('HEDGE', HEDGE)):
            for p in pats:
                m = re.search(p, low)
                if m:
                    hits.append((i, kind, m.group(0), s[:110]))
                    break
    return hits

def main():
    files = sys.argv[1:] or ['generate_moorpark_scouting_report.py']
    total = 0
    for f in files:
        hits = lint(f)
        total += len(hits)
        print(f"\n=== {f}: {len(hits)} issues ===")
        for ln, kind, hit, snip in hits:
            print(f"  L{ln:<5} [{kind:9}] '{hit}'  ::  {snip}")
    print(f"\nTOTAL: {total} prose issues")
    sys.exit(1 if total else 0)

if __name__ == '__main__':
    main()
