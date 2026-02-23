"""
Conducttr Eagle API — Streamlit Publish App
Usage:
    pip install streamlit requests
    streamlit run conducttr_app.py
"""

import io, json, os, re, time, zipfile
import requests
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Conducttr Publisher",
    page_icon="📡",
    layout="centered",
)

# ── Constants ──────────────────────────────────────────────────────────────────

API_BASE = "https://dev-api.conducttr.com/v1.1/eagle"

# ── Helpers ────────────────────────────────────────────────────────────────────

def make_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def clean_team_name(raw_name: str) -> str:
    # Named prefixes with fixed display labels
    if raw_name.startswith("S - "):
        return "Session"
    if raw_name.startswith("M - "):
        return "Moderators"
    # All other prefixes (e.g. T -): strip prefix, then strip trailing date/timestamp
    name = re.sub(r"^[A-Z] - ", "", raw_name)
    name = re.sub(r" - \d{4}[\/-]\d{2}[\/-]\d{2}.*$", "", name)
    return name.strip()

# ── Cached API calls ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def fetch_personas(api_key: str) -> list[dict]:
    """Fetch all personas; cached for 5 minutes."""
    headers = make_headers(api_key)
    res = requests.get(f"{API_BASE}/personas", headers=headers)
    res.raise_for_status()
    presigned_url = res.json()["presigned_url"]

    zip_res = requests.get(presigned_url)
    zip_res.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(zip_res.content)) as z:
        json_filename = next(n for n in z.namelist() if n.endswith(".json"))
        data = json.loads(z.read(json_filename))

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value
    return []


@st.cache_data(ttl=300, show_spinner=False)
def fetch_teams(api_key: str) -> list[dict]:
    """Fetch all teams; cached for 5 minutes.
    Response is always a bare JSON array with 'id' and 'name' fields.
    """
    headers = make_headers(api_key)
    res = requests.get(f"{API_BASE}/teams", headers=headers)
    res.raise_for_status()
    return [{"team_id": t["id"], "name": t["name"]} for t in res.json()]


def publish_to_team(api_key: str, payload: dict) -> dict:
    """POST a single message. Returns result dict."""
    try:
        res = requests.post(f"{API_BASE}/messages", headers=make_headers(api_key), json=payload)
        if res.ok:
            return {"ok": True, "status": res.status_code}
        return {"ok": False, "status": res.status_code, "error": res.text[:300]}
    except requests.RequestException as e:
        return {"ok": False, "status": 0, "error": str(e)}

# ── UI ─────────────────────────────────────────────────────────────────────────

st.title("📡 Conducttr Publisher")
st.caption("Publish articles to your Conducttr simulation via the Eagle API.")

# ── Step 1: API key ────────────────────────────────────────────────────────────

with st.expander("🔑 API Key", expanded="api_key" not in st.session_state):
    default_key = os.environ.get("CONDUCTTR_API_KEY", "")
    api_key_input = st.text_input(
        "Conducttr API Key",
        value=st.session_state.get("api_key", default_key),
        type="password",
        placeholder="Paste your Bearer token here",
    )
    if st.button("Connect", type="primary"):
        if not api_key_input.strip():
            st.error("Please enter an API key.")
        else:
            with st.spinner("Connecting and loading data..."):
                try:
                    personas_raw = fetch_personas(api_key_input.strip())
                    teams_raw    = fetch_teams(api_key_input.strip())
                    orgs = [p for p in personas_raw if p.get("system_info", {}).get("is_organisation")]
                    st.session_state["api_key"] = api_key_input.strip()
                    st.session_state["orgs"]    = orgs
                    st.session_state["teams"]   = teams_raw
                    st.success(f"Connected — {len(orgs)} persona(s), {len(teams_raw)} team(s) loaded.")
                    st.rerun()
                except requests.HTTPError as e:
                    st.error(f"API error: {e.response.status_code} — check your key and try again.")
                except Exception as e:
                    st.error(f"Unexpected error: {e}")

# ── Only show the rest once connected ─────────────────────────────────────────

if "api_key" not in st.session_state:
    st.info("Enter your API key above to get started.")
    st.stop()

api_key = st.session_state["api_key"]
orgs    = st.session_state["orgs"]
teams   = st.session_state["teams"]

if not orgs:
    st.error("No organisation personas found. Cannot publish.")
    st.stop()

if not teams:
    st.error("No teams found. Cannot publish.")
    st.stop()

# ── Step 2: Persona ────────────────────────────────────────────────────────────

st.divider()
st.subheader("1 · Choose a Persona")

persona_options = {
    f"{p.get('system_info', {}).get('name', 'Unknown')}  (@{p.get('system_info', {}).get('handle', '?')})": p
    for p in orgs
}
chosen_persona_label = st.selectbox(
    "Publish as",
    options=list(persona_options.keys()),
    help="Organisation personas only. Persona list refreshes every 5 minutes.",
)
chosen_persona = persona_options[chosen_persona_label]

# ── Step 3: Teams ──────────────────────────────────────────────────────────────

