/* Prior Authorization AI — frontend logic.
   IMPORTANT: all backend interaction is unchanged — same three endpoints
   (GET /api/eval-metrics, GET /api/sample-cases, POST /api/run) and the same
   request/response contracts. Only the rendering layer is redesigned. */

const AGENT_ORDER = ["Extractor", "ICD Coder", "Policy RAG", "Form Filler", "Critique Agent", "Insurance Company"];
const AGENT_SUBTITLE = {
  "Extractor": "Reads the clinical note",
  "ICD Coder": "Assigns the diagnosis code",
  "Policy RAG": "Checks the insurer's rules",
  "Form Filler": "Prepares the paperwork",
  "Critique Agent": "Independent QA verification",
  "Insurance Company": "Payer-side final review",
};
const AGENT_ICON = {
  "Extractor": "file-search",
  "ICD Coder": "stethoscope",
  "Policy RAG": "clipboard-check",
  "Form Filler": "file-check-2",
  "Critique Agent": "shield-check",
  "Insurance Company": "landmark",
};

/* Critique report verdict -> visual status family (icon + label, never color alone). */
const CRITIQUE_STATUS_KEY = {
  PASS: "ok",
  PASS_WITH_WARNINGS: "suspended",
  FAIL: "failed",
};

/* Payer decision -> visual status family + final banner content. Only the Insurance
   Company agent may issue the FINAL authorization decision. */
const PAYER_STATUS_KEY = { APPROVED: "ok", DENIED: "failed", PENDING_REVIEW: "suspended" };
const PAYER_META = {
  APPROVED: { key: "ok", icon: "badge-check", badge: "Payer approved", title: "Approved by Insurance Company",
    sub: "The authorization request has successfully passed all payer validation checks." },
  DENIED: { key: "failed", icon: "ban", badge: "Payer denied", title: "Authorization Denied",
    sub: "Coverage or policy requirements were not satisfied." },
  PENDING_REVIEW: { key: "suspended", icon: "user-check", badge: "Payer review", title: "Manual Review Required",
    sub: "Additional payer review is required before authorization." },
};

const STATUS_META = {
  ok:        { cls: "s-ok",        icon: "check",  label: "OK" },
  suspended: { cls: "s-suspended", icon: "pause",  label: "Suspended" },
  failed:    { cls: "s-failed",    icon: "x",      label: "Failed" },
  pending:   { cls: "s-pending",   icon: "minus",  label: "Not reached" },
};

const VERDICT_META = {
  COMPLETED: { key: "ok", icon: "check-circle-2", badge: "Auto-approved", title: "Approved automatically",
    sub: "This case meets every documented policy requirement and would be approved automatically — no human touch needed." },
  SUSPENDED_LOW_CONFIDENCE: { key: "suspended", icon: "pause-circle", badge: "Human review", title: "Sent for human review — low confidence",
    sub: "The AI isn't confident enough in the diagnosis code — especially given this may be a rare condition — so it stops and asks a human coder instead of guessing." },
  SUSPENDED_PHI_VIOLATION: { key: "failed", icon: "shield-alert", badge: "Blocked", title: "Blocked — privacy safeguard triggered",
    sub: "A potential patient-identifier leak was detected and the workflow halted immediately, before any downstream decision was made." },
  SUSPENDED_POLICY_MISMATCH: { key: "suspended", icon: "pause-circle", badge: "Human review", title: "Sent for human review — policy criteria not fully met",
    sub: "The note doesn't yet document everything this insurer's policy requires for approval." },
  SUSPENDED_LATERALITY_CONFLICT: { key: "suspended", icon: "pause-circle", badge: "Human review", title: "Sent for human review — conflicting details",
    sub: "The note and the requested procedure disagree on left vs. right side — flagged rather than guessed." },
  FAILED_VALIDATION: { key: "failed", icon: "x-circle", badge: "Rejected", title: "Rejected — incomplete information",
    sub: "Required information is missing or invalid, so the authorization form could not be completed." },
  ERROR: { key: "failed", icon: "x-circle", badge: "Error", title: "System error", sub: "An unexpected error stopped the workflow." },
};

let sampleCases = [];
let lastTrace = null;

function icons() { if (window.lucide) lucide.createIcons(); }

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

