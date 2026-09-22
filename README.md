# Options Reversal Zones - Pine Script Generator (Streamlit + Upstox)

Generates ready-to-paste TradingView Pine scripts (Nifty, BankNifty, Sensex,
Godrejprop) auto-filled with live closing option premiums pulled from Upstox.

## Deploy (GitHub + Streamlit Community Cloud)

1. Push these three files to a new GitHub repo:
   - `streamlit_app.py`
   - `requirements.txt`
   - `README.md` (this file, optional)

2. Go to https://share.streamlit.io → "New app" → sign in with GitHub →
   pick your repo/branch → set **Main file path** to `streamlit_app.py` →
   Deploy.

   You'll get a public URL like `https://your-app-name.streamlit.app`.

3. In your Upstox Developer app (https://developer.upstox.com), set the
   **Redirect URI** to that exact URL, including the trailing slash:
   `https://your-app-name.streamlit.app/`

4. Back in Streamlit Cloud: your app → **Settings → Secrets**, paste:

   ```toml
   UPSTOX_CLIENT_ID = "your_client_id"
   UPSTOX_CLIENT_SECRET = "your_client_secret"
   REDIRECT_URI = "https://your-app-name.streamlit.app/"
   ```

   Secrets entered here are **not** committed to GitHub and are never
   visible to anyone viewing the app.

5. Reload the app → **Connect to Upstox** → log in → generate & download
   a Pine script for any instrument → paste into TradingView's Pine Editor.

## Running locally first (recommended before deploying)

```
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Without a `secrets.toml`, the app will ask for your Client ID/Secret/Redirect
URI directly in the page for a local test (use `http://localhost:8501/` as
the redirect URI in that case, and register that on Upstox too).

## Notes

- Your app's URL is public by default. Your Upstox client_secret stays safe
  either way (server-side only), but if you don't want others generating
  scripts using your Upstox login, restrict viewers under your app's
  **Settings → Sharing**, or deploy from a private GitHub repo.
- This was written and syntax-checked but not run against live Upstox
  servers or a live Streamlit Cloud deployment - test the first output
  against Upstox's own option chain page before trusting it for trading.
