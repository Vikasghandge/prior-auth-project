"""Local demo API for the prior-auth multi-agent workflow.

Wraps `PriorAuthWorkflow` behind two endpoints so the frontend dashboard can submit a
doctor's note and watch it move through Extractor -> ICD Coder -> Policy RAG -> Form Filler
in real time. Runs triggered from here are not persisted to logs/audit_traces (persist_trace
=False) so demo traffic doesn't mix with real pipeline runs.
"""
from __future__ import annotations

import glob
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from prior_auth.orchestration.graph import PriorAuthWorkflow

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"

app = FastAPI(title="Prior Auth Workflow Demo API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_workflow = PriorAuthWorkflow()


class RunRequest(BaseModel):
    case_id: str
    note_text: str
    specialty: str = "unknown"


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/sample-cases")
def sample_cases() -> list[dict]:
    cases: list[dict] = []
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


_eval_metrics_cache: dict | None = None


def _score_case(c: dict) -> dict:
    """Runs one sample case through the real pipeline and diffs the result against its gold
    label. `icd_ok`/`policy_ok` require an exact code/policy match — reaching COMPLETED alone
    isn't "correct", since that status is also reachable with a wrong code underneath."""
    t0 = time.perf_counter()
    case, _trace = _workflow.run(
        c["case_id"], c["note_text"], specialty=c.get("specialty", "unknown"), persist_trace=False
    )
    gold = c.get("gold", {})
    # "Checked" requires the pipeline to have actually reached that stage, not just that gold
    # data exists — a case correctly suspended at the ICD step never attempted a policy match,
    # so it shouldn't count as a policy-match failure.
    return {
        "status": case.status.value,
        "duration_ms": (time.perf_counter() - t0) * 1000,
        "icd_checked": case.icd_result is not None and gold.get("icd10_code") is not None,
        "icd_ok": bool(case.icd_result) and case.icd_result.icd10_code == gold.get("icd10_code"),
        "policy_checked": case.policy_result is not None and gold.get("policy_id") is not None,
        "policy_ok": bool(case.policy_result) and case.policy_result.policy_id == gold.get("policy_id"),
        "is_approve_variant": gold.get("variant") == "approve",
    }


def _pct(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 1) if denominator else None


@app.get("/api/eval-metrics")
def eval_metrics() -> dict:
    """Scores every sample case against its gold label. Computed on first request, then cached
    in memory for the life of the process."""
    global _eval_metrics_cache
    if _eval_metrics_cache is not None:
        return _eval_metrics_cache

    scored = [_score_case(c) for c in sample_cases_raw()]
    icd_checked = [s for s in scored if s["icd_checked"]]
    policy_checked = [s for s in scored if s["policy_checked"]]
    approve_cases = [s for s in scored if s["is_approve_variant"]]

    _eval_metrics_cache = {
        "total": len(scored),
        "completed": sum(1 for s in scored if s["status"] == "COMPLETED"),
        "suspended": sum(1 for s in scored if s["status"].startswith("SUSPENDED")),
        "errored": sum(1 for s in scored if not s["status"].startswith(("COMPLETED", "SUSPENDED"))),
        "icd_accuracy": _pct(sum(s["icd_ok"] for s in icd_checked), len(icd_checked)),
        "policy_accuracy": _pct(sum(s["policy_ok"] for s in policy_checked), len(policy_checked)),
        "approve_accuracy": _pct(
            sum(s["status"] == "COMPLETED" and s["icd_ok"] for s in approve_cases), len(approve_cases)
        ),
        "avg_latency_ms": round(sum(s["duration_ms"] for s in scored) / len(scored), 1) if scored else None,
    }
    return _eval_metrics_cache


def sample_cases_raw() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(glob.glob(str(_DATA_DIR / "doctor_notes" / "*" / "cases.json"))):
        with open(path, "r", encoding="utf-8") as f:
            cases.extend(json.load(f))
    return cases


@app.post("/api/run")
def run_case(req: RunRequest) -> dict:
    if not req.note_text.strip():
        raise HTTPException(status_code=400, detail="note_text must not be empty")

    t0 = time.perf_counter()
    case, trace = _workflow.run(
        req.case_id, req.note_text, specialty=req.specialty, persist_trace=False
    )
    total_ms = round((time.perf_counter() - t0) * 1000, 2)

    return {
        "case": case.model_dump(mode="json"),
        "trace": trace.model_dump(mode="json"),
        "total_duration_ms": total_ms,
    }


app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")