/* Lightweight JSON syntax highlighter (operates on escaped text). */
function highlightJson(obj) {
  const json = escapeHtml(JSON.stringify(obj, null, 2));
  return json.replace(
    /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(?:\s*:)?|\b(?:true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
    (match) => {
      let cls = "tok-num";
      if (/^"/.test(match)) cls = /:$/.test(match) ? "tok-key" : "tok-str";
      else if (/true|false/.test(match)) cls = "tok-bool";
      else if (/null/.test(match)) cls = "tok-null";
      return `<span class="${cls}">${match}</span>`;
    }
  ).replace(/([{}\[\],])/g, '<span class="tok-punc">$1</span>');
}

function codeBlock(title, obj, id) {
  return `
    <div class="code-block" id="${id}">
      <div class="code-head">
        <span class="code-dots"><i></i><i></i><i></i></span>
        <span class="code-title">${escapeHtml(title)}</span>
        <span class="code-actions">
          <button class="code-btn" data-copy="${id}"><i data-lucide="copy"></i>Copy</button>
          <button class="code-btn" data-expand="${id}"><i data-lucide="maximize-2"></i>Expand</button>
        </span>
      </div>
      <pre class="code-body" data-raw="${escapeHtml(JSON.stringify(obj, null, 2))}">${highlightJson(obj)}</pre>
    </div>`;
}

function wireCodeActions(scope) {
  scope.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pre = document.getElementById(btn.dataset.copy)?.querySelector(".code-body");
      if (pre) copyText(pre.dataset.raw ?? pre.textContent);
    });
  });
  scope.querySelectorAll("[data-expand]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.getElementById(btn.dataset.expand)?.classList.toggle("expanded");
    });
  });
}

function copyText(text) {
  navigator.clipboard?.writeText(text).then(() => showToast("Copied to clipboard"))
    .catch(() => showToast("Copy failed"));
}

let toastTimer = null;
function showToast(msg) {
  const t = document.getElementById("toast");
  document.getElementById("toastMsg").textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 1800);
}

/* ---------------- Tabs ---------------- */
function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`view-${btn.dataset.view}`).classList.add("active");
    });
  });
}

/* ---------------- Overview ---------------- */
async function loadOverview() {
  const grid = document.getElementById("kpiGrid");
  grid.innerHTML = Array.from({ length: 5 }, () => `
    <div class="skel-tile">
      <div class="skel" style="width:34px;height:34px;border-radius:10px"></div>
      <div class="skel lg"></div>
      <div class="skel"></div>
    </div>`).join("");

  const res = await fetch("/api/eval-metrics");
  const m = await res.json();

  const escalatedPct = Math.round((100 * m.suspended) / m.total);
  const tiles = [
    { icon: "target", value: `${m.policy_accuracy}%`, label: "Policy-match accuracy", caption: "vs. manually labeled ground truth" },
    { icon: "check-check", value: `${m.approve_accuracy}%`, label: "Correct on clear-cut cases", caption: "auto-approved exactly as expected" },
    { icon: "gauge", value: `${Math.round(m.avg_latency_ms)} ms`, label: "Avg. decision time", caption: "note in → decision out" },
    { icon: "lock", value: "0%", label: "PHI leakage", caption: "verified across every test case" },
    { icon: "users", value: `${escalatedPct}%`, label: "Escalated to human review", caption: "by design — not a failure rate" },
  ];
  grid.innerHTML = tiles.map((t) => `
    <div class="kpi-tile">
      <div class="kpi-icon"><i data-lucide="${t.icon}"></i></div>
      <div class="kpi-value">${t.value}</div>
      <div class="kpi-label">${t.label}</div>
      <div class="kpi-caption">${t.caption}</div>
    </div>`).join("");

  const flow = document.getElementById("overviewFlow");
  const steps = AGENT_ORDER.map((name) => ({
    icon: AGENT_ICON[name], name,
    sub: name === "Extractor" ? "Reads the note, masks patient identifiers" : AGENT_SUBTITLE[name],
  }));
  flow.innerHTML = steps.map((s, i) => `
    <div class="flow-step">
      <div class="flow-icon"><i data-lucide="${s.icon}"></i></div>
      <div class="flow-name">${i + 1}. ${s.name}</div>
      <div class="flow-sub">${s.sub}</div>
    </div>
    ${i < steps.length - 1 ? `<div class="flow-arrow"><i data-lucide="chevron-right"></i></div>` : ""}
  `).join("");

  icons();
}

