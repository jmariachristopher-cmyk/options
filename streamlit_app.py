"""
Options Reversal Zones - Streamlit app (Upstox-powered, token-only)
=====================================================================
Deploy this via GitHub + Streamlit Community Cloud. Open the resulting
public URL, paste your Upstox Analytics Token once, click a button per
instrument, download a ready-to-paste Pine script with real closing
premiums baked in.

WHY THIS VERSION HAS NO LOGIN FLOW
Upstox has a token type called the "Analytics Token": a long-lived
(1-year) read-only token you generate with one click from your Upstox
Developer Apps page - no OAuth redirect, no client_id/redirect_uri
matching, no daily re-login. It covers exactly what this app needs
(option chain + option contracts), so there's no reason to use the full
trading OAuth flow (the thing that kept failing with UDAPI100068) at all.

GENERATE YOUR TOKEN (one-time, about 30 seconds)
  1. Go to https://account.upstox.com/developer/apps -> "Analytics" tab.
  2. Click "Generate Token" -> Confirm.
  3. Copy the full token shown (click the copy icon next to it).
     Keep it secret - anyone with it can read your account's market data.

DEPLOY STEPS (GitHub + Streamlit Community Cloud)
  1. Push these files to a GitHub repo: streamlit_app.py, requirements.txt
  2. Go to https://share.streamlit.io -> New app -> pick your repo/branch
     -> Main file path: streamlit_app.py -> Deploy.
  3. (Optional but recommended) In Streamlit Cloud: your app -> Settings
     -> Secrets, paste:
         UPSTOX_ANALYTICS_TOKEN = "your_token_here"
     This way you don't paste the token into the page every visit, and
     it's never committed to GitHub or visible to viewers.
     If you skip this, the app just asks you to paste it into the page
     each time instead - also fine.
  4. Open the app, generate & download a Pine script for any instrument.

NOTE: your app's URL is public by default. Restrict viewers under your
app's Settings -> Sharing in Streamlit Cloud if you don't want others
using it, or deploy from a private GitHub repo.

I could not test this against live Upstox servers or a live Streamlit
Cloud deployment from the environment I wrote this in - please run it
yourself and sanity-check the first generated file's numbers against
Upstox's own option chain page before trusting it for trading.
"""

from datetime import date

import requests
import streamlit as st

BASE = "https://api.upstox.com/v2"

INSTRUMENTS = {
    "NIFTY":      {"key": "NSE_INDEX|Nifty 50",   "expiry_type": "Weekly"},
    "BANKNIFTY":  {"key": "NSE_INDEX|Nifty Bank",  "expiry_type": "Monthly"},
    "SENSEX":     {"key": "BSE_INDEX|SENSEX",      "expiry_type": "Weekly"},
    "GODREJPROP": {"key": "NSE_EQ|INE484J01027",   "expiry_type": "Monthly"},
}

STRIKES_EACH_SIDE = 10

st.set_page_config(page_title="Options Reversal Zones - Pine Generator", page_icon="📈")


# ═══════════════════════════════════════════════════════════════════
#  UPSTOX DATA FETCHING
# ═══════════════════════════════════════════════════════════════════
def get_nearest_expiry(sess, instrument_key):
    r = sess.get(f"{BASE}/option/contract", params={"instrument_key": instrument_key})
    r.raise_for_status()
    contracts = r.json().get("data", [])
    if not contracts:
        raise RuntimeError("No contracts returned for this instrument key.")
    expiries = sorted({c["expiry"] for c in contracts})
    today = date.today().isoformat()
    upcoming = [e for e in expiries if e >= today]
    return upcoming[0] if upcoming else expiries[-1]


def fetch_option_data(sess, instrument_key, strikes_each_side):
    expiry = get_nearest_expiry(sess, instrument_key)
    r = sess.get(f"{BASE}/option/chain", params={"instrument_key": instrument_key, "expiry_date": expiry})
    r.raise_for_status()
    data = r.json().get("data", [])
    if not data:
        raise RuntimeError(f"Empty option chain for {instrument_key} / {expiry}.")

    spot = data[0]["underlying_spot_price"]
    rows = sorted(data, key=lambda d: d["strike_price"])
    strikes = [row["strike_price"] for row in rows]

    diffs = [round(b - a, 4) for a, b in zip(strikes, strikes[1:])]
    step = max(set(diffs), key=diffs.count) if diffs else None

    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))

    margin = 2  # Boundary Line needs neighbours 2 strikes beyond the display range
    lo, hi = atm_idx - (strikes_each_side + margin), atm_idx + (strikes_each_side + margin)
    if lo < 0 or hi >= len(strikes):
        raise RuntimeError(
            f"Chain only has {len(strikes)} strikes - not enough for "
            f"{strikes_each_side} + {margin} margin on each side."
        )

    window = rows[lo:hi + 1]
    return {
        "expiry": expiry,
        "spot": spot,
        "step": step,
        "margin": margin,
        "ext_strikes": [w["strike_price"] for w in window],
        "ext_ce": [w["call_options"]["market_data"]["close_price"] for w in window],
        "ext_pe": [w["put_options"]["market_data"]["close_price"] for w in window],
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

// Auto-generated from live Upstox data. Spot at generation time: {chain["spot"]}
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

// ── Data pulled from Upstox at generation time ───────────
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
st.title("📈 Options Reversal Zones - Pine Script Generator")

st.subheader("1. Your Upstox Analytics Token")
st.caption(
    "Generate once, valid for a year: account.upstox.com/developer/apps → "
    "Analytics tab → Generate Token."
)

try:
    token = st.secrets.get("UPSTOX_ANALYTICS_TOKEN")
except Exception:
    token = None

if not token:
    token = st.text_input("Paste your Analytics Token", type="password")

if not token:
    st.stop()

sess = requests.Session()
sess.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})

st.success("Token set ✓")

st.subheader("2. Generate a Pine script")
for name, cfg in INSTRUMENTS.items():
    col1, col2 = st.columns([3, 2])
    col1.write(f"**{name}**")
    if col2.button("Fetch & Generate", key=f"gen_{name}"):
        with st.spinner(f"Pulling {name} option chain from Upstox..."):
            try:
                chain = fetch_option_data(sess, cfg["key"], STRIKES_EACH_SIDE)
                pine_code = build_pine_script(name, cfg["expiry_type"], chain)
            except Exception as e:
                st.error(f"{name} failed: {e}")
            else:
                st.success(f"{name}: expiry {chain['expiry']}, spot {chain['spot']}")
                st.download_button(
                    f"Download {name} Pine script",
                    data=pine_code,
                    file_name=f"{name}_reversal_zones_{chain['expiry']}.pine",
                    mime="text/plain",
                    key=f"dl_{name}",
                )
                with st.expander(f"Preview {name}.pine"):
                    st.code(pine_code, language="text")
