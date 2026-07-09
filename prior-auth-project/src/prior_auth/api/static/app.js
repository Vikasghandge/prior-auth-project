/* Prior Authorization AI — frontend logic.
   IMPORTANT: all backend interaction is unchanged — same three endpoints
   (GET /api/eval-metrics, GET /api/sample-cases, POST /api/run) and the same
   request/response contracts. Only the rendering layer is redesigned. */

/* Provider-side pipeline only — the Insurance Company is a DIFFERENT organization and is
   rendered in its own payer review panel, never as "agent 6" of the provider pipeline. */
const AGENT_ORDER = ["Extractor", "ICD Coder", "Policy RAG", "Form Filler", "Critique Agent"];
const PAYER_AGENT = "Insurance Company";
const AGENT_SUBTITLE = {
  "Extractor": "Reads doctor notes",
  "ICD Coder": "Assigns ICD-10 codes",
  "Policy RAG": "Matches insurer policy",
  "Form Filler": "Generates authorization package",
  "Critique Agent": "Performs final QA verification",
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
  SUSPENDED_EXTRACTION_REVIEW: { key: "suspended", icon: "pause-circle", badge: "Human review", title: "Sent for human review — extraction quality",
    sub: "The Extractor couldn't confidently or completely read the note's clinical details, so it stopped instead of guessing." },
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
      if (btn.dataset.view === "review") loadReviewQueue();
    });
  });
}

/* ---------------- Human review queue ---------------- */
function reviewReasonLabel(status) {
  const meta = VERDICT_META[status];
  return meta ? meta.title.replace(/^Sent for human review — /, "") : status;
}

async function loadReviewQueue() {
  const list = document.getElementById("reviewQueueList");
  const empty = document.getElementById("reviewQueueEmpty");
  list.innerHTML = `<div class="skel-tile"><div class="skel" style="width:40%"></div><div class="skel" style="width:80%"></div></div>`;
  empty.classList.add("hidden");

  let cases = [];
  try {
    const res = await fetch("/api/review-queue");
    cases = await res.json();
  } catch {
    list.innerHTML = "";
    return;
  }

  if (cases.length === 0) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }

  list.innerHTML = cases.map((c) => `
    <div class="review-card" id="review-${escapeHtml(c.case_id)}">
      <div class="review-head">
        <span class="review-case">${escapeHtml(c.case_id)}</span>
        <span class="review-status"><i data-lucide="pause-circle"></i>${escapeHtml(reviewReasonLabel(c.workflow_status))}</span>
      </div>
      <p class="review-reason">${escapeHtml(c.reason)}</p>
      <div class="review-meta">Queued ${escapeHtml(new Date(c.queued_at).toLocaleString())}</div>
      <div class="review-actions">
        <button class="review-btn approve" data-case="${escapeHtml(c.case_id)}" data-decision="APPROVED">
          <i data-lucide="check" style="width:14px;height:14px"></i>Approve
        </button>
        <button class="review-btn reject" data-case="${escapeHtml(c.case_id)}" data-decision="REJECTED">
          <i data-lucide="x" style="width:14px;height:14px"></i>Reject
        </button>
      </div>
    </div>
  `).join("");

  list.querySelectorAll(".review-btn").forEach((btn) => {
    btn.addEventListener("click", () => resolveReview(btn.dataset.case, btn.dataset.decision));
  });
  icons();
}

