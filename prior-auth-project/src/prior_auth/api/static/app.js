const AGENT_ORDER = ["Extractor", "ICD Coder", "Policy RAG", "Form Filler"];

const STATUS_META = {
  COMPLETED: { color: "emerald", title: "Completed", icon: "check" },
  SUSPENDED_LOW_CONFIDENCE: { color: "amber", title: "Suspended — low ICD coding confidence", icon: "pause" },
  SUSPENDED_PHI_VIOLATION: { color: "red", title: "Suspended — PHI boundary violation", icon: "shield" },
  SUSPENDED_POLICY_MISMATCH: { color: "amber", title: "Suspended — policy criteria not met", icon: "pause" },
  SUSPENDED_LATERALITY_CONFLICT: { color: "amber", title: "Suspended — laterality conflict", icon: "pause" },
  FAILED_VALIDATION: { color: "red", title: "Failed — validation error", icon: "x" },
  ERROR: { color: "red", title: "Error", icon: "x" },
  IN_PROGRESS: { color: "ink", title: "In progress", icon: "dot" },
};

const ICONS = {
  check: '<svg viewBox="0 0 20 20" fill="currentColor" class="h-5 w-5"><path fill-rule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0l-3.5-3.5a1 1 0 111.4-1.4l2.8 2.8 6.8-6.8a1 1 0 011.4 0z" clip-rule="evenodd"/></svg>',
  pause: '<svg viewBox="0 0 20 20" fill="currentColor" class="h-5 w-5"><path d="M6 4h2v12H6zM12 4h2v12h-2z"/></svg>',
  shield: '<svg viewBox="0 0 20 20" fill="currentColor" class="h-5 w-5"><path fill-rule="evenodd" d="M10 1l7 3v5c0 4.6-3 8.4-7 9.9-4-1.5-7-5.3-7-9.9V4l7-3zm-1 9.5l-2-2L5.6 9.9 9 13.3l5.4-5.4-1.4-1.4L9 10.5z" clip-rule="evenodd"/></svg>',
  x: '<svg viewBox="0 0 20 20" fill="currentColor" class="h-5 w-5"><path fill-rule="evenodd" d="M4.3 4.3a1 1 0 011.4 0L10 8.6l4.3-4.3a1 1 0 111.4 1.4L11.4 10l4.3 4.3a1 1 0 01-1.4 1.4L10 11.4l-4.3 4.3a1 1 0 01-1.4-1.4L8.6 10 4.3 5.7a1 1 0 010-1.4z" clip-rule="evenodd"/></svg>',
  dot: '<svg viewBox="0 0 20 20" fill="currentColor" class="h-5 w-5"><circle cx="10" cy="10" r="4"/></svg>',
};

const COLOR_CLASSES = {
  emerald: { bg: "bg-emerald-100", text: "text-emerald-700", border: "border-emerald-200", icon: "bg-emerald-500" },
  amber: { bg: "bg-amber-100", text: "text-amber-700", border: "border-amber-200", icon: "bg-amber-500" },
  red: { bg: "bg-red-100", text: "text-red-700", border: "border-red-200", icon: "bg-red-500" },
  ink: { bg: "bg-ink-100", text: "text-ink-700", border: "border-ink-200", icon: "bg-ink-400" },
};

let sampleCases = [];

async function loadSampleCases() {
  try {
    const res = await fetch("/api/sample-cases");
    sampleCases = await res.json();
    const select = document.getElementById("sampleSelect");
    for (const c of sampleCases) {
      const opt = document.createElement("option");
      opt.value = c.case_id;
      opt.textContent = `${c.case_id} — ${c.specialty}${c.requested_procedure ? " · " + c.requested_procedure : ""}`;
      select.appendChild(opt);
    }
  } catch (e) {
    console.error("Failed to load sample cases", e);
  }
}

function newCaseId() {
  return "UI-" + Math.random().toString(36).slice(2, 8).toUpperCase();
}

function setupInputs() {
  document.getElementById("caseIdInput").value = newCaseId();

  document.getElementById("sampleSelect").addEventListener("change", (e) => {
    const val = e.target.value;
    if (!val) return;
    const c = sampleCases.find((x) => x.case_id === val);
    if (!c) return;
    document.getElementById("noteInput").value = c.note_text;
    document.getElementById("specialtySelect").value = c.specialty in specialtyOptions() ? c.specialty : "unknown";
    document.getElementById("caseIdInput").value = c.case_id;
  });
}

