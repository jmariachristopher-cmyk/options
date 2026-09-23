"""
Options Reversal Zones - Streamlit app (Angel One SmartAPI)
=============================================================
Deploy via GitHub + Streamlit Community Cloud. Fully scriptable login (no
browser redirect step at all - Angel One's TOTP login can run headlessly),
pulls PREVIOUS DAY'S CLOSING premium (not live LTP) for Nifty, BankNifty,
Sensex, Godrejprop, and generates a ready-to-paste Pine script per
instrument.

WHY ANGEL ONE INSTEAD OF UPSTOX
Angel One's login (clientcode + PIN/password + a TOTP code) can be
generated entirely in code using the `pyotp` library and your TOTP secret
- no browser, no redirect_uri matching, no daily manual click. This also
lets us cross-verify against Upstox if you ever want to run both side by
side.

ONE-TIME SETUP ON ANGEL ONE'S SIDE
  1. Create a SmartAPI app at https://smartapi.angelone.in -> get your API Key.
  2. Enable TOTP: visit https://smartapi.angelbroking.com/enable-totp,
     log in, scan the QR code with an authenticator app (Google
     Authenticator, Authy, etc). The same screen shows a manual "secret
     key" string underneath the QR code - copy that; it's what pyotp uses
     to generate the same 6-digit codes your authenticator app shows.
  3. You'll need: API Key, Client Code, PIN (or password), and that TOTP
     secret. Keep all four private.

DEPLOY STEPS (GitHub + Streamlit Community Cloud)
  1. Push these files to a GitHub repo: streamlit_app.py, requirements.txt
  2. https://share.streamlit.io -> New app -> your repo -> Main file path:
     streamlit_app.py -> Deploy.
  3. (Recommended) In Streamlit Cloud: your app -> Settings -> Secrets:
       ANGEL_API_KEY = "..."
       ANGEL_CLIENT_CODE = "..."
       ANGEL_PIN = "..."
       ANGEL_TOTP_SECRET = "..."
     Never committed to GitHub, never visible to viewers. Skip this and
     the app just asks for these four values on the page instead.
  4. Open the app -> Connect -> Generate & download a Pine script per
     instrument -> paste into TradingView.

IMPORTANT - PREVIOUS CLOSE, NOT LIVE LTP
This deliberately uses the Historical Candle API (daily candle, most
recent completed session) for CE/PE prices, matching your original
spreadsheet's "CLOSE PREMIUM" columns - NOT the live/current LTP, which
moves every few seconds and is a different number entirely.

WHAT I COULD NOT VERIFY
I have no network access to Angel One's servers from the environment I
wrote this in. Endpoint paths, field names, and the instrument master
file structure are taken from Angel One's official docs and multiple
independently-confirmed community examples, but this has not been run
against a live account. Use the raw-data preview table in the app to
cross-check every number against Angel One's own option chain screen
before trusting the generated Pine script.
"""

import json
from datetime import date, datetime, timedelta

import pyotp
import requests
import streamlit as st

BASE = "https://apiconnect.angelbroking.com"
MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"

# name = exact "name" field in Angel's instrument master for the option series
# underlying_name = "name"/"symbol" fragment used to find the underlying's own
#   quote (for spot price / ATM detection)
# exch_seg = segment options trade in ("NFO" for NSE F&O, "BFO" for BSE F&O)
INSTRUMENTS = {
    "NIFTY":      {"name": "NIFTY",      "exch_seg": "NFO", "instrumenttype": "OPTIDX",
                   "underlying_search": "NIFTY 50",   "underlying_exch": "NSE", "expiry_type": "Weekly"},
    "BANKNIFTY":  {"name": "BANKNIFTY",  "exch_seg": "NFO", "instrumenttype": "OPTIDX",
                   "underlying_search": "NIFTY BANK",  "underlying_exch": "NSE", "expiry_type": "Monthly"},
    "SENSEX":     {"name": "SENSEX",     "exch_seg": "BFO", "instrumenttype": "OPTIDX",
                   "underlying_search": "SENSEX",      "underlying_exch": "BSE", "expiry_type": "Weekly"},
    "GODREJPROP": {"name": "GODREJPROP", "exch_seg": "NFO", "instrumenttype": "OPTSTK",
                   "underlying_search": "GODREJPROP-EQ", "underlying_exch": "NSE", "expiry_type": "Monthly"},
}

STRIKES_EACH_SIDE = 10