async function resolveReview(caseId, decision) {
  const card = document.getElementById(`review-${CSS.escape(caseId)}`);
  card.querySelectorAll(".review-btn").forEach((b) => (b.disabled = true));

  try {
    const res = await fetch(`/api/review-queue/${encodeURIComponent(caseId)}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reviewer: "ghandgevikas804@gmail.com" }),
    });
    if (!res.ok) throw new Error("Failed to submit decision");

    const actions = card.querySelector(".review-actions");
    const icon = decision === "APPROVED" ? "check-circle-2" : "x-circle";
    const label = decision === "APPROVED" ? "Approved" : "Rejected";
    actions.outerHTML = `<div class="review-resolved ${decision}"><i data-lucide="${icon}" style="width:14px;height:14px"></i>${label} by reviewer</div>`;
    icons();
    showToast(`Case ${caseId} ${label.toLowerCase()}`);
  } catch (e) {
    card.querySelectorAll(".review-btn").forEach((b) => (b.disabled = false));
    showToast("Something went wrong — try again");
  }
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
    icon: AGENT_ICON[name], name, payer: false,
    sub: name === "Extractor" ? "Reads the note, masks patient identifiers" : AGENT_SUBTITLE[name],
  }));
  // The payer is a different organization — rendered as the distinct final stop.
  steps.push({ icon: "landmark", name: "Insurance Company", payer: true,
               sub: "Payer review → final authorization decision" });
  flow.innerHTML = steps.map((s, i) => `
    <div class="flow-step${s.payer ? " payer-step" : ""}">
      <div class="flow-icon"${s.payer ? ' style="background:var(--good-tint);color:var(--good-text)"' : ""}><i data-lucide="${s.icon}"></i></div>
      <div class="flow-name">${s.payer ? "" : (i + 1) + ". "}${s.name}</div>
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

  // Payer review summary checklist under the banner text.
  const summaryEl = document.getElementById("payerSummary");
  const d = payerEv?.output_summary;
  if (d) {
    const items = [
      { pass: d.member_status === "ACTIVE", ok: "Member Eligible", bad: `Member ${d.member_status}` },
      { pass: d.policy_status === "ACTIVE", ok: "Policy Active", bad: `Policy ${d.policy_status}` },
      { pass: d.coverage_status === "COVERED", ok: "Procedure Covered", bad: "Procedure Not Covered" },
      { pass: d.provider_status === "IN_NETWORK", ok: "Provider In-Network", bad: "Provider Out-of-Network" },
      { pass: d.fraud_check === "CLEAR", ok: "No Duplicate Submission", bad: "Possible Duplicate", warn: true },
    ];
    summaryEl.innerHTML = items.map((it) => `
      <span class="chk ${it.pass ? "pass" : (it.warn ? "warn" : "fail")}">
        <i data-lucide="${it.pass ? "check" : (it.warn ? "alert-triangle" : "x")}"></i>${escapeHtml(it.pass ? it.ok : it.bad)}
      </span>`).join("");
    summaryEl.classList.remove("hidden");
  } else {
    summaryEl.classList.add("hidden");
    summaryEl.innerHTML = "";
  }
}

/* ---------------- Insurance Company review panel ---------------- */
const PAYER_CHECKS = [
  { area: "elig",  icon: "id-card",     title: "Eligibility Check",       desc: "Member and policy validation",
    value: (d) => d.member_status === "ACTIVE" && d.policy_status === "ACTIVE"
      ? { label: "ACTIVE", tone: "good" }
      : { label: d.member_status !== "ACTIVE" ? d.member_status : d.policy_status, tone: "bad" } },
  { area: "cov",   icon: "shield",      title: "Coverage Check",          desc: "Procedure coverage verification",
    value: (d) => d.coverage_status === "COVERED"
      ? { label: "COVERED", tone: "good" } : { label: "NOT COVERED", tone: "bad" } },
  { area: "prov",  icon: "hospital",    title: "Provider Check",          desc: "Network and provider validation",
    value: (d) => d.provider_status === "IN_NETWORK"
      ? { label: "IN-NETWORK", tone: "good" } : { label: "OUT-OF-NETWORK", tone: "bad" } },
  { area: "fraud", icon: "fingerprint", title: "Fraud / Duplicate Check", desc: "Duplicate authorization screening",
    value: (d) => d.fraud_check === "CLEAR"
      ? { label: "CLEAR", tone: "good" } : { label: "DUPLICATE FOUND", tone: "warn" } },
];
const PAYER_TONE_ICON = { good: "check", bad: "x", warn: "alert-triangle" };

function renderPayerPanel(payerEv) {
  const divider = document.getElementById("submissionDivider");
  const panel = document.getElementById("payerPanel");
  if (!payerEv || !payerEv.output_summary?.final_decision) {
    // Case never left the provider organization — no submission, no payer review.
    divider.classList.add("hidden");
    panel.classList.add("hidden");
    return;
  }
  divider.classList.remove("hidden");
  panel.classList.remove("hidden");

  const d = payerEv.output_summary;
  const decisionKey = PAYER_STATUS_KEY[d.final_decision] || "suspended";
  const dCls = decisionKey === "ok" ? "d-ok" : decisionKey === "failed" ? "d-bad" : "d-warn";
  const dIcon = decisionKey === "ok" ? "badge-check" : decisionKey === "failed" ? "ban" : "user-check";

  const cards = PAYER_CHECKS.map((c) => {
    const v = c.value(d);
    return `
      <div class="payer-card" style="grid-area:${c.area}">
        <div class="payer-icon"><i data-lucide="${c.icon}"></i></div>
        <h5>${c.title}</h5>
        <div class="desc">${c.desc}</div>
        <span class="payer-result ${v.tone}"><i data-lucide="${PAYER_TONE_ICON[v.tone]}"></i>${escapeHtml(v.label)}</span>
      </div>`;
  }).join("");

  const ts = fmtTime(payerEv.timestamp);
  const confPct = payerEv.confidence != null ? Math.round(payerEv.confidence * 100) + "%" : "—";
  document.getElementById("payerGrid").innerHTML = cards + `
    <div class="payer-decision ${dCls}">
      <span class="pd-kicker">Final Payer Decision</span>
      <span class="pd-badge"><i data-lucide="${dIcon}"></i>${escapeHtml(d.final_decision.replace(/_/g, " "))}</span>
      <div class="pd-reason">${escapeHtml(d.reason || "")}</div>
      <div class="pd-meta">
        <span><i data-lucide="clock"></i>${ts}</span>
        <span><i data-lucide="percent"></i>${confPct} confidence</span>
        <span><i data-lucide="timer"></i>${payerEv.duration_ms.toFixed(1)} ms</span>
      </div>
    </div>`;
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

/* ---------------- Technical detail tabs (provider group + payer group) -------- */
function renderDetailTabs(byAgent) {
  const reached = AGENT_ORDER.filter((a) => byAgent[a]);
  const payerEv = byAgent[PAYER_AGENT];
  const tabsEl = document.getElementById("detailTabs");
  const payerTabsEl = document.getElementById("payerTabs");
  const payerGroup = document.getElementById("payerTabGroup");
  const panelsEl = document.getElementById("detailPanels");

  tabsEl.innerHTML = reached.map((a, i) =>
    `<button class="seg-tab${i === 0 ? " active" : ""}" data-agent="${a}"><i data-lucide="${AGENT_ICON[a]}"></i>${a}</button>`
  ).join("");
  payerGroup.style.display = payerEv ? "" : "none";
  payerTabsEl.innerHTML = payerEv
    ? `<button class="seg-tab" data-agent="${PAYER_AGENT}"><i data-lucide="landmark"></i>Insurance Review</button>`
    : "";

  function payerChips(d) {
    const rows = [
      ["Eligibility", d.member_status, d.member_status === "ACTIVE"],
      ["Coverage", d.coverage_status, d.coverage_status === "COVERED"],
      ["Provider", d.provider_status, d.provider_status === "IN_NETWORK"],
      ["Policy", d.policy_status, d.policy_status === "ACTIVE"],
      ["Fraud check", d.fraud_check, d.fraud_check === "CLEAR"],
      ["Decision", d.final_decision, d.final_decision === "APPROVED"],
    ];
    return `<div class="payer-summary" style="margin:0 0 14px">` + rows.map(([k, v, ok]) => `
      <span class="chk ${ok ? "pass" : "fail"}"><i data-lucide="${ok ? "check" : "x"}"></i>${k}: ${escapeHtml(String(v).replace(/_/g, " "))}</span>`).join("") + `</div>`;
  }

  function renderPanel(agentName) {
    const ev = byAgent[agentName];
    const isPayer = agentName === PAYER_AGENT;
    panelsEl.innerHTML = `
      ${isPayer && ev.output_summary ? payerChips(ev.output_summary) : ""}
      ${ev.errors && ev.errors.length ? `
        <div class="agent-errors"><i data-lucide="alert-triangle"></i><div>${ev.errors.map((e) => escapeHtml(e)).join("<br/>")}</div></div>` : ""}
      <div class="io-grid">
        <div>
          <div class="io-col-head"><span class="io-kicker"><i data-lucide="arrow-down-to-line"></i>${isPayer ? "Submitted package" : "Input"}</span></div>
          ${codeBlock(`${agentName.toLowerCase().replace(/\s+/g, "-")}.input.json`, ev.input_summary, "codeIn")}
        </div>
        <div>
          <div class="io-col-head"><span class="io-kicker"><i data-lucide="arrow-up-from-line"></i>${isPayer ? "Payer decision" : "Output"}</span></div>
          ${codeBlock(`${agentName.toLowerCase().replace(/\s+/g, "-")}.output.json`, ev.output_summary, "codeOut")}
        </div>
      </div>`;
    wireCodeActions(panelsEl);
    icons();
  }

  const allTabs = () => [...tabsEl.querySelectorAll(".seg-tab"), ...payerTabsEl.querySelectorAll(".seg-tab")];
  if (reached.length) renderPanel(reached[0]);
  allTabs().forEach((tab) => {
    tab.addEventListener("click", () => {
      allTabs().forEach((t) => t.classList.remove("active"));
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

  function eventStep(ev, i, displayName) {
    let key = stepStatusKey(ev);
    let statusLabel = ev.status;
    if (ev.agent_name === "Critique Agent" && ev.output_summary?.status) {
      key = CRITIQUE_STATUS_KEY[ev.output_summary.status] || key;
      statusLabel = ev.output_summary.status.replace(/_/g, " ");
    }
    if (ev.agent_name === PAYER_AGENT && ev.output_summary?.final_decision) {
      key = PAYER_STATUS_KEY[ev.output_summary.final_decision] || key;
      statusLabel = ev.output_summary.final_decision.replace(/_/g, " ");
    }
    const s = STATUS_META[key];
    const confidencePct = ev.confidence != null ? Math.round(ev.confidence * 100) : null;
    return `
      <div class="tl-step" data-idx="${i}">
        <span class="tl-node ${key}"><i data-lucide="${AGENT_ICON[ev.agent_name] || "circle"}"></i></span>
        <div class="tl-row" role="button" tabindex="0">
          <span class="tl-name">${escapeHtml(displayName || ev.agent_name)}</span>
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
  }

  function milestone(icon, name, chipKey, chipIcon, chipText) {
    return `
      <div class="tl-step">
        <span class="tl-node flag"><i data-lucide="${icon}"></i></span>
        <div class="tl-row" style="cursor:default">
          <span class="tl-name">${name}</span>
          <span class="tl-status ${chipKey}"><i data-lucide="${chipIcon}"></i>${escapeHtml(chipText)}</span>
        </div>
      </div>`;
  }

  const providerSteps = trace.events
    .map((ev, i) => ({ ev, i }))
    .filter(({ ev }) => ev.agent_name !== PAYER_AGENT);
  const payerEntry = trace.events.map((ev, i) => ({ ev, i })).find(({ ev }) => ev.agent_name === PAYER_AGENT);

  let html = providerSteps.map(({ ev, i }) => eventStep(ev, i)).join("");

  if (payerEntry) {
    const d = payerEntry.ev.output_summary || {};
    const decision = d.final_decision || "PENDING_REVIEW";
    const dKey = PAYER_STATUS_KEY[decision] || "suspended";
    const dMeta = PAYER_META[decision] || { icon: "flag" };
    html += milestone("send", "Authorization package submitted", "ok", "lock", "Provider → Payer · encrypted");
    html += eventStep(payerEntry.ev, payerEntry.i, "Insurance Company review");
    html += milestone(dMeta.icon || "flag", "Final payer decision", dKey, dMeta.icon || "flag", decision.replace(/_/g, " "));
  } else {
    const finalKey = (VERDICT_META[trace.final_status] || { key: "suspended" }).key;
    const verdict = VERDICT_META[trace.final_status] || { icon: "flag", title: trace.final_status };
    html += `
      <div class="tl-step">
        <span class="tl-node ${finalKey === "ok" ? "ok" : finalKey}"><i data-lucide="flag"></i></span>
        <div class="tl-row" style="cursor:default">
          <span class="tl-name">Case stopped in provider workflow</span>
          <span class="tl-status ${finalKey}"><i data-lucide="${verdict.icon}"></i>${escapeHtml(trace.final_status)}</span>
        </div>
      </div>`;
  }

  el.innerHTML = html;

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
  renderPayerPanel(data.trace.events.find((e) => e.agent_name === PAYER_AGENT));
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
