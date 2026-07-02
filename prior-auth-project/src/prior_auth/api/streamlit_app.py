"""Streamlit dashboard for the prior-auth multi-agent workflow.

Calls PriorAuthWorkflow directly in-process (no HTTP hop) so this can run standalone with
`streamlit run streamlit_app.py`. Runs triggered here are not persisted to logs/audit_traces.
"""
from __future__ import annotations

import glob
import json
import time
from pathlib import Path

import streamlit as st

from prior_auth.orchestration.graph import PriorAuthWorkflow

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
AGENT_ORDER = ["Extractor", "ICD Coder", "Policy RAG", "Form Filler"]

# Validated status palette (dataviz skill): good / warning / critical, paired with
# icon + label everywhere (never color alone) per the palette's contrast notes.
STATUS = {
    "ok": {"fill": "#0ca30c", "tint": "#e6f7e6", "border": "#b9e8b9", "icon": "✓", "label": "OK"},
    "suspended": {"fill": "#fab219", "tint": "#fff6e0", "border": "#ffdf94", "icon": "⏸", "label": "Suspended"},
    "failed": {"fill": "#d03b3b", "tint": "#fbe8e8", "border": "#f3b8b8", "icon": "✕", "label": "Failed"},
    "pending": {"fill": "#c3c2b7", "tint": "#f4f4f2", "border": "#e1e0d9", "icon": "·", "label": "Not reached"},
}

WORKFLOW_STATUS_META = {
    "COMPLETED": ("ok", "Completed", "No suspension or validation issues."),
    "SUSPENDED_LOW_CONFIDENCE": ("suspended", "Suspended — low ICD coding confidence", None),
    "SUSPENDED_PHI_VIOLATION": ("failed", "Suspended — PHI boundary violation", None),
    "SUSPENDED_POLICY_MISMATCH": ("suspended", "Suspended — policy criteria not met", None),
    "SUSPENDED_LATERALITY_CONFLICT": ("suspended", "Suspended — laterality conflict", None),
    "FAILED_VALIDATION": ("failed", "Failed — validation error", None),
    "ERROR": ("failed", "Error", None),
    "IN_PROGRESS": ("pending", "In progress", None),
}


@st.cache_resource
def get_workflow() -> PriorAuthWorkflow:
    return PriorAuthWorkflow()


@st.cache_data
def load_sample_cases() -> list[dict]:
    cases = []
    for path in sorted(glob.glob(str(_DATA_DIR / "doctor_notes" / "*" / "cases.json"))):
        with open(path, "r", encoding="utf-8") as f:
            for case in json.load(f):
                cases.append(
                    {
                        "case_id": case["case_id"],
                        "specialty": case.get("specialty", "unknown"),
                        "note_text": case["note_text"],
                        "requested_procedure": case.get("gold", {}).get("requested_procedure"),
                    }
                )
    return cases


