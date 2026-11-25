# Hosting the dashboard on Render (free plan)

One Render web service runs everything:
- the Django API and the built React frontend, together, like `serve.py` on the office PC;
- the 10:30 / 15:30 IST refresh, which runs inside that server.

All data comes from APIs:
- **Supabase:** TD data, the fixed sheets and the dashboard edits;
- **Google Sheets:** the Tracker and TechnoD Distributors;
- **Dropbox:** BlueOrigin.

Nothing is read from a PC. The blueprint is `render.yaml` at the repo root.

## What the free plan means

| Free-plan limit | What happens | What to do |
|---|---|---|
| Sleeps after 15 min without visitors | The next visitor waits ~1 minute while it wakes up, and a refresh that falls due while it sleeps runs on wake. | Keep it awake with a free pinger (step 6). |
| No disk | `db.sqlite3` is lost on every deploy, restart or wake-up. The server rebuilds it by itself: edits and users are restored from Supabase, then a full import runs. | Expect the dashboard to show **no data for a few minutes** after a deploy or restart. |
| 512 MB memory, small CPU | A full import is slower than on the PC. | If Render shows "out of memory" in the logs, the free plan is too small: switch to Starter. |

**Your data is safe while it rebuilds.** An empty new server never overwrites the Supabase backup: it skips the
backup until its users are restored, and it never empties a whole table in Supabase.

Later, **Starter plus a 1 GB disk** removes all three limits. In `render.yaml`, set `plan: starter` and add a disk
mounted for `db.sqlite3`.

## Steps

1. **Push the code to GitHub.** Render deploys from `github.com/lukeshpawar01/TechnoDirect`, branch `main`. The
   `.env` files, `db.sqlite3` and key files are git-ignored and never uploaded.

2. **Create the service.** Go to https://dashboard.render.com and sign in with GitHub. Click **New → Blueprint**, pick
   the **TechnoDirect** repo and click **Apply**. Render reads `render.yaml`: one free web service in Singapore.

3. **Fill in the secrets.** Render asks once for every value marked `sync: false`. Copy each from `Backend\.env`,
   except:
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: open `C:\Users\IT\Documents\keys\td-sheets-key.json` in Notepad and paste **its
     whole text**, from `{` to `}`. Don't paste the path.
   - Leave `DJANGO_SECRET_KEY` alone; Render generates it.

   To change one later: **Service → Environment → Edit**, then **Save** (this redeploys).

4. **Wait for the first deploy, about 5 to 10 minutes.** It installs Python and the frontend packages and builds the
   frontend, then starts `serve.py`. In **Logs** you should see:
   - `TechnoDirect dashboard on http://0.0.0.0:...`
   - about a minute later, `new database: restored ... edited records from Supabase`
   - then the refresh: Supabase → BlueOrigin → sheets → derivations.

5. **Open the site.** It's `https://technodirect-dashboard.onrender.com` (the exact link is at the top of the service
   page).
   - Log in with your usual account; it was restored from Supabase.
   - On **Data Health**, every source should show "ok" with "Comes from: Supabase / Google Sheets API / Dropbox
     API".

6. **Keep it awake (optional).** At https://uptimerobot.com (free), add an **HTTP(s) monitor** for
   `https://<your-service>.onrender.com/api/health/`, every 5 minutes. Then:
   - it doesn't sleep, so the 10:30 / 15:30 refreshes run on time;
   - the database isn't rebuilt at every wake-up.

   One always-on free service uses ~730 of the 750 free hours a month, so don't run a second free service on the
   same account.

## Day to day

- **New code:** `git push` to `main`, and Render redeploys automatically. The dashboard then rebuilds for a few
  minutes (free plan).
- **Logs:** Render → service → **Logs**.
- **A changed setting:** Render → **Environment**.
- **The office PC copy** (Cloudflare tunnel) keeps working unchanged. Running both at once is fine: both read the
  same sources, and both back up edits to the same Supabase tables. Make admin edits in **one** of them, so a change
  on one isn't undone by the other.
