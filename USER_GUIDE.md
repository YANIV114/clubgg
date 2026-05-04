# ClubGG Analytics — User Guide

## Starting and Stopping the App

**Start:**
```bash
cd ~/claude\ project/clubgg
uv run uvicorn app.main:app --reload --port 8000
```
Open **http://localhost:8000** in your browser.

**Stop:** Press `Ctrl+C` in the terminal.

**Database must be running** before starting. If PostgreSQL isn't running:
```bash
brew services start postgresql  # macOS
```

---

## Importing ClubGG Hand History Files

1. Open the **Import** tab.
2. Drag one or more `.txt` ClubGG export files onto the drop zone, or click to browse.
3. Click **Import Files**.
4. When complete, a summary shows hands imported, duplicates skipped, and any parse errors.
5. A **player picker** appears below the summary — click any player to load them immediately.

**Getting export files from ClubGG:**
In the ClubGG app go to **History → Export Hand History** and save the `.txt` file. Files are named like `GG20260404-1650 - .txt`.

Re-uploading the same file is always safe — duplicates are skipped automatically.

---

## Selecting a Player

**After import:** Click any player in the post-import picker. Players are sorted by hand count.

**From the header:** Paste a player UUID into the input field and press Enter or click **Load Player**.

**Recent players:** Click the **▾** button next to the input to open the recent players dropdown. Click any entry to load them instantly. Click **Clear history** to remove all recents.

**Finding your UUID:**
```
psql clubgg -c "SELECT id, username FROM players ORDER BY username;"
```
Or use the player picker after your first import — your username is "Hero".

---

## Stats Tab

Shows aggregate stats for the loaded player across all imported hands.

| Stat | What it means |
|---|---|
| VPIP | % of hands voluntarily entered. High = playing too many marginal hands. |
| PFR | Preflop raise %. Should track close to VPIP. Low = passive. |
| 3-Bet % | 3-bet frequency. Too low = easy to steal against. |
| Fold to 3-Bet | % folded to 3-bets. Above 68% is exploitable. |
| WTSD | Went to showdown %. High = calling too many rivers. |
| WSD | Won at showdown %. Low with high WTSD = calling too loose. |
| Steal % | Combined BTN+CO+SB steal frequency. |

**Color coding:** Green = in optimal range, Yellow = borderline, Red = leak.

**Positional breakdown:** Click any position row to see stats, explanations, detected leaks, and hand examples for that position. Click **Drill leaks →** to jump straight into targeted drills.

**Reliability badge:** Stats with n < 20 are low confidence. 200+ hands gives reliable estimates.

**Export report:** Click the **Export Report** link (top right of stats) to download a printable HTML report.

---

## Leaks Tab

Shows all detected leaks ranked by priority (severity × exploitability).

- **Filter pills** (All / High / Medium / Low) narrow by severity.
- Each card shows: what you're doing wrong, evidence, suggested fix, and confidence level.
- Click **▶ Explanation** or **▶ Suggested Fix** to expand detail.
- **Hand examples** appear at the bottom of each card when real hands support the finding.
- Click **Replay hand →** on any example to open the hand replay.

**Hand replay:** Shows the table, action sequence, and pauses at your decision point. Choose your action, then see what you actually did and why it's weak. Use **← / →** to navigate between examples of the same leak.

---

## Trainer Tab

Targeted preflop drills based on your detected leaks.

1. Click **Start Drill Session** to begin.
2. Each drill presents a scenario — position, stack depth, action facing you.
3. Choose your action. Correct answers are shown with explanation.
4. Session ends with a score, per-leak breakdown, and missed spots to revisit.

**Missed spots** from previous sessions are automatically prioritised at the start of the next session.

---

## Daily Coach

A structured 10-minute daily session.

1. From the **Home** tab, click **Daily Coach**.
2. The plan screen shows: today's focus leak, estimated time, missed replays to revisit, and a numbered plan.
3. Click **Start session →** to begin.
4. Complete the session normally through the trainer.
5. The finish screen shows your grade, streak, per-area breakdown, and tomorrow's recommended focus.

Click **Regular trainer instead** on the plan screen to skip to the normal trainer start screen.

---

## Tournament Plan Tab

Generates a stage-by-stage study plan for a specific tournament format.

1. Select **Tournament Format** (Freezeout, Re-entry, PKO, Satellite, Spin & Go).
2. Select **Tournament Stage** (Early / Middle / Bubble / In the Money / Final Table).
3. Click **Generate Plan**.

The plan synthesises your detected leaks into stage-specific priorities — e.g., bubble ICM considerations, final-table push/fold, PKO bounty adjustments.

---

## Progress Tab

Visualises your training history from localStorage (no server required).

- **KPIs:** Sessions completed, all-time accuracy, total drills, current daily streak.
- **Accuracy sparkline:** Last 10 sessions plotted.
- **Weakest area / Most improved:** Derived from cumulative per-leak drill results.
- **Leak category table:** Accuracy % per leak with a trend arrow comparing last session to prior history.
- **Recent mistake trends:** Which leaks you miss most often (last 30 mistakes).
- **Session history:** Last 10 sessions with date and score.

Progress resets if browser localStorage is cleared.

---

## Exporting a Player Report

