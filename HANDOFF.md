# Handing this over

Everything in this archive is committed. `git log` shows the work as a series
of reviewable commits on top of `be38a48`, the last commit that is already on
GitHub.

## Push it

    git remote -v                 # should be your repo; add it if the archive lost it
    git push origin main

## Then, once

1. **GitHub Pages**: Settings, then Pages, then Build and deployment, then
   Source: **GitHub Actions**. The `pages` workflow regenerates the site's
   figures from the engine on every publish; the old HTML report stays
   reachable at `/report.html`.
2. **Render**: the service was created with the Python runtime and `render.yaml`
   now asks for Docker. If the deploy log still shows a `pip install` build,
   change the runtime in the Render dashboard or re-create the service from the
   blueprint.
3. **Check one assumption**: the per-client rate limit reads the rightmost
   `X-Forwarded-For` entry, which is the one Render appends. Send a request with
   a made-up `X-Forwarded-For` and confirm the limit still counts you.
4. **Decide about `keepalive.yml`**: it pings the engine every 10 minutes so
   visitors never wait for a cold start, and uses roughly 730 of the free
   tier's 750 monthly instance-hours doing it. Delete the file if those hours
   are worth more; the site still works, it just falls back to recorded runs
   while the engine starts.

## Run it here

    pip install -r requirements-web.txt
    python -m uvicorn app:app --app-dir src --port 8000     # engine + dashboard

    cd web && npm install && npm run dev                    # dashboard with hot reload
    python scripts/build_site_data.py                       # rebuild the site's figures

    python -m pytest tests -q                               # 168 tests

## What changed, in one line each

- Four blind spots the adversarial harness found are closed, and two more
  unseen classes are now named rather than lumped into `orphan_bank_credit`.
- `src/taxonomy.py` holds every classification once; the agent and the report
  both read it instead of keeping their own lists.
- `src/analysis.py` renders a run as JSON; `/api/v1/*` serves it, with OpenAPI
  docs at `/api/docs`.
- Four web-layer bugs fixed: a rate-limit bypass message that was not true, a
  visitor key that could spend the operator's other providers, an upload size
  check that ran after the whole body was read, and a per-client limit keyed on
  a client-controlled header.
- A dashboard in `web/`, served by the engine and published to Pages.
- The cold start is handled in the page as well as by the ping.

`NOTES.md` has the long version of each, including what it cost.
