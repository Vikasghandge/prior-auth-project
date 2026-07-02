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
