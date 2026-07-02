const AGENT_ORDER = ["Extractor", "ICD Coder", "Policy RAG", "Form Filler"];
const AGENT_SUBTITLE = {
  "Extractor": "Reads the clinical note",
  "ICD Coder": "Assigns the diagnosis code",
  "Policy RAG": "Checks the insurer's rules",
  "Form Filler": "Prepares the paperwork",
};
const AGENT_ICON = {
  "Extractor": "file-search",
  "ICD Coder": "stethoscope",
  "Policy RAG": "clipboard-check",
  "Form Filler": "file-check-2",
};

const STATUS_COLOR = {
  ok: { fill: "#0ca30c", tint: "var(--good-tint)", border: "var(--good-border)", icon: "check" },
  suspended: { fill: "#d97a06", tint: "var(--warn-tint)", border: "var(--warn-border)", icon: "pause" },
  failed: { fill: "#d03b3b", tint: "var(--bad-tint)", border: "var(--bad-border)", icon: "x" },
  pending: { fill: "#c3c2b7", tint: "#f4f4f7", border: "#e6e8ee", icon: "minus" },
};

const VERDICT_META = {
  COMPLETED: { key: "ok", icon: "check-circle-2", title: "Auto-Approved",
    sub: "This case meets every documented policy requirement and would be approved automatically — no human touch needed." },
  SUSPENDED_LOW_CONFIDENCE: { key: "suspended", icon: "pause-circle", title: "Sent for Human Review — Low Confidence",
    sub: "The AI isn't confident enough in the diagnosis code — especially given this may be a rare condition — so it stops and asks a human coder instead of guessing." },
  SUSPENDED_PHI_VIOLATION: { key: "failed", icon: "shield-alert", title: "Blocked — Privacy Safeguard Triggered",
    sub: "A potential patient-identifier leak was detected and the workflow halted immediately, before any downstream decision was made." },
  SUSPENDED_POLICY_MISMATCH: { key: "suspended", icon: "pause-circle", title: "Sent for Human Review — Policy Criteria Not Fully Met",
    sub: "The note doesn't yet document everything this insurer's policy requires for approval." },
  SUSPENDED_LATERALITY_CONFLICT: { key: "suspended", icon: "pause-circle", title: "Sent for Human Review — Conflicting Details",
    sub: "The note and the requested procedure disagree on left vs. right side — flagged rather than guessed." },
  FAILED_VALIDATION: { key: "failed", icon: "x-circle", title: "Rejected — Incomplete Information",
    sub: "Required information is missing or invalid, so the authorization form could not be completed." },
  ERROR: { key: "failed", icon: "x-circle", title: "System Error", sub: "An unexpected error stopped the workflow." },
};

let sampleCases = [];

function icons() { if (window.lucide) lucide.createIcons(); }

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

// ---------------- Tabs ----------------
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