st.divider()
st.subheader("2 · Choose Team(s)")

team_options = {
    f"{clean_team_name(t['name'])}  (id: {t['team_id']})": t
    for t in teams
}
chosen_team_labels = st.multiselect(
    "Publish to",
    options=list(team_options.keys()),
    placeholder="Select one or more teams…",
    help="Hold Ctrl / Cmd to select multiple. Team list refreshes every 5 minutes.",
)

col_all, col_clear = st.columns([1, 5])
with col_all:
    if st.button("Select all"):
        # Trigger a rerun with all teams pre-selected via query param workaround
        st.session_state["select_all_teams"] = True
        st.rerun()

# Handle "select all" on rerun
if st.session_state.pop("select_all_teams", False):
    chosen_team_labels = list(team_options.keys())

chosen_teams = [team_options[label] for label in chosen_team_labels]

# ── Step 4: Article ────────────────────────────────────────────────────────────

st.divider()
st.subheader("3 · Compose Article")

title    = st.text_input("Title *", placeholder="Breaking: Major event unfolds…")
subtitle = st.text_input("Subtitle", placeholder="Optional standfirst or deck copy")
body_raw = st.text_area(
    "Body *",
    height=200,
    placeholder="Paste plain text or HTML. Plain text will be wrapped in <p> tags automatically.",
)
body = body_raw.strip() if "<" in body_raw else f"<p>{body_raw.strip()}</p>"

col_sent, col_draft = st.columns(2)
with col_sent:
    sentiment = st.selectbox("Sentiment", ["positive", "neutral", "negative"])
with col_draft:
    is_draft = st.checkbox("Save as draft (don't publish yet)")

# ── Step 5: Publish ────────────────────────────────────────────────────────────

st.divider()

# Validation
ready = title.strip() and body_raw.strip() and chosen_teams

if not title.strip():
    st.warning("A title is required.")
if not body_raw.strip():
    st.warning("A body is required.")
if not chosen_teams:
    st.warning("Select at least one team.")

# Summary before submitting
if ready:
    with st.expander("📋 Review before publishing", expanded=True):
        st.markdown(f"**Persona:** {chosen_persona_label}")
        st.markdown(f"**Teams:** {', '.join(clean_team_name(t['name']) for t in chosen_teams)}")
        st.markdown(f"**Title:** {title}")
        st.markdown(f"**Sentiment:** {sentiment}")
        st.markdown(f"**Mode:** {'🗒️ Draft' if is_draft else '🚀 Publish immediately'}")

publish_btn = st.button(
    "🚀 Publish" if not is_draft else "💾 Save Draft",
    type="primary",
    disabled=not ready,
    use_container_width=True,
)

if publish_btn and ready:
    article = {
        "title":     title.strip(),
        "subtitle":  subtitle.strip(),
        "body":      body,
        "sentiment": sentiment,
        "is_draft":  1 if is_draft else 0,
    }
    persona_hash = chosen_persona["system_info"]["hash"]
    team_ids     = [t["team_id"] for t in chosen_teams]

    results = []
    progress = st.progress(0, text="Publishing…")

    for i, team_id in enumerate(team_ids):
        payload = {
            "persona":   persona_hash,
            "channel":   "websites",
            "title":     article["title"],
            "subtitle":  article["subtitle"],
            "body":      article["body"],
            "assets":    [],
            "sentiment": article["sentiment"],
            "team_id":   team_id,
            "type":      "team",
            "isDraft":   article["is_draft"],
        }
        result = publish_to_team(api_key, payload)
        results.append({"team_id": team_id, **result})
        progress.progress((i + 1) / len(team_ids), text=f"Published {i + 1} of {len(team_ids)}…")
        if i < len(team_ids) - 1:
            time.sleep(0.5)

    progress.empty()

    # Results
    st.divider()
    st.subheader("Results")
    successes = [r for r in results if r["ok"]]
    failures  = [r for r in results if not r["ok"]]

    if successes:
        st.success(f"✓ Published to {len(successes)} team(s) successfully.")
    if failures:
        st.error(f"✗ {len(failures)} publish(es) failed.")

    for r in results:
        team_name = next(
            (clean_team_name(t["name"]) for t in teams if t["team_id"] == r["team_id"]),
            str(r["team_id"]),
        )
        if r["ok"]:
            st.markdown(f"✅ **{team_name}** — HTTP {r['status']}")
        else:
            st.markdown(f"❌ **{team_name}** — HTTP {r['status']}: `{r.get('error', 'unknown error')}`")

# ── Footer ─────────────────────────────────────────────────────────────────────

st.divider()
col1, col2 = st.columns([3, 1])
with col1:
    st.caption(f"Connected to `{API_BASE}`")
with col2:
    if st.button("🔄 Refresh data"):
        fetch_personas.clear()
        fetch_teams.clear()
        st.session_state.pop("orgs", None)
        st.session_state.pop("teams", None)
        st.session_state.pop("api_key", None)
        st.rerun()