Click **Export Report** in the Stats tab, or visit:
```
http://localhost:8000/api/v1/players/{player_uuid}/export
```

The downloaded `.html` file is self-contained and printable. It includes:
- All key stats with sample sizes
- Positional breakdown (VPIP / PFR / 3-Bet% / F-3bet per position)
- Next training focus (top priority leak with suggested fix)
- Ranked study priorities
- Full leak list with evidence, fix, and limitations

---

## Troubleshooting

**"No player loaded" after import**
Click a player in the post-import picker, or paste your UUID into the header input.

**Import shows 0 hands imported, 0 duplicates**
The file may have failed to parse. Check the **Errors** section in the import result. Common cause: file is not UTF-8 or is not a ClubGG hand history format.

**Stats show "—" for most values**
Too few hands. VPIP/PFR need at least 20 hands for low-confidence estimates; 100+ for reliable numbers.

**Leaks tab shows nothing**
Either no leaks were detected (stats within normal ranges) or the player has fewer than 5 hands for any given spot. Import more hands.

**"Load failed" in the header**
Player UUID not found, or the server isn't running. Check the terminal for error output.

**Trainer shows "No player loaded"**
Load a player first via the header input or recent players dropdown.

**Daily Coach button not visible**
Daily Coach only appears on the Home tab when a player with detected leaks is loaded.

**Database connection error on startup**
Ensure PostgreSQL is running and `DATABASE_URL` in `.env` matches your local setup (default: `postgresql+asyncpg://yaniv@localhost:5432/clubgg`).

**Migrations not applied**
```bash
uv run alembic upgrade head
```
Run this after pulling new code that adds database changes.

---

## Private Beta Deployment

Deploy the app publicly so testers can access it from any browser. The backend and frontend are served as one process — no separate frontend hosting needed.

### Prerequisites

- A PostgreSQL database (Render, Supabase, Railway, or any managed PG)
- Docker (for Railway/Fly.io) or a Render account (for native Python)

---

### Option A — Render (recommended for quick setup)

**1. Create a PostgreSQL database on Render**

In the Render dashboard: New → PostgreSQL. Note the **Internal Database URL** (shown after creation).

**2. Create a Web Service**

New → Web Service → connect your repository. Render detects `render.yaml` automatically and pre-fills most settings.

**3. Set environment variables** in the Render dashboard (Environment tab):

| Variable | Value |
|---|---|
| `DATABASE_URL` | Take Render's **Internal Database URL** and replace `postgresql://` with `postgresql+asyncpg://` |
| `JWT_SECRET_KEY` | Auto-generated by `render.yaml` — no action needed |
| `BETA_INVITE_CODE` | Your private invite code (share this with testers) |
| `CORS_ORIGINS` | `https://your-app.onrender.com` (replace with your actual service URL) |
| `ENVIRONMENT` | `production` |

**4. Deploy**

Click **Manual Deploy → Deploy latest commit**. Render runs `./start.sh` which applies migrations then starts the server.

**Stripe billing (optional):**
Add `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and the three `STRIPE_PRICE_*` vars. Set `BILLING_SUCCESS_URL` and `BILLING_CANCEL_URL` to your Render service URL + path.

---

### Option B — Railway

**1. Create a new project** in Railway, add a PostgreSQL service.

**2. Add a web service** linked to your repository.

**3. Set the start command:**
```
./start.sh
```

**4. Set environment variables** (same as the Render table above). Railway provides `DATABASE_URL` automatically — prefix it with `+asyncpg`:
```
postgresql+asyncpg://user:pass@host:5432/dbname
```

**5. Deploy.** Railway builds from `Dockerfile` and runs `start.sh`.

---

### Option C — Any Docker host (Fly.io, DigitalOcean, VPS)

```bash
docker build -t clubgg .
docker run -p 8000:8000 \
  -e DATABASE_URL="postgresql+asyncpg://..." \
  -e JWT_SECRET_KEY="$(openssl rand -hex 32)" \
  -e BETA_INVITE_CODE="your-invite-code" \
  -e CORS_ORIGINS="https://your-domain.com" \
  -e ENVIRONMENT=production \
  clubgg
```

`start.sh` runs migrations automatically before the server starts.

---

### Production checklist

Before sharing with testers, verify every item:

- [ ] `DATABASE_URL` set with `+asyncpg` driver prefix
- [ ] `JWT_SECRET_KEY` is at least 32 random characters (`openssl rand -hex 32`)
- [ ] `BETA_INVITE_CODE` set to a strong passphrase — this is your only signup gate
- [ ] `CORS_ORIGINS` set to your exact frontend URL (no trailing slash)
- [ ] `ENVIRONMENT=production`
- [ ] App loads at the deploy URL and `/health` returns `{"status": "ok"}`
- [ ] Signup fails without invite code
- [ ] Signup succeeds with correct invite code, user gets `is_tester: true`
- [ ] Stripe vars set if billing is enabled
- [ ] Stripe webhook configured to point at `https://your-domain.com/api/v1/billing/webhook`

---

### Updating after code changes

Push to your repository. Render and Railway redeploy automatically (or trigger manually). `start.sh` always runs `alembic upgrade head` before starting — migrations are applied safely on every deploy.