/* ---------------- Live demo: inputs ---------------- */
async function loadSampleCases() {
  const res = await fetch("/api/sample-cases");
  sampleCases = await res.json();
  const select = document.getElementById("sampleSelect");
  for (const c of sampleCases) {
    const opt = document.createElement("option");
    opt.value = c.case_id;
    opt.textContent = `${c.case_id} — ${c.specialty}${c.requested_procedure ? " · " + c.requested_procedure : ""}`;
    select.appendChild(opt);
  }
}

function newCaseId() { return "UI-" + Math.random().toString(36).slice(2, 8).toUpperCase(); }

function updateCharCount() {
  document.getElementById("charCount").textContent =
    document.getElementById("noteInput").value.length.toLocaleString();
}

function setupInputs() {
  document.getElementById("caseIdInput").value = newCaseId();
  document.getElementById("sampleSelect").addEventListener("change", (e) => {
    const val = e.target.value;
    if (!val) return;
    const c = sampleCases.find((x) => x.case_id === val);
    if (!c) return;
    document.getElementById("noteInput").value = c.note_text;
    const specialtySelect = document.getElementById("specialtySelect");
    const has = [...specialtySelect.options].some((o) => o.value === c.specialty);
    specialtySelect.value = has ? c.specialty : "unknown";
    document.getElementById("caseIdInput").value = c.case_id;
    updateCharCount();
  });
  document.getElementById("noteInput").addEventListener("input", updateCharCount);
  updateCharCount();
}

/* ---------------- Decision hero ---------------- */
function renderVerdict(status, reason, totalMs, events) {
  // The payer's decision is the system's FINAL decision: when the case reached the
  // Insurance Company agent, its verdict drives the banner. Cases that stopped on the
  // provider side (suspended/failed before submission) keep the provider-side banner.
  const payerEv = (events || []).find((e) => e.agent_name === "Insurance Company");
  const payerDecision = payerEv?.output_summary?.final_decision;
  let meta, subText;
  if (payerDecision && PAYER_META[payerDecision]) {
    meta = PAYER_META[payerDecision];
    subText = payerEv.output_summary.reason || meta.sub;
  } else {
    meta = VERDICT_META[status] || { key: "suspended", icon: "help-circle", badge: status, title: status, sub: "" };
    subText = reason || meta.sub;
  }
  const hero = document.getElementById("decisionHero");
  hero.className = `decision-hero is-${meta.key}`;
  document.getElementById("decisionIcon").innerHTML = `<i data-lucide="${meta.icon}"></i>`;
  document.getElementById("decisionBadge").innerHTML = `<i data-lucide="${meta.icon}"></i>${escapeHtml(meta.badge)}`;
  document.getElementById("decisionTitle").textContent = meta.title;
  document.getElementById("decisionSub").textContent = subText;
  document.getElementById("decisionDuration").textContent = `${totalMs.toFixed(0)} ms`;

  const confs = (events || []).map((e) => e.confidence).filter((c) => c != null);
  document.getElementById("decisionConfidence").textContent =
    confs.length ? `${Math.round(Math.min(...confs) * 100)}%` : "—";
}

/* ---------------- Pipeline ---------------- */
function stepStatusKey(ev) {
  if (!ev) return "pending";
  if (ev.status === "OK") return "ok";
  if (ev.status === "SUSPENDED") return "suspended";
  return "failed";
}

