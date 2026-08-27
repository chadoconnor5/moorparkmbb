#!/usr/bin/env python3
"""Keep the two copies of the practice tracker byte-identical.

There are two on purpose:

  tracker/index.html                                  what GitHub Pages serves
  Neural Network - Codex Optimized/practice_tracker.html   the local editor copy

They are the SAME app. The only thing that separates them is that a pt_data.json
sits beside the published one, and loadPublishedData() treats that file's presence
as "this is the published site" - it sets _publishedMode and hides Live Tracker,
Publish and Backup. So the editor copy has to live in a folder without one, which
is why deleting it is not an option.

Keeping them in step by hand is what failed before: every commit for a fortnight
went to tracker/index.html only, and the editor copy fell about a thousand lines
behind without anyone noticing. This decides the direction from what actually
changed rather than assuming one side is always the source, because assuming
"published wins" would silently throw away an edit made in the editor copy.

  python tools/sync_tracker.py            report, and sync if the direction is clear
  python tools/sync_tracker.py --check    exit 1 if they differ, write nothing
  python tools/sync_tracker.py --pre-commit   as default, but stage the result
"""

import subprocess, sys, pathlib

PUBLISHED = 'tracker/index.html'
EDITOR    = 'Neural Network - Codex Optimized/practice_tracker.html'


def repo_root():
    out = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                         capture_output=True, text=True)
    if out.returncode:
        sys.exit('not inside a git repository')
    return pathlib.Path(out.stdout.strip())


def norm(b):
    """Compare on content, not line endings - core.autocrlf can hand back CRLF."""
    return None if b is None else b.replace(b'\r\n', b'\n')


def head_blob(rel):
    r = subprocess.run(['git', 'show', f'HEAD:{rel}'], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    root = repo_root()
    pub_p, ed_p = root / PUBLISHED, root / EDITOR

    for p in (pub_p, ed_p):
        if not p.exists():
            sys.exit(f'missing: {p}')

    pub, ed = norm(pub_p.read_bytes()), norm(ed_p.read_bytes())
    if pub == ed:
        print('tracker copies in sync')
        return 0

    if mode == '--check':
        print('DRIFT: the two tracker copies differ.', file=sys.stderr)
        print('  run: python tools/sync_tracker.py', file=sys.stderr)
        return 1

    pub_changed = pub != norm(head_blob(PUBLISHED))
    ed_changed  = ed  != norm(head_blob(EDITOR))

    if pub_changed and ed_changed:
        # Both edited, and to different content. Picking a winner here would throw
        # away real work, so this is the one case a human has to settle.
        print('DRIFT: both copies were edited and they do not match.', file=sys.stderr)
        print('  diff them and copy the one you want over the other, then commit.',
              file=sys.stderr)
        return 1

    if pub_changed:
        src, dst, rel = pub_p, ed_p, EDITOR
    elif ed_changed:
        src, dst, rel = ed_p, pub_p, PUBLISHED
    else:
        # Neither side changed in this commit yet they differ: drift that predates
        # this commit, so there is no "what you just edited" to infer from.
        print('DRIFT: copies differ but neither changed since HEAD.', file=sys.stderr)
        print('  copy the one you want over the other by hand, then commit.',
              file=sys.stderr)
        return 1

    dst.write_bytes(src.read_bytes())
    print(f'synced {src.relative_to(root)} -> {dst.relative_to(root)}')

    if mode == '--pre-commit':
        subprocess.run(['git', 'add', '--', rel], cwd=root, check=True)
        print(f'staged {rel}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
