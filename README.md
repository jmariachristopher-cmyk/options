# Options Reversal Zones - Pine Script Generator (Streamlit + Upstox)

Generates ready-to-paste TradingView Pine scripts (Nifty, BankNifty, Sensex,
Godrejprop) auto-filled with live closing option premiums pulled from Upstox.

## Get your Upstox token (one-time, ~30 seconds - no app/redirect URI needed)

1. Go to https://account.upstox.com/developer/apps → **Analytics** tab.
2. Click **Generate Token** → Confirm.
3. Copy the full token. It's valid for 1 year and is read-only (it can't
   place or modify orders).

This replaces the earlier OAuth client_id/client_secret/redirect_uri setup
entirely - no more `UDAPI100068` redirect-mismatch errors, no daily login.

## Deploy (GitHub + Streamlit Community Cloud)

1. Push these files to a new GitHub repo:
   - `streamlit_app.py`
   - `requirements.txt`

2. Go to https://share.streamlit.io → "New app" → sign in with GitHub →
   pick your repo/branch → set **Main file path** to `streamlit_app.py` →
   Deploy.

3. (Optional but recommended) In Streamlit Cloud: your app →
   **Settings → Secrets**, paste:

   ```toml
   UPSTOX_ANALYTICS_TOKEN = "your_token_here"
   ```

   This way you don't paste the token into the page every visit, and it's
   never committed to GitHub or visible to anyone viewing the app.
   If you skip this step, the app just asks you to paste the token into
   the page each time instead - also fine.

4. Open the app → generate & download a Pine script for any instrument →
   paste into TradingView's Pine Editor.

## Running locally first (recommended before deploying)

```
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Paste your token into the page when prompted.

## Notes

- Your app's URL is public by default. Your token stays safe either way if
  you use Streamlit Secrets (server-side only), but if you don't want
  others using your token to pull data, restrict viewers under your app's
  **Settings → Sharing**, or deploy from a private GitHub repo.
- Only one Analytics Token is allowed per Upstox account at a time -
  generating a new one revokes the old one.
- This was written and syntax-checked but not run against live Upstox
  servers or a live Streamlit Cloud deployment - test the first output
  against Upstox's own option chain page before trusting it for trading.