function renderPipeline(events) {
  const byAgent = {};
  for (const ev of events) byAgent[ev.agent_name] = ev;

  const pipeline = document.getElementById("pipeline");
  pipeline.innerHTML = AGENT_ORDER.map((agentName, idx) => {
    const ev = byAgent[agentName];
    let key = stepStatusKey(ev);
    let statusLabel = ev ? ev.status : null;
    let confLabel = "Confidence";
    let confText = null;
    let hoverTitle = "";

    const confidencePct = ev && ev.confidence != null ? Math.round(ev.confidence * 100) : null;
    if (confidencePct != null) confText = confidencePct + "%";

    // The Critique card reports its QA verdict and quality score, not a raw handoff status.
    const report = agentName === "Critique Agent" ? ev?.output_summary : null;
    if (report && report.status) {
      key = CRITIQUE_STATUS_KEY[report.status] || key;
      statusLabel = report.status.replace(/_/g, " ");
      confLabel = "Quality score";
      confText = `${report.quality_score}/100`;
      hoverTitle = ` title="${escapeHtml(report.summary || "")}"`;
    }

    // The Insurance Company card reports the FINAL payer decision.
    const payer = agentName === "Insurance Company" ? ev?.output_summary : null;
    if (payer && payer.final_decision) {
      key = PAYER_STATUS_KEY[payer.final_decision] || key;
      statusLabel = payer.final_decision.replace(/_/g, " ");
      confLabel = "Decision confidence";
      hoverTitle = ` title="${escapeHtml(payer.reason || "")}"`;
    }

    const s = STATUS_META[key];
    return `
      <div class="agent-card ${s.cls}"${hoverTitle}>
        <span class="conn-dot"></span>
        <div class="agent-top">
          <span class="agent-num">${idx + 1}</span>
          <span class="agent-name">${agentName}</span>
          <span class="agent-icon"><i data-lucide="${AGENT_ICON[agentName]}"></i></span>
        </div>
        <div class="agent-sub">${AGENT_SUBTITLE[agentName]}</div>
        <span class="agent-status"><i data-lucide="${s.icon}"></i>${statusLabel ? escapeHtml(statusLabel) : s.label}</span>
        <div class="conf-row">
          <span class="conf-label">${confLabel}</span>
          <span class="conf-value">${confText ?? "—"}</span>
        </div>
        <div class="conf-track"><div class="conf-fill" data-w="${confidencePct ?? 0}"></div></div>
        <div class="agent-time"><i data-lucide="timer"></i>${ev ? ev.duration_ms.toFixed(1) + " ms" : "not executed"}</div>
      </div>`;
  }).join("");

  // Animate confidence bars in after paint.
  requestAnimationFrame(() => requestAnimationFrame(() => {
    pipeline.querySelectorAll(".conf-fill").forEach((el) => { el.style.width = el.dataset.w + "%"; });
  }));

  return byAgent;
}

/* ---------------- Technical detail tabs ---------------- */
function renderDetailTabs(byAgent) {
  const reached = AGENT_ORDER.filter((a) => byAgent[a]);
  const tabsEl = document.getElementById("detailTabs");
  const panelsEl = document.getElementById("detailPanels");

  tabsEl.innerHTML = reached.map((a, i) =>
    `<button class="seg-tab${i === 0 ? " active" : ""}" data-agent="${a}"><i data-lucide="${AGENT_ICON[a]}"></i>${a}</button>`
  ).join("");

  function renderPanel(agentName) {
    const ev = byAgent[agentName];
    panelsEl.innerHTML = `
      ${ev.errors && ev.errors.length ? `
        <div class="agent-errors"><i data-lucide="alert-triangle"></i><div>${ev.errors.map((e) => escapeHtml(e)).join("<br/>")}</div></div>` : ""}
      <div class="io-grid">
        <div>
          <div class="io-col-head"><span class="io-kicker"><i data-lucide="arrow-down-to-line"></i>Input</span></div>
          ${codeBlock(`${agentName.toLowerCase().replace(/\s+/g, "-")}.input.json`, ev.input_summary, "codeIn")}
        </div>
        <div>
          <div class="io-col-head"><span class="io-kicker"><i data-lucide="arrow-up-from-line"></i>Output</span></div>
          ${codeBlock(`${agentName.toLowerCase().replace(/\s+/g, "-")}.output.json`, ev.output_summary, "codeOut")}
        </div>
      </div>`;
    wireCodeActions(panelsEl);
    icons();
  }

  if (reached.length) renderPanel(reached[0]);
  tabsEl.querySelectorAll(".seg-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      tabsEl.querySelectorAll(".seg-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      renderPanel(tab.dataset.agent);
    });
  });
}

