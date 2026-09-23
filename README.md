# Options Reversal Zones - Pine Script Generator (Angel One SmartAPI)

Generates ready-to-paste TradingView Pine scripts (Nifty, BankNifty, Sensex,
Godrejprop) auto-filled with the **previous trading day's closing option
premiums** pulled from Angel One - matching your original spreadsheet's
"CLOSE PREMIUM" columns (not live/current LTP, which is a different,
constantly-moving number).

## One-time Angel One setup

1. Create a SmartAPI app at https://smartapi.angelone.in to get your **API Key**.
2. Enable TOTP at https://smartapi.angelbroking.com/enable-totp - log in,
   scan the QR code with an authenticator app, and copy the **secret key**
   shown under the QR code (a short text string, not the 6-digit code).
3. You now have four things: **API Key, Client Code, PIN, TOTP Secret**.
   Keep all four private - the TOTP secret in particular lets anyone
   generate valid login codes for your account.

This login can run with zero browser interaction each time - `pyotp`
generates the same 6-digit code your authenticator app would show, from
the secret, in code.

## Deploy (GitHub + Streamlit Community Cloud)

1. Push these files to a GitHub repo:
   - `streamlit_app.py`
   - `requirements.txt`

2. https://share.streamlit.io → New app → your repo → Main file path:
   `streamlit_app.py` → Deploy.

3. (Recommended) In Streamlit Cloud: your app → **Settings → Secrets**:

   ```toml
   ANGEL_API_KEY = "your_api_key"
   ANGEL_CLIENT_CODE = "your_client_code"
   ANGEL_PIN = "your_pin_or_password"
   ANGEL_TOTP_SECRET = "your_totp_secret"
   ```

   Never committed to GitHub, never visible to anyone viewing the app.
   Skip this and the app just asks for all four on the page instead.

4. Open the app → **Connect to Angel One** → generate & download a Pine
   script per instrument → paste into TradingView's Pine Editor.

## Running locally first (recommended before deploying)

```
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Important: always check the raw data table first

After clicking "Fetch & Generate," the app shows a table of every strike's
CE/PE previous-close value **before** building the Pine script. Compare
that table against Angel One's own option chain screen for the same
expiry before trusting the downloaded script - if that raw table matches,
the Pine script is guaranteed correct downstream (the reversal-zone
formulas were independently verified against your original examples).

## Notes / limitations

- This makes two API calls per strike (CE + PE previous close), so
  generating one instrument takes noticeably longer than a single quick
  request - expect it to take a bit, especially on first run per session
  (it also downloads Angel One's full instrument master file once, cached
  for 6 hours).
- Your app's URL is public by default. Restrict viewers under your app's
  **Settings → Sharing** in Streamlit Cloud if you don't want others using
  it, or deploy from a private GitHub repo.
- I have no network access to Angel One's servers from the environment I
  wrote this in. Endpoint paths and field names are taken from Angel
  One's official docs and multiple independently-confirmed community
  examples, but this has not been run against a live account - please
  test it yourself and use the raw-data table above to verify before
  trusting it for trading.