function specialtyOptions() {
  const select = document.getElementById("specialtySelect");
  const set = {};
  for (const o of select.options) set[o.value] = true;
  return set;
}

function statusMeta(status) {
  return STATUS_META[status] || { color: "ink", title: status, icon: "dot" };
}

function renderStatusBanner(status, reason, totalMs) {
  const meta = statusMeta(status);
  const c = COLOR_CLASSES[meta.color];
  const banner = document.getElementById("statusBanner");
  banner.className = `rounded-xl border p-5 flex items-start gap-4 ${c.bg} ${c.border}`;
  const icon = document.getElementById("statusIcon");
  icon.className = `h-10 w-10 rounded-full flex items-center justify-center shrink-0 text-white ${c.icon}`;
  icon.innerHTML = ICONS[meta.icon];
  document.getElementById("statusTitle").textContent = meta.title;
  document.getElementById("statusTitle").className = `text-sm font-semibold ${c.text}`;
  document.getElementById("statusSubtitle").textContent = reason || "No suspension or validation issues.";
  document.getElementById("statusDuration").textContent = `${totalMs.toFixed(1)} ms`;
}

function stepStatusFromEvent(ev) {
  if (!ev) return "pending";
  if (ev.status === "OK") return "ok";
  if (ev.status === "SUSPENDED") return "suspended";
  return "failed";
}

function renderStepper(events) {
  const stepper = document.getElementById("stepper");
  const details = document.getElementById("stepDetails");
  stepper.innerHTML = "";
  details.innerHTML = "";

  const byAgent = {};
  for (const ev of events) byAgent[ev.agent_name] = ev;

  AGENT_ORDER.forEach((agentName, idx) => {
    const ev = byAgent[agentName];
    const status = stepStatusFromEvent(ev);
    const node = document.createElement("div");
    node.className = "step-node";
    node.dataset.status = status;
    const confidencePct = ev && ev.confidence != null ? Math.round(ev.confidence * 100) : null;
    node.innerHTML = `
      <div class="flex items-center gap-2 mb-2">
        <span class="step-dot">${idx + 1}</span>
        <span class="text-xs font-semibold text-ink-800 truncate">${agentName}</span>
      </div>
      <p class="text-[11px] font-medium ${status === "pending" ? "text-ink-400" : "text-ink-600"} mb-2">${ev ? ev.status : "Not reached"}</p>
      ${confidencePct != null ? `
        <div class="confidence-bar-track mb-1"><div class="confidence-bar-fill" style="width:${confidencePct}%"></div></div>
        <p class="text-[10px] text-ink-500 font-mono">${confidencePct}% confidence</p>
      ` : `<div class="confidence-bar-track"></div><p class="text-[10px] text-ink-400 font-mono">&mdash;</p>`}
      ${ev ? `<p class="text-[10px] text-ink-400 font-mono mt-1">${ev.duration_ms.toFixed(1)} ms</p>` : ""}
    `;
    if (ev) {
      node.addEventListener("click", () => toggleStepDetail(node, ev, details));
    }
    stepper.appendChild(node);
  });
}

function toggleStepDetail(node, ev, container) {
  const isActive = node.classList.contains("active");
  document.querySelectorAll(".step-node").forEach((n) => n.classList.remove("active"));
  container.innerHTML = "";
  if (isActive) return;
  node.classList.add("active");

  const wrap = document.createElement("div");
  wrap.className = "rounded-lg border border-ink-200 bg-ink-50 p-4";
  wrap.innerHTML = `
    <p class="text-xs font-semibold text-ink-700 mb-2">${ev.agent_name} — step ${ev.step}</p>
    ${ev.errors && ev.errors.length ? `
      <div class="mb-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded-md p-2">
        ${ev.errors.map((e) => `<div>• ${escapeHtml(e)}</div>`).join("")}
      </div>` : ""}
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div>
        <p class="text-[10px] uppercase tracking-wide text-ink-400 font-semibold mb-1">Input summary</p>
        <pre class="text-[11px] font-mono bg-white border border-ink-200 rounded-md p-2 overflow-auto max-h-56">${escapeHtml(JSON.stringify(ev.input_summary, null, 2))}</pre>
      </div>
      <div>
        <p class="text-[10px] uppercase tracking-wide text-ink-400 font-semibold mb-1">Output summary</p>
        <pre class="text-[11px] font-mono bg-white border border-ink-200 rounded-md p-2 overflow-auto max-h-56">${escapeHtml(JSON.stringify(ev.output_summary, null, 2))}</pre>
      </div>
    </div>
  `;
  container.appendChild(wrap);
}

