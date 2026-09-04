"""Weekly refresh of data/dashboard.json from Google Search Console.

Runs in GitHub Actions every Monday. Needs one repository secret:
  GSC_SERVICE_ACCOUNT_JSON  – the JSON key of a Google service account that has
                              been added as a (restricted) user on the
                              https://www.smoke-screen.com/ Search Console property.

What it does
  1. Pulls the last 90 days of page-level clicks / impressions / CTR / position.
  2. Updates every LIVE post by URL.
  3. For PLANNED posts that now have a "url" field (fill it in once the trial is
     published), pulls the same metrics and adds a Content Lab signal:
       Strong    >= 3 clicks, or >= 50 impressions with CTR >= 1 %
       Weak CTR  >= 50 impressions, CTR < 1 %
       Low demand  1–49 impressions
       No data   0 impressions
  4. Stamps meta.last_sync and meta.gsc_window.

Volumes / KD are Ubersuggest and have no public API – refresh those by hand
in data/dashboard.json when you re-run keyword research (quarterly is enough).
"""
import json, os, sys, datetime as dt
from google.oauth2 import service_account
from googleapiclient.discovery import build

SITE = os.environ.get("GSC_SITE", "https://www.smoke-screen.com/")
DATA = os.path.join(os.path.dirname(__file__), "..", "data", "dashboard.json")

def gsc_pages(days=90):
    key = json.loads(os.environ["GSC_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        key, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    end = dt.date.today() - dt.timedelta(days=3)          # GSC lags ~2-3 days
    start = end - dt.timedelta(days=days)
    rows, start_row = {}, 0
    while True:
        resp = svc.searchanalytics().query(siteUrl=SITE, body={
            "startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": ["page"], "rowLimit": 5000, "startRow": start_row}).execute()
        batch = resp.get("rows", [])
        for r in batch:
            rows[r["keys"][0].rstrip("/") + "/"] = r
        if len(batch) < 5000:
            break
        start_row += 5000
    return rows, f"{start} to {end}"

def signal(clicks, imp, ctr):
    if clicks >= 3 or (imp >= 50 and ctr >= 1.0): return "Strong"
    if imp >= 50: return "Weak CTR"
    if imp > 0: return "Low demand"
    return "No data"

def apply(post, r):
    c, i = int(r.get("clicks", 0)), int(r.get("impressions", 0))
    post["clicks"], post["impressions"] = c, i
    post["ctr"] = round(c / i * 100, 2) if i else 0
    post["position"] = round(r.get("position", 0), 2) if i else None
    return c, i, post["ctr"]

def main():
    D = json.load(open(DATA))
    rows, window = gsc_pages()
    hit = 0
    for p in D["current"]:
        r = rows.get(p["url"].rstrip("/") + "/")
        if r: apply(p, r); hit += 1
        else: p["clicks"], p["impressions"], p["ctr"] = 0, 0, 0
    for p in D["future"]:
        url = p.get("url")
        if not url: continue
        r = rows.get(url.rstrip("/") + "/")
        if r:
            c, i, ctr = apply(p, r); p["signal"] = signal(c, i, ctr); hit += 1
        else:
            p["signal"] = "No data"
    D.setdefault("meta", {})
    D["meta"]["last_sync"] = dt.date.today().isoformat()
    D["meta"]["gsc_window"] = window
    json.dump(D, open(DATA, "w"), indent=1)
    print(f"updated {hit} pages · window {window}")

if __name__ == "__main__":
    if "GSC_SERVICE_ACCOUNT_JSON" not in os.environ:
        sys.exit("GSC_SERVICE_ACCOUNT_JSON secret not set")
    main()
