from __future__ import annotations

import html
import time

import streamlit as st

try:
    from frontend import runtime_bridge as rb
    from frontend.seed_data import COMPLAINTS, REPLAY_DIAGNOSES, THRESHOLD, build_trace
    from frontend.terminal import render, script_rows
except ModuleNotFoundError as exc:
    if exc.name != "frontend":
        raise
    import runtime_bridge as rb
    from seed_data import COMPLAINTS, REPLAY_DIAGNOSES, THRESHOLD, build_trace
    from terminal import render, script_rows


st.set_page_config(page_title="socialAmbers", page_icon="📡", layout="wide")
st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:
radial-gradient(circle at 8% 4%,rgba(76,125,255,.18),transparent 28%),
radial-gradient(circle at 92% 8%,rgba(32,201,151,.14),transparent 25%),
linear-gradient(160deg,#f7faff 0%,#eef4ff 48%,#f5fbfa 100%)!important;color:#172033}
[data-testid="stHeader"]{background:transparent!important}
[data-testid="stMainBlockContainer"]{max-width:1440px;padding-top:2.4rem;padding-bottom:4rem}
[data-testid="stMainBlockContainer"] p,[data-testid="stMainBlockContainer"] label{color:#33425b}
[data-testid="stButton"] button p,[data-testid="stSegmentedControl"] button[aria-checked="true"] p{color:inherit!important}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#101d38 0%,#142849 55%,#113b43 100%)!important;
border-right:1px solid rgba(255,255,255,.12)}
[data-testid="stSidebar"] *{color:#edf5ff!important}
h1{color:#102242!important;letter-spacing:-.04em;font-weight:850!important}h2,h3{color:#183153!important}
.hero-sub{color:#536884;font-size:1.02rem;margin:-.65rem 0 1.15rem;padding-left:3px}
.stCaptionContainer p{color:#62718a!important}.terminal{height:520px;overflow-y:auto;display:flex;
flex-direction:column;background:linear-gradient(180deg,#0b111a,#070a10);color:#c9d1d9;
border:1px solid #25344a;border-radius:14px;box-shadow:0 18px 45px rgba(16,34,66,.18),inset 0 1px 0 rgba(255,255,255,.04);
padding:16px;font-family:ui-monospace,monospace;white-space:pre;font-size:.82rem}.terminal .ts{color:#687b93}
.pill{display:inline-block;padding:3px 9px;margin:2px;border-radius:999px;background:#e4efff;color:#2765ba;
border:1px solid #cbdfff;font-size:.72rem;font-weight:700}
.post,.meter,.diagnosis{border:1px solid #dbe5f2;background:rgba(255,255,255,.94);border-radius:14px;
padding:16px;margin:10px 0;box-shadow:0 8px 24px rgba(42,68,110,.075);color:#25324a}
.post:hover,.meter:hover{transform:translateY(-1px);border-color:#b9cdf0;box-shadow:0 12px 28px rgba(42,68,110,.12)}
.post,.meter{transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease}
.meter{border-left:4px solid #4c7dff}.people{border:1px solid #c9d8ff;
background:linear-gradient(125deg,#edf5ff 0%,#f4efff 62%,#ecfbf7 100%);color:#223350;
border-radius:14px;padding:16px;margin-top:16px;box-shadow:0 8px 22px rgba(76,125,255,.08)}
.crash{color:#c66f14}.cause{color:#148c82}.counter{font-variant-numeric:tabular-nums;font-weight:750}
details{border:1px solid #c7d8e7!important;background:rgba(255,255,255,.92)!important;border-radius:12px!important;
box-shadow:0 6px 20px rgba(31,67,100,.07)!important}details:hover{border-color:#72b7bd!important}
code{color:#1769aa!important;background:#eaf3fb!important;border-radius:5px!important;padding:2px 5px!important}
[data-testid="stSegmentedControl"]{background:rgba(255,255,255,.75);border-radius:12px;padding:4px;
box-shadow:0 5px 18px rgba(39,67,110,.08)}
[data-testid="stSegmentedControl"] button[aria-checked="true"]{background:#244f91!important;color:#fff!important}
[data-testid="stTextInput"] input,[data-baseweb="select"]>div{background:#fff!important;color:#1e2b43!important;
border-color:#cbd8e8!important;border-radius:9px!important}
[data-testid="stButton"] button[kind="primary"]{
background:linear-gradient(135deg,#e5484d,#c92d3a)!important;color:#fff!important;border:1px solid #b92634!important;
font-weight:800!important;box-shadow:0 7px 18px rgba(201,45,58,.25)!important;min-height:2.7rem}
[data-testid="stButton"] button[kind="primary"]:hover{
background:linear-gradient(135deg,#f05257,#d93644)!important;border-color:#c72a39!important;color:#fff!important;
transform:translateY(-1px);box-shadow:0 10px 22px rgba(201,45,58,.3)!important}
[data-testid="stButton"] button[kind="primary"]:disabled{
background:#e8b8bb!important;color:#fff!important;border-color:#dfa4a8!important;box-shadow:none!important;opacity:1!important}
.st-key-investigation_controls{
background:linear-gradient(120deg,rgba(255,255,255,.98),rgba(240,247,255,.98))!important;
border:1px solid #cbdcf0!important;border-radius:16px!important;padding:16px 18px 12px!important;margin:10px 0 16px!important;
box-shadow:0 12px 32px rgba(34,65,110,.11)!important}
.st-key-investigation_controls [data-testid="stMarkdownContainer"] p{margin-bottom:.2rem}
.st-key-fix_issue button{width:100%!important;background:linear-gradient(135deg,#22a699,#16867d)!important;color:#fff!important;
border:1px solid #11756e!important;font-weight:800!important;min-height:2.7rem;box-shadow:0 7px 18px rgba(22,134,125,.2)!important}
.st-key-fix_issue button:hover{background:linear-gradient(135deg,#2bb8aa,#19958a)!important;color:#fff!important;border-color:#147f77!important}
.st-key-fix_issue button:disabled{background:#d9e5e7!important;color:#819297!important;border-color:#cad8da!important;box-shadow:none!important;opacity:1!important}
.st-key-issue_picker [data-baseweb="select"]>div{background:#fff!important;border-color:#bdcee2!important;min-height:2.7rem}
[data-testid="stAlert"]{border-radius:12px!important;box-shadow:0 5px 16px rgba(32,65,105,.07)}
</style>""", unsafe_allow_html=True)


def esc(value: object) -> str:
    return html.escape(str(value))


def pills(values: list[object]) -> str:
    return "".join(f'<span class="pill">{esc(value)}</span>' for value in values)


def matched_text(verdict: dict) -> str:
    parts = []
    for group, terms in verdict.get("matched", {}).items():
        if terms:
            parts.append(f"{group}={','.join(terms)}")
    return " ".join(parts) or esc(verdict.get("reason", "no qualifying terms"))


def diagnosis_card(diagnosis: dict) -> None:
    context = diagnosis.get("social_context") or {}
    summary = context.get("summary") or diagnosis.get("symptom", "Consolidated complaint cluster")
    artifacts = [f"{key}: {value}" for key, values in context.get("artifacts", {}).items() for value in values]
    quotes = "".join(f"<blockquote>“{esc(item)}”</blockquote>" for item in context.get("exemplars", [])[:3])
    st.markdown(
        f'<div class="people"><b>What people reported</b><p>{esc(summary)}</p>'
        f'<span class="counter">{int(context.get("complaint_count", 0))} reports · '
        f'{int(context.get("distinct_authors", 0))} people</span><br>'
        f'{pills(list(context.get("families", [])) + artifacts)}{quotes}</div>',
        unsafe_allow_html=True,
    )
    confidence = float(diagnosis.get("confidence", 0))
    prior = diagnosis.get("prior_review") or {}
    rows = []
    if prior:
        rows.append(
            f'<b>FLAGGED {esc(prior.get("severity", ""))}</b> · PR #{esc(prior.get("pr", "?"))} · '
            f'{esc(prior.get("title", ""))} · <code>{esc(prior.get("location", ""))}</code> · '
            "still unaddressed · review saw this before users did"
        )
    evidence = diagnosis.get("code_evidence", [])
    root = next((item for item in evidence if item.get("role") == "root-cause"), evidence[-1] if evidence else {})
    crash = next((item for item in evidence if item.get("role") == "crash-site"), {})
    mode = diagnosis.get("mode", "crash")
    if mode == "crash":
        rows.append(f'<span class="crash"><b>CRASH SITE</b> · cite, do not patch</span> · <code>{esc(crash.get("file", "unknown"))}:{esc(crash.get("line_start", "?"))}</code> · {esc(crash.get("source", "unknown"))} · evidence confidence {float(crash.get("confidence", 0)):.2f}')
    elif mode == "degradation":
        rows.append('<span class="crash"><b>NO CRASH SITE</b> · nothing threw · every request returned 200</span>')
    else:
        rows.append('<span class="crash"><b>EXTERNAL</b> · vendor · operational, not a patch</span>')
        rows.append('<b>CALL SITE</b> · no timeout, retry or circuit breaker — the durable fix')
    rows.append(f'<span class="cause"><b>ROOT CAUSE · patch this</b></span> · <code>{esc(root.get("file", diagnosis.get("root_cause", "unknown")))}:{esc(root.get("line_start", ""))}</code> · {esc(root.get("source", "unknown"))} · evidence confidence {float(root.get("confidence", confidence)):.2f}')
    contradiction = (diagnosis.get("contradictions") or ["No contradiction recorded."])[0]
    st.markdown(
        f'<div class="diagnosis"><b>{esc(diagnosis.get("feature", "incident"))}</b> · {esc(mode)} · '
        f'evidence confidence {confidence:.2f}<hr>{"<hr>".join(rows)}<hr><b>Contradiction:</b> {esc(contradiction)}</div>',
        unsafe_allow_html=True,
    )
    logs = diagnosis.get("log_evidence", [])
    with st.expander(f"Inspect exact machine evidence · {len(logs)} log clusters · {len(evidence)} code locations"):
        st.markdown("**Telemetry and stack traces**")
        if logs:
            st.json(logs)
        else:
            st.caption("No exception telemetry; this degradation was corroborated without a thrown request.")
        st.markdown("**Code-analysis evidence**")
        for item in evidence:
            st.code(f'{item.get("file")}:{item.get("line_start")}-{item.get("line_end")}\nsource={item.get("source")} role={item.get("role")} evidence confidence={float(item.get("confidence", 0)):.2f}\n{item.get("rationale", "")}')
        st.markdown("**Prior Greptile review response**")
        st.json(prior or {"status": "No prior review evidence"})


def replay_clusters() -> list[dict]:
    return [
        {"feature": "checkout/promo", "distinct_authors": 5, "complaint_count": 5, "families": ["availability", "abuse"], "status": "diagnosed"},
        {"feature": "ai/assistant", "distinct_authors": 4, "complaint_count": 4, "families": ["correctness"], "status": "diagnosed"},
        {"feature": "checkout/payment", "distinct_authors": 2, "complaint_count": 2, "families": ["friction"], "status": "collecting"},
        {"feature": "account", "distinct_authors": 2, "complaint_count": 2, "families": ["friction"], "status": "collecting"},
        {"feature": "shipping", "distinct_authors": 1, "complaint_count": 1, "families": ["availability"], "status": "collecting"},
    ]


def signal_feed(live: bool) -> None:
    with st.form("compose", clear_on_submit=True):
        text = st.text_input("Add a customer report", placeholder="What are customers seeing?")
        submitted = st.form_submit_button("Post report")
    if submitted and text.strip():
        if live:
            rb.post_complaint(text.strip())
            st.toast("Report queued")
        else:
            item = {"id": f"replay-{time.time_ns()}", "name": "Demo customer", "handle": "@demo", "avatar": "🔹", "time": "0m", "likes": 0, "reposts": 0, "source": "customer report", "text": text.strip()}
            st.session_state.replay_posts.insert(0, item)
    posts = rb.read_complaints() if live else st.session_state.replay_posts
    for post in posts:
        verdict = rb.classify_text(post.get("text", "")) if live else {"label": "replay", "feature": post.get("feature", "unclassified"), "score": 0, "matched": {}}
        score = f' · {float(verdict.get("score", 0)):.2f}' if live else ""
        st.markdown(f'<div class="post"><b>{esc(post.get("avatar", "●"))} {esc(post.get("name", "Customer"))}</b> <span class="pill">{esc(post.get("source", "customer report"))}</span><br><small>{esc(post.get("time", "0m"))}</small><p>{esc(post.get("text", ""))}</p><b>{esc(str(verdict.get("label", "noise")).upper())} · {esc(verdict.get("feature") or "unrouted")}{score}</b> — {esc(matched_text(verdict))}</div>', unsafe_allow_html=True)


def render_clusters(live: bool, state: dict | None = None) -> None:
    if live and rb.is_manual() and rb.queued_count():
        st.warning(f"{rb.queued_count()} reports queued and ready to diagnose")
    signals = (state if state is not None else rb.read_state()).get("signals", []) if live else replay_clusters()
    st.subheader("Customer-signal clusters")
    st.caption("Grouped by product surface and counted by independent customer voices—not raw post volume.")
    columns = st.columns(3)
    for index, signal in enumerate(signals):
        with columns[index % len(columns)]:
            voices = int(signal.get("distinct_authors", 0)); status = signal.get("status", "collecting")
            bar = "▓" * min(voices, THRESHOLD) + "░" * max(0, THRESHOLD - voices)
            if status == "investigating": hint = "investigating — further complaints reinforce it rather than starting a second run"
            elif voices >= THRESHOLD: hint = "Customer-evidence gate passed"
            else: hint = f"{THRESHOLD - voices} more independent voices before investigation"
            ambiguous = " · ambiguous surface; awaiting evidence-led routing" if str(signal.get("feature", "")).endswith("/*") else ""
            st.markdown(f'<div class="meter"><b>{esc(signal.get("feature"))}</b><br><span class="counter">{voices}/{THRESHOLD} voices {bar}</span><br>{int(signal.get("complaint_count", 0))} raw reports · {esc(", ".join(signal.get("families", [])))}<br><small>{esc(hint + ambiguous)}</small></div>', unsafe_allow_html=True)
    st.info("Two gates, two questions: independent customer voices qualify a pattern for investigation; telemetry and code evidence separately decide whether a fix is justified. Only the two seeded incidents pass both gates.")


def replay_diagnose() -> None:
    render_clusters(False)
    st.caption("SCRIPTED REPLAY · offline presentation fixture, never live Greptile or telemetry")
    if st.button("Diagnose now", type="primary", use_container_width=True, help="Start the diagnosis trace"):
        st.session_state.replay_ran = True
        st.session_state.replay_cursor = 0
        st.session_state.replay_last_reveal = time.monotonic() - 0.3
    trace = build_trace([item["id"] for item in st.session_state.replay_posts])
    now = time.monotonic()
    cursor = int(st.session_state.get("replay_cursor", 0))
    if st.session_state.replay_ran and cursor < len(trace) and now - st.session_state.get("replay_last_reveal", now) >= 0.3:
        cursor += 1
        st.session_state.replay_cursor = cursor
        st.session_state.replay_last_reveal = now
    rows = script_rows(trace, cursor) if st.session_state.replay_ran else []
    render(rows)
    if st.session_state.replay_ran and cursor >= len(trace):
        for diagnosis in REPLAY_DIAGNOSES:
            diagnosis_card(diagnosis)


def live_diagnose_body() -> None:
    events = rb.read_events(); state = rb.read_state(); busy = rb.work_in_flight()
    render_clusters(True, state)
    investigating = any(signal.get("status") == "investigating" for signal in state.get("signals", []))
    diagnose_disabled = rb.run_pending() or investigating
    baseline = int(st.session_state.get("diagnose_baseline", len(events)))
    stream_events = events[baseline:]
    if st.session_state.get("diagnose_started_at") is not None:
        now = time.monotonic()
        cursor = int(st.session_state.get("diagnose_cursor", 0))
        if cursor < len(stream_events) and now - st.session_state.get("diagnose_last_reveal", now) >= 0.3:
            st.session_state.diagnose_cursor = cursor + 1
            st.session_state.diagnose_last_reveal = now
    visible = stream_events[:int(st.session_state.get("diagnose_cursor", 0))]
    streaming = bool(busy or len(visible) < len(stream_events)) and st.session_state.get("diagnose_started_at") is not None
    st.caption(f'{len(visible)} streamed events · {len(state.get("signals", []))} signals · {"◉ streaming at 0.3s/line" if streaming else "idle"} · live tail of runtime/events.jsonl written by engine.pipeline')
    diagnoses = rb.all_diagnoses()
    eligible = [item for item in diagnoses if item.get("signal_id")]
    chosen = None
    with st.container(border=True, key="investigation_controls"):
        st.markdown("**Investigation controls**")
        st.caption("Run evidence correlation, select a completed diagnosis, then apply its verified fixture patch.")
        run_col, select_col, fix_col = st.columns([1.15, 2.2, 1.15], vertical_alignment="bottom")
        with run_col:
            if st.button("Diagnose now", key="diagnose_now", type="primary", use_container_width=True, disabled=diagnose_disabled, help="Start diagnosis and stream each engine event at a 0.3-second cadence"):
                st.session_state.diagnose_baseline = len(events)
                st.session_state.diagnose_cursor = 0
                st.session_state.diagnose_started_at = time.monotonic()
                st.session_state.diagnose_last_reveal = time.monotonic() - 0.3
                rb.request_run()
        with select_col:
            if eligible:
                chosen = st.selectbox("Completed diagnosis", eligible, key="issue_picker", format_func=lambda item: f'{item.get("signal_id")} · {item.get("feature") or "incident"}')
            else:
                st.selectbox("Completed diagnosis", ["Awaiting diagnosis…"], key="issue_picker_empty", disabled=True)
        with fix_col:
            signal_id = str((chosen or {}).get("signal_id", ""))
            status = rb.fix_status(signal_id).get("status") if signal_id else None
            disabled = busy or not signal_id or status in {"requested", "running", "completed"}
            label = "Fix completed" if status == "completed" else "Fix issue"
            if st.button(label, key="fix_issue", use_container_width=True, disabled=disabled, help="Replay a captured verified local patch; does not push or open a PR."):
                rb.request_fix(signal_id)
    if st.button("↻ Refresh"):
        st.rerun(scope="fragment")
    render(rb.events_to_rows(visible))
    for diagnosis in diagnoses:
        diagnosis_card(diagnosis)


st.title("📡 socialAmbers")
st.markdown('<div class="hero-sub">Customer signals in. Production evidence correlated. Verified fixes out.</div>', unsafe_allow_html=True)
st.session_state.setdefault("view", "Signal Feed")
st.session_state.setdefault("replay_posts", list(COMPLAINTS))
st.session_state.setdefault("replay_ran", False)
st.session_state.setdefault("diagnose_cursor", 0)
st.session_state.setdefault("diagnose_started_at", None)
force_replay = st.sidebar.toggle("Force scripted replay", value=False)
live_source = rb.is_live() and not force_replay
st.sidebar.success("● live pipeline" if live_source else "● scripted replay")
picked = st.segmented_control("View", ["Signal Feed", "Diagnose"], default=st.session_state.view, key="view_picker")
if picked:
    st.session_state.view = picked

if st.session_state.view == "Signal Feed":
    signal_feed(live_source)
elif live_source:
    fragment = st.fragment(run_every=0.2)(live_diagnose_body)
    fragment()
else:
    replay_fragment = st.fragment(run_every=0.1)(replay_diagnose)
    replay_fragment()