function escapeHtml(str) {
  return str.replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

function renderPhiBoundary(caseObj) {
  const idList = document.getElementById("identifiersList");
  const maskedList = document.getElementById("maskedSummary");
  idList.innerHTML = "";
  maskedList.innerHTML = "";

  const ids = caseObj.identifiers || {};
  const idFields = ["name", "mrn", "dob", "address", "phone"];
  let anyDetected = false;
  for (const f of idFields) {
    const val = ids[f];
    if (val) anyDetected = true;
    idList.innerHTML += `<div><span class="text-amber-600">${f}:</span> ${val ? escapeHtml(val) : "<span class='text-amber-400'>not detected</span>"}</div>`;
  }
  if (!anyDetected) {
    idList.innerHTML = `<div class="text-amber-600">No identifiers detected in this note.</div>`;
  }

  const facts = caseObj.clinical_facts;
  if (facts) {
    maskedList.innerHTML = `
      <div><span class="text-emerald-600">phi_detected:</span> ${facts.phi_detected}</div>
      <div><span class="text-emerald-600">phi_fields_masked:</span> ${facts.phi_fields_masked && facts.phi_fields_masked.length ? escapeHtml(facts.phi_fields_masked.join(", ")) : "none"}</div>
      <div><span class="text-emerald-600">diagnosis:</span> ${escapeHtml((facts.diagnosis || "").slice(0, 80))}${(facts.diagnosis || "").length > 80 ? "…" : ""}</div>
      <div><span class="text-emerald-600">requested_procedure:</span> ${escapeHtml(facts.requested_procedure || "")}</div>
    `;
  } else {
    maskedList.innerHTML = `<div class="text-emerald-600">No clinical facts extracted (pipeline stopped before completion).</div>`;
  }
}

function renderForm(caseObj) {
  const card = document.getElementById("formCard");
  const form = caseObj.form;
  if (!form) {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");
  document.getElementById("formMeta").innerHTML = `
    <div><p class="text-[10px] uppercase tracking-wide text-ink-400 font-semibold">Template</p><p class="font-mono mt-0.5">${escapeHtml(form.form_template_id)}</p></div>
    <div><p class="text-[10px] uppercase tracking-wide text-ink-400 font-semibold">ICD-10</p><p class="font-mono mt-0.5">${escapeHtml(form.icd10_code)}</p></div>
    <div><p class="text-[10px] uppercase tracking-wide text-ink-400 font-semibold">Policy</p><p class="font-mono mt-0.5">${escapeHtml(form.policy_id)}</p></div>
  `;
  const tbody = document.getElementById("formFields");
  tbody.innerHTML = form.fields.map((f) => `
    <tr class="border-b border-ink-100">
      <td class="py-1.5 pr-3 font-medium text-ink-600">${escapeHtml(f.name)}</td>
      <td class="py-1.5 pr-3 font-mono text-ink-800">${escapeHtml(f.value)}</td>
      <td class="py-1.5">${f.required ? '<span class="text-[10px] rounded-full bg-ink-100 px-2 py-0.5">required</span>' : ""}</td>
    </tr>
  `).join("");
  if (form.validation_errors && form.validation_errors.length) {
    tbody.innerHTML += `<tr><td colspan="3" class="pt-3"><div class="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md p-2">${form.validation_errors.map((e) => `• ${escapeHtml(e)}`).join("<br/>")}</div></td></tr>`;
  }
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
  const spinner = document.getElementById("runSpinner");
  btn.disabled = true;
  label.textContent = "Running…";
  spinner.classList.remove("hidden");

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
    spinner.classList.add("hidden");
  }
}

function renderResults(data) {
  document.getElementById("emptyState").classList.add("hidden");
  const results = document.getElementById("results");
  results.classList.remove("hidden");
  results.classList.remove("reveal");
  void results.offsetWidth;
  results.classList.add("reveal");

  const caseObj = data.case;
  renderStatusBanner(caseObj.status, caseObj.suspension_reason, data.total_duration_ms);
  renderStepper(data.trace.events);
  renderPhiBoundary(caseObj);
  renderForm(caseObj);
  document.getElementById("rawTrace").textContent = JSON.stringify(data.trace, null, 2);
}

document.getElementById("runBtn").addEventListener("click", runWorkflow);
loadSampleCases().then(setupInputs);