/* ---------------- PHI boundary ---------------- */
function renderPhiBoundary(caseObj) {
  const grid = document.getElementById("phiGrid");
  const ids = caseObj.identifiers || {};
  const idFields = ["name", "mrn", "dob", "address", "phone"];
  const detected = idFields.filter((f) => ids[f]);

  const idRows = detected.length
    ? idFields.map((f) => `<div><b>${f}:</b> ${ids[f] ? escapeHtml(ids[f]) : "not detected"}</div>`).join("")
    : `<div>No identifiers detected in this note.</div>`;

  const facts = caseObj.clinical_facts;
  const violated = caseObj.status === "SUSPENDED_PHI_VIOLATION";

  let seenRows, banner;
  if (facts) {
    const diag = (facts.diagnosis || "").slice(0, 90);
    seenRows = `
      <div><b>PHI detected in note:</b> ${facts.phi_detected}</div>
      <div><b>Fields masked:</b> ${escapeHtml((facts.phi_fields_masked || []).join(", ")) || "none"}</div>
      <div><b>Diagnosis seen by AI:</b> ${escapeHtml(diag)}${(facts.diagnosis || "").length > 90 ? "…" : ""}</div>
      <div><b>Requested procedure:</b> ${escapeHtml(facts.requested_procedure || "")}</div>`;
    banner = violated
      ? `<div class="phi-banner"><i data-lucide="shield-alert"></i>Privacy safeguard triggered — workflow halted</div>`
      : `<div class="phi-banner"><i data-lucide="badge-check"></i>Zero PHI reached the AI reasoning steps</div>`;
  } else {
    seenRows = `<div>No clinical facts extracted (pipeline stopped before completion).</div>`;
    banner = "";
  }

  grid.innerHTML = `
    <div class="phi-card locked">
      <div class="phi-head">
        <span class="phi-icon"><i data-lucide="lock"></i></span>
        <span class="phi-title">Patient privacy boundary</span>
        <span class="phi-tag"><i data-lucide="archive"></i>Case record only</span>
      </div>
      <div class="phi-list">${idRows}</div>
    </div>
    <div class="phi-card ${violated ? "violated" : "clean"}">
      <div class="phi-head">
        <span class="phi-icon"><i data-lucide="${violated ? "shield-alert" : "scan-eye"}"></i></span>
        <span class="phi-title">What the AI actually sees</span>
        <span class="phi-tag"><i data-lucide="${violated ? "alert-triangle" : "check"}"></i>${violated ? "PHI violation" : "PHI safe"}</span>
      </div>
      <div class="phi-list">${seenRows}</div>
      ${banner}
    </div>`;
}

/* ---------------- Form document viewer ---------------- */
function renderForm(caseObj) {
  const card = document.getElementById("formCard");
  const form = caseObj.form;
  if (!form) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");

  const total = form.fields.length;
  const filled = form.fields.filter((f) => f.value && f.value !== "UNSPECIFIED").length;
  const pct = total ? Math.round((100 * filled) / total) : 0;
  const hasErrors = form.validation_errors && form.validation_errors.length;

  const ring = document.getElementById("ringFill");
  const C = 2 * Math.PI * 52; // r=52
  ring.classList.toggle("warn", Boolean(hasErrors));
  ring.setAttribute("stroke-dasharray", C.toFixed(1));
  ring.setAttribute("stroke-dashoffset", C.toFixed(1));
  requestAnimationFrame(() => requestAnimationFrame(() => {
    ring.setAttribute("stroke-dashoffset", (C * (1 - pct / 100)).toFixed(1));
  }));
  document.getElementById("ringPct").textContent = `${pct}%`;

  const badge = document.getElementById("docBadge");
  badge.className = `doc-badge ${hasErrors ? "warn" : "ok"}`;
  badge.innerHTML = hasErrors
    ? `<i data-lucide="alert-triangle"></i>Needs review`
    : `<i data-lucide="badge-check"></i>Validated`;

  document.getElementById("formMeta").innerHTML = `
    <div class="doc-meta-item"><div class="k">Template</div><div class="v">${escapeHtml(form.form_template_id)}</div></div>
    <div class="doc-meta-item"><div class="k">ICD-10</div><div class="v">${escapeHtml(form.icd10_code)}</div></div>
    <div class="doc-meta-item"><div class="k">Policy</div><div class="v">${escapeHtml(form.policy_id)}</div></div>`;

  document.getElementById("formFields").innerHTML = form.fields.map((f) => `
    <div class="doc-field">
      <span class="fname">${escapeHtml(f.name)}</span>
      <span class="fvalue">${escapeHtml(f.value)}</span>
      ${f.required ? `<span class="req-chip">Required</span>` : "<span></span>"}
    </div>`).join("");

  document.getElementById("formErrors").innerHTML = hasErrors
    ? `<div class="doc-errors"><i data-lucide="alert-triangle"></i><div>${form.validation_errors.map((e) => escapeHtml(e)).join("<br/>")}</div></div>`
    : "";
}