def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

        html, body, [class*="css"]  { font-family: 'Inter', sans-serif; }
        code, pre, .mono { font-family: 'JetBrains Mono', monospace !important; }

        .block-container { padding-top: 1.5rem; max-width: 1200px; }

        .hero {
            background: linear-gradient(120deg, #1e38b6 0%, #2a78d6 100%);
            border-radius: 16px; padding: 1.6rem 1.9rem; color: white;
            margin-bottom: 1.4rem; box-shadow: 0 8px 24px rgba(30,56,182,0.18);
        }
        .hero h1 { font-size: 1.35rem; font-weight: 800; margin: 0; }
        .hero p { font-size: 0.85rem; opacity: 0.85; margin: 0.25rem 0 0 0; }
        .hero .pill {
            display: inline-flex; align-items: center; gap: 6px; font-size: 0.72rem;
            background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.25);
            border-radius: 999px; padding: 4px 12px; margin-top: 0.7rem;
        }

        .status-banner {
            border-radius: 14px; padding: 1.1rem 1.4rem; display: flex;
            align-items: center; gap: 14px; border: 1px solid;
        }
        .status-banner .dot {
            height: 40px; width: 40px; border-radius: 999px; display: flex;
            align-items: center; justify-content: center; font-size: 1.1rem;
            color: white; flex-shrink: 0;
        }
        .status-banner .title { font-weight: 700; font-size: 0.95rem; color: #0b0b0b; }
        .status-banner .subtitle { font-size: 0.8rem; color: #52514e; margin-top: 2px; }

        .step-card {
            border-radius: 14px; border: 1px solid; padding: 0.95rem 1rem;
        }
        .step-card .step-head { display:flex; align-items:center; gap:8px; margin-bottom: 8px; }
        .step-card .step-num {
            height: 22px; width: 22px; border-radius: 999px; color: white;
            display:flex; align-items:center; justify-content:center; font-size: 0.68rem; font-weight:700;
        }
        .step-card .step-name { font-weight: 700; font-size: 0.82rem; color: #0b0b0b; }
        .step-card .step-status { font-size: 0.72rem; color: #52514e; margin-bottom: 8px; }
        .meter-track { height: 6px; border-radius: 999px; overflow: hidden; margin-bottom: 4px; }
        .meter-fill { height: 100%; border-radius: 999px; }
        .step-card .step-meta { font-size: 0.68rem; color: #898781; font-family: 'JetBrains Mono', monospace; }

        .phi-panel { border-radius: 14px; border: 1px solid; padding: 1rem 1.1rem; height: 100%; }
        .phi-panel .kicker { font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 8px; }
        .phi-panel dl { font-size: 0.76rem; font-family: 'JetBrains Mono', monospace; color: #3f465a; line-height: 1.6; margin: 0; }

        .section-title { font-size: 0.9rem; font-weight: 700; color: #171a22; margin: 0.3rem 0 0.7rem 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
          <h1>Prior Authorization Workflow</h1>
          <p>Extractor &rarr; ICD Coder &rarr; Policy RAG &rarr; Form Filler</p>
          <span class="pill">● Live demo &middot; synthetic data only &middot; real agent pipeline, nothing mocked</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_status_banner(status: str, reason: str | None, total_ms: float) -> None:
    key, title, default_subtitle = WORKFLOW_STATUS_META.get(status, ("pending", status, None))
    s = STATUS[key]
    subtitle = reason or default_subtitle or ""
    col1, col2 = st.columns([5, 1])
    with col1:
        st.markdown(
            f"""
            <div class="status-banner" style="background:{s['tint']}; border-color:{s['border']};">
              <div class="dot" style="background:{s['fill']}">{s['icon']}</div>
              <div>
                <div class="title">{title}</div>
                <div class="subtitle">{subtitle}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        st.metric("Total time", f"{total_ms:.1f} ms")


def step_status_key(ev: dict | None) -> str:
    if ev is None:
        return "pending"
    if ev["status"] == "OK":
        return "ok"
    if ev["status"] == "SUSPENDED":
        return "suspended"
    return "failed"


def render_pipeline(events: list[dict]) -> None:
    st.markdown('<p class="section-title">Agent pipeline</p>', unsafe_allow_html=True)
    by_agent = {e["agent_name"]: e for e in events}
    cols = st.columns(4)
    for idx, agent_name in enumerate(AGENT_ORDER):
        ev = by_agent.get(agent_name)
        key = step_status_key(ev)
        s = STATUS[key]
        confidence_pct = round(ev["confidence"] * 100) if ev and ev.get("confidence") is not None else None
        with cols[idx]:
            st.markdown(
                f"""
                <div class="step-card" style="background:{s['tint']}; border-color:{s['border']};">
                  <div class="step-head">
                    <span class="step-num" style="background:{s['fill']}">{idx + 1}</span>
                    <span class="step-name">{agent_name}</span>
                  </div>
                  <div class="step-status">{s['icon']} {ev['status'] if ev else 'Not reached'}</div>
                  <div class="meter-track" style="background:{s['tint']}; border:1px solid {s['border']};">
                    <div class="meter-fill" style="width:{confidence_pct if confidence_pct is not None else 0}%; background:{s['fill']};"></div>
                  </div>
                  <div class="step-meta">{f"{confidence_pct}% confidence" if confidence_pct is not None else "—"}{f" · {ev['duration_ms']:.1f} ms" if ev else ""}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with st.expander("Step-by-step input / output detail", expanded=False):
        tabs = st.tabs([f"{i+1}. {a}" for i, a in enumerate(AGENT_ORDER) if a in by_agent])
        reached = [a for a in AGENT_ORDER if a in by_agent]
        for tab, agent_name in zip(tabs, reached):
            ev = by_agent[agent_name]
            with tab:
                if ev["errors"]:
                    for err in ev["errors"]:
                        st.error(err, icon="⚠️")
                c1, c2 = st.columns(2)
                with c1:
                    st.caption("Input summary")
                    st.json(ev["input_summary"])
                with c2:
                    st.caption("Output summary")
                    st.json(ev["output_summary"])


def render_phi_boundary(case_obj: dict) -> None:
    st.markdown('<p class="section-title">PHI boundary</p>', unsafe_allow_html=True)
    st.caption("Identifiers stay on the case object and are never forwarded to downstream agents.")
    col1, col2 = st.columns(2)

    identifiers = case_obj.get("identifiers") or {}
    id_fields = ["name", "mrn", "dob", "address", "phone"]
    id_rows = "".join(
        f"<div><span style='color:#b8860b'>{f}:</span> {identifiers.get(f) or '<span style=\"color:#c9a227\">not detected</span>'}</div>"
        for f in id_fields
    )
    if not any(identifiers.get(f) for f in id_fields):
        id_rows = "<div style='color:#b8860b'>No identifiers detected in this note.</div>"

    with col1:
        st.markdown(
            f"""
            <div class="phi-panel" style="background:#fff8e6; border-color:#ffe6a3;">
              <div class="kicker" style="color:#a86400;">Case identifiers &middot; never forwarded</div>
              <dl>{id_rows}</dl>
            </div>
            """,
            unsafe_allow_html=True,
        )

    facts = case_obj.get("clinical_facts")
    if facts:
        diag = (facts.get("diagnosis") or "")[:100]
        masked_rows = f"""
            <div><span style='color:#0a7d0a'>phi_detected:</span> {facts.get('phi_detected')}</div>
            <div><span style='color:#0a7d0a'>phi_fields_masked:</span> {', '.join(facts.get('phi_fields_masked') or []) or 'none'}</div>
            <div><span style='color:#0a7d0a'>diagnosis:</span> {diag}{'…' if len(facts.get('diagnosis') or '') > 100 else ''}</div>
            <div><span style='color:#0a7d0a'>requested_procedure:</span> {facts.get('requested_procedure')}</div>
        """
    else:
        masked_rows = "<div style='color:#0a7d0a'>No clinical facts extracted (pipeline stopped before completion).</div>"

    with col2:
        st.markdown(
            f"""
            <div class="phi-panel" style="background:#eaf9ea; border-color:#c3edc3;">
              <div class="kicker" style="color:#0a7d0a;">Sent to agents &middot; zero PHI</div>
              <dl>{masked_rows}</dl>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_form(case_obj: dict) -> None:
    form = case_obj.get("form")
    if not form:
        return
    st.markdown('<p class="section-title">Prior-authorization form</p>', unsafe_allow_html=True)
    m1, m2, m3 = st.columns(3)
    for col, label, value in (
        (m1, "Template", form["form_template_id"]),
        (m2, "ICD-10", form["icd10_code"]),
        (m3, "Policy", form["policy_id"]),
    ):
        col.markdown(
            f"""<div style="font-size:0.72rem;color:#898781;font-weight:600;text-transform:uppercase;
            letter-spacing:0.03em;">{label}</div>
            <div style="font-size:1.15rem;font-weight:700;color:#171a22;font-family:'JetBrains Mono',monospace;
            word-break:break-word;">{value}</div>""",
            unsafe_allow_html=True,
        )

    st.table(
        [
            {"Field": f["name"], "Value": f["value"], "Required": "✓" if f["required"] else ""}
            for f in form["fields"]
        ]
    )
    for err in form.get("validation_errors", []):
        st.error(err, icon="⚠️")


def main() -> None:
    st.set_page_config(page_title="Prior Auth Workflow", page_icon="🩺", layout="wide")
    inject_css()

    workflow = get_workflow()
    samples = load_sample_cases()

    with st.sidebar:
        st.markdown("### Submit a case")
        options = ["Custom note…"] + [
            f"{c['case_id']} — {c['specialty']}" + (f" · {c['requested_procedure']}" if c["requested_procedure"] else "")
            for c in samples
        ]
        choice = st.selectbox("Sample doctor notes", options)

        if choice != "Custom note…":
            selected = samples[options.index(choice) - 1]
            default_note, default_specialty, default_case_id = (
                selected["note_text"], selected["specialty"], selected["case_id"],
            )
        else:
            default_note, default_specialty, default_case_id = "", "unknown", "UI-0001"

        specialties = ["unknown", "orthopedics", "cardiology", "oncology", "neurology", "gastroenterology", "rare_disease", "general"]
        specialty = st.selectbox(
            "Specialty", specialties,
            index=specialties.index(default_specialty) if default_specialty in specialties else 0,
        )
        case_id = st.text_input("Case ID", value=default_case_id)
        note_text = st.text_area("Doctor's note", value=default_note, height=260)
        run_clicked = st.button("Run workflow", type="primary", use_container_width=True)

        st.markdown("---")
        st.caption(
            "Every run executes the real pipeline — PHI masking, ICD-10 knowledge-graph coding "
            "with a rare-disease confidence gate, insurer policy retrieval, and form filling — "
            "against the actual agent code. Nothing here is mocked."
        )

    render_hero()

    if run_clicked:
        if not note_text.strip():
            st.error("Please enter or select a doctor's note first.")
        else:
            t0 = time.perf_counter()
            case, trace = workflow.run(case_id, note_text, specialty=specialty, persist_trace=False)
            total_ms = (time.perf_counter() - t0) * 1000
            st.session_state["last_result"] = {
                "case": case.model_dump(mode="json"),
                "trace": trace.model_dump(mode="json"),
                "total_duration_ms": total_ms,
            }

    result = st.session_state.get("last_result")
    if not result:
        st.info("Submit a case in the sidebar to see it move through the agent chain.", icon="👈")
        return

    case_obj = result["case"]
    render_status_banner(case_obj["status"], case_obj.get("suspension_reason"), result["total_duration_ms"])
    st.write("")
    render_pipeline(result["trace"]["events"])
    st.write("")
    render_phi_boundary(case_obj)
    st.write("")
    render_form(case_obj)

    with st.expander("Raw audit trace (JSON)"):
        st.json(result["trace"])


if __name__ == "__main__":
    main()