st.set_page_config(page_title="Options Reversal Zones - Pine Generator", page_icon="📈")


# ═══════════════════════════════════════════════════════════════════
#  ANGEL ONE LOGIN (fully scriptable - no browser step)
# ═══════════════════════════════════════════════════════════════════
def angel_headers(api_key, jwt_token=None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
        "X-PrivateKey": api_key,
    }
    if jwt_token:
        h["Authorization"] = f"Bearer {jwt_token}"
    return h


def angel_login(api_key, client_code, pin, totp_secret):
    totp = pyotp.TOTP(totp_secret).now()
    r = requests.post(
        f"{BASE}/rest/auth/angelbroking/user/v1/loginByPassword",
        headers=angel_headers(api_key),
        json={"clientcode": client_code, "password": pin, "totp": totp},
    )
    r.raise_for_status()
    body = r.json()
    if not body.get("status"):
        raise RuntimeError(f"Login failed: {body.get('message')}")
    return body["data"]["jwtToken"]


# ═══════════════════════════════════════════════════════════════════
#  INSTRUMENT MASTER (large file - cache it)
# ═══════════════════════════════════════════════════════════════════
@st.cache_data(ttl=6 * 3600, show_spinner="Downloading Angel One instrument master (first time only)...")
def load_master():
    r = requests.get(MASTER_URL, timeout=60)
    r.raise_for_status()
    return r.json()


def get_option_contracts(master, cfg):
    out = []
    for row in master:
        if row.get("exch_seg") != cfg["exch_seg"]:
            continue
        if row.get("instrumenttype") != cfg["instrumenttype"]:
            continue
        if row.get("name") != cfg["name"]:
            continue
        sym = row.get("symbol", "")
        if not (sym.endswith("CE") or sym.endswith("PE")):
            continue
        out.append(row)
    if not out:
        raise RuntimeError(f"No option contracts found for name={cfg['name']} exch_seg={cfg['exch_seg']}.")
    return out


def pick_expiry(contracts, expiry_type):
    def parse(e):
        return datetime.strptime(e, "%d%b%Y").date()

    expiries = sorted({c["expiry"] for c in contracts}, key=parse)
    today = date.today()

    if expiry_type == "Weekly":
        upcoming = [e for e in expiries if parse(e) >= today]
        return upcoming[0] if upcoming else expiries[-1]

    by_month = {}
    for e in expiries:
        d = parse(e)
        by_month.setdefault((d.year, d.month), []).append(e)
    monthly_expiries = sorted((max(v, key=parse) for v in by_month.values()), key=parse)
    upcoming = [e for e in monthly_expiries if parse(e) >= today]
    return upcoming[0] if upcoming else monthly_expiries[-1]


def get_spot(master, sess, jwt_token, api_key, cfg):
    match = None
    for row in master:
        if row.get("exch_seg") == cfg["underlying_exch"] and row.get("name") == cfg["underlying_search"]:
            match = row
            break
    if match is None:
        # fallback: loose match on symbol text
        for row in master:
            if cfg["underlying_search"].upper() in row.get("symbol", "").upper() and row.get("exch_seg") in ("NSE", "BSE"):
                match = row
                break
    if match is None:
        raise RuntimeError(f"Could not find underlying instrument for {cfg['underlying_search']} in master file.")

    token = match["token"]
    r = sess.post(
        f"{BASE}/rest/secure/angelbroking/market/v1/quote",
        headers=angel_headers(api_key, jwt_token),
        json={"mode": "LTP", "exchangeTokens": {cfg["underlying_exch"]: [token]}},
    )
    r.raise_for_status()
    body = r.json()
    if not body.get("status"):
        raise RuntimeError(f"Spot price fetch failed: {body.get('message')}")
    fetched = body["data"]["fetched"]
    if not fetched:
        raise RuntimeError("Spot price fetch returned no data.")
    return fetched[0]["ltp"]