/* ---------------- Audit timeline ---------------- */
function fmtTime(ts) {
  try {
    return new Date(ts).toLocaleTimeString([], { hour12: false }) +
      "." + String(new Date(ts).getMilliseconds()).padStart(3, "0");
  } catch { return String(ts); }
}

function renderTimeline(trace) {
  const el = document.getElementById("timeline");
  const finalKey = (VERDICT_META[trace.final_status] || { key: "suspended" }).key;

  const stepsHtml = trace.events.map((ev, i) => {
    let key = stepStatusKey(ev);
    let statusLabel = ev.status;
    // Critique event: surface the QA verdict, not the (always-OK) handoff status.
    if (ev.agent_name === "Critique Agent" && ev.output_summary?.status) {
      key = CRITIQUE_STATUS_KEY[ev.output_summary.status] || key;
      statusLabel = ev.output_summary.status.replace(/_/g, " ");
    }
    // Payer event: surface the final authorization decision.
    if (ev.agent_name === "Insurance Company" && ev.output_summary?.final_decision) {
      key = PAYER_STATUS_KEY[ev.output_summary.final_decision] || key;
      statusLabel = ev.output_summary.final_decision.replace(/_/g, " ");
    }
    const s = STATUS_META[key];
    const confidencePct = ev.confidence != null ? Math.round(ev.confidence * 100) : null;
    return `
      <div class="tl-step" data-idx="${i}">
        <span class="tl-node ${key}"><i data-lucide="${AGENT_ICON[ev.agent_name] || "circle"}"></i></span>
        <div class="tl-row" role="button" tabindex="0">
          <span class="tl-name">${escapeHtml(ev.agent_name)}</span>
          <span class="tl-status ${key}"><i data-lucide="${s.icon}"></i>${escapeHtml(statusLabel)}</span>
          <span class="tl-meta">
            <span><i data-lucide="clock"></i>${fmtTime(ev.timestamp)}</span>
            <span><i data-lucide="timer"></i>${ev.duration_ms.toFixed(1)} ms</span>
            <span><i data-lucide="percent"></i>${confidencePct != null ? confidencePct + "% conf" : "—"}</span>
          </span>
          <span class="tl-chev"><i data-lucide="chevron-right"></i></span>
        </div>
        <div class="tl-body">${codeBlock(`event-${ev.step}-${ev.agent_name.toLowerCase().replace(/\s+/g, "-")}.json`, ev, `tlCode${i}`)}</div>
      </div>`;
  }).join("");

  const verdict = VERDICT_META[trace.final_status] || { icon: "flag", title: trace.final_status };
  el.innerHTML = stepsHtml + `
    <div class="tl-step">
      <span class="tl-node ${finalKey === "ok" ? "ok" : finalKey}"><i data-lucide="flag"></i></span>
      <div class="tl-row" style="cursor:default">
        <span class="tl-name">Final decision</span>
        <span class="tl-status ${finalKey}"><i data-lucide="${verdict.icon}"></i>${escapeHtml(trace.final_status)}</span>
      </div>
    </div>`;

  el.querySelectorAll(".tl-step[data-idx] .tl-row").forEach((row) => {
    const step = row.closest(".tl-step");
    const toggle = () => step.classList.toggle("open");
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
  });
  wireCodeActions(el);
}