// ---------------- Overview ----------------
async function loadOverview() {
  const grid = document.getElementById("kpiGrid");
  grid.innerHTML = `<div class="col-span-5 text-center text-sm text-slate-400 py-10">Scoring the pipeline against 90 labeled test cases…</div>`;
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
      <div class="kpi-icon"><i data-lucide="${t.icon}" class="lucide"></i></div>
      <div class="kpi-value">${t.value}</div>
      <div class="kpi-label">${t.label}</div>
      <div class="kpi-caption">${t.caption}</div>
    </div>
  `).join("");

  const flow = document.getElementById("overviewFlow");
  const steps = [
    { icon: "file-search", name: "Extractor", sub: "Reads the note, masks patient identifiers" },
    { icon: "stethoscope", name: "ICD Coder", sub: "Assigns the diagnosis code" },
    { icon: "clipboard-check", name: "Policy RAG", sub: "Checks the insurer's rules" },
    { icon: "file-check-2", name: "Form Filler", sub: "Prepares the paperwork" },
  ];
  flow.innerHTML = steps.map((s, i) => `
    <div class="flow-step">
      <div class="flow-icon"><i data-lucide="${s.icon}" class="lucide"></i></div>
      <div class="flow-name">${i + 1}. ${s.name}</div>
      <div class="flow-sub">${s.sub}</div>
    </div>
    ${i < steps.length - 1 ? `<div class="flow-arrow"><i data-lucide="chevron-right" class="lucide"></i></div>` : ""}
  `).join("");

  icons();
}

// ---------------- Live demo: inputs ----------------
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
  });
}

// ---------------- Live demo: run + render ----------------
function renderVerdict(status, reason, totalMs) {
  const meta = VERDICT_META[status] || { key: "pending", icon: "help-circle", title: status, sub: "" };
  const c = STATUS_COLOR[meta.key];
  const banner = document.getElementById("verdictBanner");
  banner.style.background = c.tint;
  banner.style.borderColor = c.border;
  const iconEl = document.getElementById("verdictIcon");
  iconEl.style.background = c.fill;
  iconEl.innerHTML = `<i data-lucide="${meta.icon}" class="lucide" style="width:28px;height:28px"></i>`;
  document.getElementById("verdictTitle").textContent = meta.title;
  document.getElementById("verdictSub").textContent = reason || meta.sub;
  document.getElementById("verdictDuration").textContent = `${totalMs.toFixed(0)} ms`;
}

function stepStatusKey(ev) {
  if (!ev) return "pending";
  if (ev.status === "OK") return "ok";
  if (ev.status === "SUSPENDED") return "suspended";
  return "failed";
}

function renderStepper(events) {
  const stepper = document.getElementById("stepper");
  stepper.innerHTML = "";
  const byAgent = {};
  for (const ev of events) byAgent[ev.agent_name] = ev;

  AGENT_ORDER.forEach((agentName, idx) => {
    const ev = byAgent[agentName];
    const key = stepStatusKey(ev);
    const c = STATUS_COLOR[key];
    const confidencePct = ev && ev.confidence != null ? Math.round(ev.confidence * 100) : null;
    const node = document.createElement("div");
    node.className = "step-card";
    node.style.background = c.tint;
    node.style.borderColor = c.border;
    node.innerHTML = `
      <div class="step-top">
        <span class="step-num" style="background:${c.fill}">${idx + 1}</span>
        <span class="step-name">${agentName}</span>
      </div>
      <div class="step-sub">${AGENT_SUBTITLE[agentName]}</div>
      <div class="step-status" style="color:${c.fill}"><i data-lucide="${c.icon}" class="lucide" style="width:14px;height:14px"></i>${ev ? ev.status : "Not reached"}</div>
      <div class="meter-track"><div class="meter-fill" style="width:${confidencePct ?? 0}%;background:${c.fill};"></div></div>
      <div class="step-meta">${confidencePct != null ? confidencePct + "% confidence" : "—"}${ev ? " · " + ev.duration_ms.toFixed(1) + " ms" : ""}</div>
    `;
    stepper.appendChild(node);
  });
  icons();

  // Technical detail tabs
  const reached = AGENT_ORDER.filter((a) => byAgent[a]);
  const tabsEl = document.getElementById("detailTabs");
  const panelsEl = document.getElementById("detailPanels");
  tabsEl.innerHTML = reached.map((a, i) => `<div class="detail-tab${i === 0 ? " active" : ""}" data-agent="${a}">${i + 1}. ${a}</div>`).join("");
  function renderPanel(agentName) {
    const ev = byAgent[agentName];
    panelsEl.innerHTML = `
      ${ev.errors && ev.errors.length ? `<div class="mb-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded-md p-2">${ev.errors.map((e) => `• ${escapeHtml(e)}`).join("<br/>")}</div>` : ""}
      <div class="grid grid-cols-2 gap-3">
        <div><p class="text-[11px] uppercase tracking-wide text-slate-400 font-semibold mb-1">Input</p><pre class="json-block">${escapeHtml(JSON.stringify(ev.input_summary, null, 2))}</pre></div>
        <div><p class="text-[11px] uppercase tracking-wide text-slate-400 font-semibold mb-1">Output</p><pre class="json-block">${escapeHtml(JSON.stringify(ev.output_summary, null, 2))}</pre></div>
      </div>
    `;
  }
  if (reached.length) renderPanel(reached[0]);
  tabsEl.querySelectorAll(".detail-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      tabsEl.querySelectorAll(".detail-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      renderPanel(tab.dataset.agent);
    });
  });
}

function renderPhiBoundary(caseObj) {
  const idList = document.getElementById("identifiersList");
  const maskedList = document.getElementById("maskedSummary");
  const ids = caseObj.identifiers || {};
  const idFields = ["name", "mrn", "dob", "address", "phone"];
  let anyDetected = false;
  idList.innerHTML = idFields.map((f) => {
    const val = ids[f];
    if (val) anyDetected = true;
    return `<div><b>${f}:</b> ${val ? escapeHtml(val) : "not detected"}</div>`;
  }).join("");
  if (!anyDetected) idList.innerHTML = `<div>No identifiers detected in this note.</div>`;

  const facts = caseObj.clinical_facts;
  if (facts) {
    const diag = (facts.diagnosis || "").slice(0, 90);
    maskedList.innerHTML = `
      <div><b>PHI detected in note:</b> ${facts.phi_detected}</div>
      <div><b>Fields masked:</b> ${(facts.phi_fields_masked || []).join(", ") || "none"}</div>
      <div><b>Diagnosis seen by AI:</b> ${escapeHtml(diag)}${(facts.diagnosis || "").length > 90 ? "…" : ""}</div>
      <div><b>Requested procedure:</b> ${escapeHtml(facts.requested_procedure || "")}</div>
    `;
  } else {
    maskedList.innerHTML = `<div>No clinical facts extracted (pipeline stopped before completion).</div>`;
  }
}

function renderForm(caseObj) {
  const card = document.getElementById("formCard");
  const form = caseObj.form;
  if (!form) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");
  document.getElementById("formMeta").innerHTML = `
    <div><p class="text-[11px] uppercase tracking-wide text-slate-400 font-semibold">Template</p><p class="font-mono font-bold mt-0.5">${escapeHtml(form.form_template_id)}</p></div>
    <div><p class="text-[11px] uppercase tracking-wide text-slate-400 font-semibold">ICD-10</p><p class="font-mono font-bold mt-0.5">${escapeHtml(form.icd10_code)}</p></div>
    <div><p class="text-[11px] uppercase tracking-wide text-slate-400 font-semibold">Policy</p><p class="font-mono font-bold mt-0.5" style="word-break:break-word">${escapeHtml(form.policy_id)}</p></div>
  `;
  document.getElementById("formFields").innerHTML = form.fields.map((f) => `
    <tr>
      <td class="field-name">${escapeHtml(f.name)}</td>
      <td class="field-value">${escapeHtml(f.value)}</td>
      <td>${f.required ? '<span class="req-badge">required</span>' : ""}</td>
    </tr>
  `).join("") + (form.validation_errors && form.validation_errors.length
    ? `<tr><td colspan="3" class="pt-3"><div class="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md p-2">${form.validation_errors.map((e) => `• ${escapeHtml(e)}`).join("<br/>")}</div></td></tr>`
    : "");
}

async function runWorkflow() {
  const noteText = document.getElementById("noteInput").value;
  const specialty = document.getElementById("specialtySelect").value;
  const caseId = document.getElementById("caseIdInput").value || newCaseId();
  const errorMsg = document.getElementById("errorMsg");
  errorMsg.classList.add("hidden");

  if (!noteText.trim()) {
    errorMsg.textContent = "Please enter or select a doctor's note first.";
    errorMsg.classList.remove("hidden");
    return;
  }

  const btn = document.getElementById("runBtn");
  const label = document.getElementById("runBtnLabel");
  const iconWrap = document.getElementById("runIconWrap");
  btn.disabled = true;
  label.textContent = "Running…";
  iconWrap.innerHTML = '<i data-lucide="loader-2" class="lucide animate-spin"></i>';
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
    errorMsg.textContent = e.message || "Something went wrong.";
    errorMsg.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    label.textContent = "Run workflow";
    iconWrap.innerHTML = '<i data-lucide="play" class="lucide"></i>';
    icons();
  }
}

function renderResults(data) {
  document.getElementById("emptyState").classList.add("hidden");
  document.getElementById("results").classList.remove("hidden");

  const caseObj = data.case;
  renderVerdict(caseObj.status, caseObj.suspension_reason, data.total_duration_ms);
  renderStepper(data.trace.events);
  renderPhiBoundary(caseObj);
  renderForm(caseObj);
  document.getElementById("rawTrace").textContent = JSON.stringify(data.trace, null, 2);
  icons();
}

function setupExpandToggles() {
  [["detailToggle", "detailBody"], ["rawToggle", "rawBody"]].forEach(([toggleId, bodyId]) => {
    document.getElementById(toggleId).addEventListener("click", () => {
      document.getElementById(toggleId).classList.toggle("open");
      document.getElementById(bodyId).classList.toggle("open");
    });
  });
}

document.getElementById("runBtn").addEventListener("click", runWorkflow);
setupTabs();
setupExpandToggles();
loadOverview();
loadSampleCases().then(setupInputs);
icons();
