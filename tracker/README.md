# Moorpark MBB Practice Tracker — published site

Live URL: https://chadoconnor5.github.io/moorparkmbb/tracker/

## How this works

- `index.html` — the app (published copy).
- `pt_data.json` — the published data snapshot the site reads.

The app decides its role at load time:

- **Editor (Chad's browser):** local practice data exists in `localStorage`, so it is used and the
  full app is available (Live Tracker, Publish, Backup).
- **Viewer (anyone else):** no local data, so the app fetches `pt_data.json` and renders it
  read-only. Live Tracker / Publish / Backup are hidden.

Note: this is UI-level gating, not real security. The code still ships in the file and the
tracker password is in the source, so it stops casual use, not a determined viewer.

## Updating the live site

1. Track your practice as usual (Live Tracker on your own machine).
2. Click **↑ Publish** in the nav, enter the password → `pt_data.json` downloads.
3. Replace `tracker/pt_data.json` in this repo with the downloaded file.
4. Commit and push:

   ```bash
   git add tracker/pt_data.json && git commit -m "Update practice data" && git push
   ```

GitHub Pages redeploys in about a minute; viewers see the update on refresh.

## Updating the app itself (after code changes)

The published copy is `tracker/index.html`. After editing
`Neural Network - Codex Optimized/practice_tracker.html`, copy it over:

```bash
cp "Neural Network - Codex Optimized/practice_tracker.html" tracker/index.html
```

then commit and push.