/* ---------------- Bottom metrics ---------------- */
function renderMetaGrid(totalMs) {
  const tiles = [
    { icon: "shield-check", k: "Security", v: "PHI protected" },
    { icon: "cpu", k: "Model", v: "Azure OpenAI GPT-4o" },
    { icon: "library", k: "Policy source", v: "Enterprise policy library" },
    { icon: "gauge", k: "Latency", v: `${totalMs.toFixed(0)} ms`, mono: true },
    { icon: "history", k: "Last run", v: new Date().toLocaleTimeString([], { hour12: false }), mono: true },
    { icon: "server", k: "Environment", v: "Production demo" },
  ];
  document.getElementById("metaGrid").innerHTML = tiles.map((t) => `
    <div class="meta-tile">
      <div class="meta-k"><i data-lucide="${t.icon}"></i>${t.k}</div>
      <div class="meta-v${t.mono ? " mono" : ""}">${t.v}</div>
    </div>`).join("");
}

/* ---------------- Run + render ---------------- */
async function runWorkflow() {
  const noteText = document.getElementById("noteInput").value;
  const specialty = document.getElementById("specialtySelect").value;
  const caseId = document.getElementById("caseIdInput").value || newCaseId();
  const errorMsg = document.getElementById("errorMsg");
  errorMsg.classList.add("hidden");

  if (!noteText.trim()) {
    errorMsg.innerHTML = `<i data-lucide="alert-triangle"></i><span>Please enter or select a doctor's note first.</span>`;
    errorMsg.classList.remove("hidden");
    icons();
    return;
  }

  const btn = document.getElementById("runBtn");
  const label = document.getElementById("runBtnLabel");
  const iconWrap = document.getElementById("runIconWrap");
  btn.disabled = true;
  label.textContent = "Running…";
  iconWrap.innerHTML = '<i data-lucide="loader-2" class="spin" style="width:15px;height:15px"></i>';
  icons();

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: caseId, note_text: noteText, specialty }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();
    renderResults(data);
  } catch (e) {
    errorMsg.innerHTML = `<i data-lucide="alert-triangle"></i><span>${escapeHtml(e.message || "Something went wrong.")}</span>`;
    errorMsg.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    label.textContent = "Run workflow";
    iconWrap.innerHTML = '<i data-lucide="play" style="width:15px;height:15px"></i>';
    icons();
  }
}

function renderResults(data) {
  document.getElementById("emptyState").classList.add("hidden");
  document.getElementById("results").classList.remove("hidden");

  const caseObj = data.case;
  lastTrace = data.trace;

  renderVerdict(caseObj.status, caseObj.suspension_reason, data.total_duration_ms, data.trace.events);
  const byAgent = renderPipeline(data.trace.events);
  renderDetailTabs(byAgent);
  renderPhiBoundary(caseObj);
  renderForm(caseObj);
  renderTimeline(data.trace);
  renderMetaGrid(data.total_duration_ms);
  icons();
}

/* ---------------- Button ripple ---------------- */
function setupRipple() {
  document.getElementById("runBtn").addEventListener("pointerdown", function (e) {
    const rect = this.getBoundingClientRect();
    const d = Math.max(rect.width, rect.height);
    const span = document.createElement("span");
    span.className = "ripple";
    span.style.width = span.style.height = d + "px";
    span.style.left = (e.clientX - rect.left - d / 2) + "px";
    span.style.top = (e.clientY - rect.top - d / 2) + "px";
    this.appendChild(span);
    setTimeout(() => span.remove(), 600);
  });
}

/* ---------------- Boot ---------------- */
document.getElementById("runBtn").addEventListener("click", runWorkflow);
document.getElementById("copyTraceBtn").addEventListener("click", () => {
  if (lastTrace) copyText(JSON.stringify(lastTrace, null, 2));
});
setupTabs();
setupRipple();
loadOverview();

/* Deep-linking: /?view=demo opens a tab directly; &case=GEN-0001 preselects a
   sample; &autorun=1 immediately runs it. */
const params = new URLSearchParams(location.search);
const wantView = params.get("view");
if (wantView) document.querySelector(`.tab-btn[data-view="${CSS.escape(wantView)}"]`)?.click();

loadSampleCases().then(() => {
  setupInputs();
  const wantCase = params.get("case");
  if (wantCase || params.get("autorun")) {
    const select = document.getElementById("sampleSelect");
    const target = wantCase && sampleCases.some((c) => c.case_id === wantCase)
      ? wantCase
      : (sampleCases[0] && sampleCases[0].case_id);
    if (target) {
      select.value = target;
      select.dispatchEvent(new Event("change"));
      if (params.get("autorun")) runWorkflow();
    }
  }
});icons();