def get_prev_close(sess, jwt_token, api_key, exch_seg, symboltoken):
    today = date.today()
    from_dt = (today - timedelta(days=10)).strftime("%Y-%m-%d 00:00")
    to_dt = today.strftime("%Y-%m-%d 00:00")
    r = sess.post(
        f"{BASE}/rest/secure/angelbroking/historical/v1/getCandleData",
        headers=angel_headers(api_key, jwt_token),
        json={"exchange": exch_seg, "symboltoken": symboltoken, "interval": "ONE_DAY",
              "fromdate": from_dt, "todate": to_dt},
    )
    r.raise_for_status()
    body = r.json()
    if not body.get("status"):
        raise RuntimeError(f"Historical candle fetch failed: {body.get('message')}")
    candles = body.get("data", [])
    if not candles:
        return None
    today_iso = today.isoformat()
    for c in reversed(candles):  # candles are oldest-first; walk backwards for most recent
        candle_date = c[0][:10]
        if candle_date < today_iso:
            return c[4]
    return candles[-1][4]


# ═══════════════════════════════════════════════════════════════════
#  MAIN DATA FETCH FOR ONE INSTRUMENT
# ═══════════════════════════════════════════════════════════════════
def fetch_option_data(master, sess, jwt_token, api_key, instrument_name, strikes_each_side):
    cfg = INSTRUMENTS[instrument_name]
    contracts = get_option_contracts(master, cfg)
    expiry = pick_expiry(contracts, cfg["expiry_type"])
    expiry_contracts = [c for c in contracts if c["expiry"] == expiry]

    # strike field in the master file is the real strike * 100
    by_strike_type = {}
    for c in expiry_contracts:
        strike = round(float(c["strike"]) / 100, 4)
        opt_type = "CE" if c["symbol"].endswith("CE") else "PE"
        by_strike_type[(strike, opt_type)] = c["token"]

    strikes = sorted({k[0] for k in by_strike_type.keys()})
    diffs = [round(b - a, 4) for a, b in zip(strikes, strikes[1:])]
    step = max(set(diffs), key=diffs.count) if diffs else None

    spot = get_spot(master, sess, jwt_token, api_key, cfg)
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))

    margin = 2  # Boundary Line needs neighbours 2 strikes beyond the display range
    lo, hi = atm_idx - (strikes_each_side + margin), atm_idx + (strikes_each_side + margin)
    if lo < 0 or hi >= len(strikes):
        raise RuntimeError(
            f"Chain only has {len(strikes)} strikes - not enough for "
            f"{strikes_each_side} + {margin} margin on each side."
        )

    window_strikes = strikes[lo:hi + 1]

    ext_ce, ext_pe = [], []
    for s in window_strikes:
        ce_token = by_strike_type.get((s, "CE"))
        pe_token = by_strike_type.get((s, "PE"))
        if not ce_token or not pe_token:
            raise RuntimeError(f"Missing CE/PE contract for strike {s}.")
        ce_close = get_prev_close(sess, jwt_token, api_key, cfg["exch_seg"], ce_token)
        pe_close = get_prev_close(sess, jwt_token, api_key, cfg["exch_seg"], pe_token)
        if ce_close is None or pe_close is None:
            raise RuntimeError(f"No historical candle available for strike {s}.")
        ext_ce.append(ce_close)
        ext_pe.append(pe_close)

    expiry_display = datetime.strptime(expiry, "%d%b%Y").date().isoformat()

    return {
        "expiry": expiry_display,
        "spot": spot,
        "step": step,
        "margin": margin,
        "ext_strikes": window_strikes,
        "ext_ce": ext_ce,
        "ext_pe": ext_pe,
    }


# ═══════════════════════════════════════════════════════════════════
#  PINE SCRIPT GENERATION (formulas verified against your original scripts)
# ═══════════════════════════════════════════════════════════════════
def build_pine_script(instrument_name, expiry_type, chain):
    m = chain["margin"]
    ext_strikes, ext_ce, ext_pe = chain["ext_strikes"], chain["ext_ce"], chain["ext_pe"]
    n_display = len(ext_strikes) - 2 * m

    def r4(x):
        return f"{x:.4f}"

    strikes, ce, pe, avg, bl = [], [], [], [], []
    uce133, uce15, upe133, upe15 = [], [], [], []
    lce15, lce2, lpe15, lpe2 = [], [], [], []

    for d in range(n_display):
        ext_i = d + m
        s, c, p = ext_strikes[ext_i], ext_ce[ext_i], ext_pe[ext_i]
        strikes.append(s)
        ce.append(c)
        pe.append(p)
        avg.append((c + p) / 2)
        bl.append((ext_ce[ext_i + 2] + ext_pe[ext_i - 2]) / 2)
        uce133.append(c * 1.33)
        uce15.append(c * 1.5)
        upe133.append(p * 1.33)
        upe15.append(p * 1.5)
        lce15.append(c / 1.5)
        lce2.append(c / 3)
        lpe15.append(p / 1.5)
        lpe2.append(p / 3)

    default_strike = strikes[n_display // 2]
    strike_opts = ", ".join(f"\"{s:g}\"" for s in strikes)

    def arr(vals):
        return ", ".join(r4(v) for v in vals)

    return f'''//@version=5
indicator("Options Reversal Zones - Auto ({instrument_name}) | Expiry: {chain["expiry"]}", overlay=true, max_lines_count=500, max_labels_count=500)

// Auto-generated from Angel One SmartAPI (previous day's close). Spot at generation time: {chain["spot"]}
// Regenerate this file each trading day for fresh premiums.

// ── Strike Selector ──────────────────────────────────────
selected = input.string("{default_strike:g}", "Select Strike", options=[{strike_opts}])

// ── Zone Toggles ─────────────────────────────────────────
show_avg    = input.bool(true,  "Individual Average")
show_bl     = input.bool(true,  "Boundary Line")
show_uce    = input.bool(true,  "Upper Reversal Zone CE")
show_upe    = input.bool(true,  "Upper Reversal Zone PE")
show_lce    = input.bool(true,  "Lower Reversal Zone CE")
show_lpe    = input.bool(true,  "Lower Reversal Zone PE")
show_lbl    = input.bool(true,  "Show Labels")
lw          = input.int(1, "Line Width", minval=1, maxval=4)

// ── Data pulled from Angel One at generation time ────────
var string[] strike_arr  = array.from({strike_opts})
var float[]  avg_arr     = array.from({arr(avg)})
var float[]  bl_arr      = array.from({arr(bl)})
var float[]  uce133_arr  = array.from({arr(uce133)})
var float[]  uce15_arr   = array.from({arr(uce15)})
var float[]  upe133_arr  = array.from({arr(upe133)})
var float[]  upe15_arr   = array.from({arr(upe15)})
var float[]  lce15_arr   = array.from({arr(lce15)})
var float[]  lce2_arr    = array.from({arr(lce2)})
var float[]  lpe15_arr   = array.from({arr(lpe15)})
var float[]  lpe2_arr    = array.from({arr(lpe2)})

// ── Helpers ──────────────────────────────────────────────
f_line(y, col, w) =>
    line.new(bar_index-1, y, bar_index, y, extend=extend.both, color=col, width=w)

f_lbl(y, txt, col) =>
    if show_lbl
        label.new(bar_index, y, txt, xloc=xloc.bar_index, yloc=yloc.price,
                  style=label.style_label_left, color=color.new(col,80),
                  textcolor=col, size=size.small)

// ── Plot on last bar ─────────────────────────────────────
idx = array.indexof(strike_arr, selected)

if barstate.islast and idx >= 0
    s = selected
    label.new(bar_index, high, "{instrument_name} | {expiry_type} Expiry: {chain["expiry"]}", xloc=xloc.bar_index, yloc=yloc.abovebar,
              style=label.style_label_down, color=color.new(color.yellow,60),
              textcolor=color.yellow, size=size.normal)
    if show_avg
        v = array.get(avg_arr, idx)
        f_line(v, color.new(color.gray, 20), lw)
        f_lbl(v, s + " Avg " + str.tostring(v, "#.00"), color.gray)
    if show_bl
        v = array.get(bl_arr, idx)
        f_line(v, color.new(color.orange, 20), lw)
        f_lbl(v, s + " BL " + str.tostring(v, "#.00"), color.orange)
    if show_uce
        v = array.get(uce133_arr, idx)
        f_line(v, color.new(color.red, 20), lw)
        f_lbl(v, s + " UCE×1.33 " + str.tostring(v, "#.00"), color.red)
        v := array.get(uce15_arr, idx)
        f_line(v, color.new(color.red, 40), lw)
        f_lbl(v, s + " UCE×1.5 " + str.tostring(v, "#.00"), color.red)
    if show_upe
        v = array.get(upe133_arr, idx)
        f_line(v, color.new(color.purple, 20), lw)
        f_lbl(v, s + " UPE×1.33 " + str.tostring(v, "#.00"), color.purple)
        v := array.get(upe15_arr, idx)
        f_line(v, color.new(color.purple, 40), lw)
        f_lbl(v, s + " UPE×1.5 " + str.tostring(v, "#.00"), color.purple)
    if show_lce
        v = array.get(lce15_arr, idx)
        f_line(v, color.new(color.teal, 20), lw)
        f_lbl(v, s + " LCE×1.5 " + str.tostring(v, "#.00"), color.teal)
        v := array.get(lce2_arr, idx)
        f_line(v, color.new(color.teal, 40), lw)
        f_lbl(v, s + " LCE×2 " + str.tostring(v, "#.00"), color.teal)
    if show_lpe
        v = array.get(lpe15_arr, idx)
        f_line(v, color.new(color.blue, 20), lw)
        f_lbl(v, s + " LPE×1.5 " + str.tostring(v, "#.00"), color.blue)
        v := array.get(lpe2_arr, idx)
        f_line(v, color.new(color.blue, 40), lw)
        f_lbl(v, s + " LPE×2 " + str.tostring(v, "#.00"), color.blue)

// ── Legend ───────────────────────────────────────────────
plot(na, "Individual Average",     color=color.gray)
plot(na, "Boundary Line",          color=color.orange)
plot(na, "Upper Reversal Zone CE", color=color.red)
plot(na, "Upper Reversal Zone PE", color=color.purple)
plot(na, "Lower Reversal Zone CE", color=color.teal)
plot(na, "Lower Reversal Zone PE", color=color.blue)
'''


# ═══════════════════════════════════════════════════════════════════
#  APP UI
# ═══════════════════════════════════════════════════════════════════
st.title("📈 Options Reversal Zones - Pine Script Generator (Angel One)")

st.subheader("1. Connect to Angel One")
st.caption("Client Code, PIN and a TOTP secret from smartapi.angelbroking.com/enable-totp - no browser login needed each time.")


def cfg_value(secret_name, label, is_password=False):
    try:
        v = st.secrets.get(secret_name)
    except Exception:
        v = None
    if not v:
        v = st.text_input(label, type="password" if is_password else "default")
    return v


api_key = cfg_value("ANGEL_API_KEY", "API Key", is_password=True)
client_code = cfg_value("ANGEL_CLIENT_CODE", "Client Code")
pin = cfg_value("ANGEL_PIN", "PIN / Password", is_password=True)
totp_secret = cfg_value("ANGEL_TOTP_SECRET", "TOTP Secret", is_password=True)

if not all([api_key, client_code, pin, totp_secret]):
    st.stop()

if "jwt_token" not in st.session_state:
    if st.button("Connect to Angel One"):
        try:
            st.session_state["jwt_token"] = angel_login(api_key, client_code, pin, totp_secret)
        except Exception as e:
            st.error(f"Login failed: {e}")
    if "jwt_token" not in st.session_state:
        st.stop()

st.success("Connected ✓")

st.subheader("2. Generate a Pine script")
sess = requests.Session()

master = load_master()

for name, cfg in INSTRUMENTS.items():
    col1, col2 = st.columns([3, 2])
    col1.write(f"**{name}**")
    if col2.button("Fetch & Generate", key=f"gen_{name}"):
        with st.spinner(f"Pulling {name} previous-close data from Angel One (this fetches each strike individually, may take a bit)..."):
            try:
                chain = fetch_option_data(master, sess, st.session_state["jwt_token"], api_key, name, STRIKES_EACH_SIDE)
                pine_code = build_pine_script(name, cfg["expiry_type"], chain)
            except Exception as e:
                st.error(f"{name} failed: {e}")
            else:
                st.success(f"{name}: expiry {chain['expiry']}, spot {chain['spot']}")

                with st.expander(f"🔍 Raw fetched data for {name} - check this against Angel One's own option chain first", expanded=True):
                    m = chain["margin"]
                    disp_strikes = chain["ext_strikes"][m:len(chain["ext_strikes"]) - m]
                    disp_ce = chain["ext_ce"][m:len(chain["ext_ce"]) - m]
                    disp_pe = chain["ext_pe"][m:len(chain["ext_pe"]) - m]
                    st.dataframe(
                        {"Strike": disp_strikes, "CE (prev close)": disp_ce, "PE (prev close)": disp_pe},
                        use_container_width=True,
                    )

                st.download_button(
                    f"Download {name} Pine script",
                    data=pine_code,
                    file_name=f"{name}_reversal_zones_{chain['expiry']}.pine",
                    mime="text/plain",
                    key=f"dl_{name}",
                )
                with st.expander(f"Preview {name}.pine"):
                    st.code(pine_code, language="text")
