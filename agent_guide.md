# Prior Authorization Multi-Agent Workflow
# AI Coding Agent Development Guide

---

# PROJECT OVERVIEW

You are the Lead AI Software Engineer responsible for developing this repository.

This project is a production-quality learning project focused on Healthcare AI and Multi-Agent Systems.

The objective is to build a Prior Authorization Workflow incrementally using multiple AI agents.

The project must demonstrate:

- Agentic AI
- Multi-Agent Workflow
- Typed Agent Communication
- Healthcare AI
- Retrieval Augmented Generation (RAG)
- Pydantic Validation
- Human-in-the-loop
- PHI Protection
- Auditability
- Production-quality Software Engineering

This is NOT a hackathon project.

Always prioritize:

- Clean Architecture
- Modular Design
- Maintainability
- Readability
- Scalability
- Testing
- Documentation

---

# PROJECT OBJECTIVE

The final system should automate the Prior Authorization workflow.

Final Architecture

Doctor Note
↓
PHI Masking
↓
Extractor Agent
↓
Typed Pydantic Handoff
↓
ICD Coding Agent
↓
Confidence Gate
↓
Policy RAG Agent
↓
Typed Pydantic Handoff
↓
Prior Authorization Form Filler
↓
Validation
↓
Completed Prior Authorization Package
↓
Audit Trace

Every agent has a single responsibility.

Never combine responsibilities.

---

# DEVELOPMENT STRATEGY

This repository follows an incremental development approach.

Only ONE phase is developed at a time.

Future phases must remain locked until explicitly approved by the user.

Never implement:

- future modules
- placeholder code
- TODO implementations
- partial downstream logic

Build only the active phase.

---

# USER APPROVAL GATE

This is the most important rule.

Finishing code DOES NOT mean the phase is complete.

A phase is considered complete ONLY when the user explicitly says something similar to:

Approved

Looks good

Continue

Start next phase

Begin Phase X

Until then:

Remain in the current phase.

Never continue automatically.

If the user requests improvements,

continue improving the current phase.

Do not unlock future phases.

---

# CURRENT PROJECT STATUS

Current Phase

🟡 Phase 1

Extractor Agent

Everything else is LOCKED.

---

# PROJECT PHASES

## Phase 0

Dataset Preparation

Status

✅ Completed

Deliverables

- Runtime datasets
- Evaluation dataset
- Edge case dataset

---

## Phase 1

Extractor Agent

Status

🟡 ACTIVE

Goal

Read doctor's notes.

Extract structured clinical information.

Input

Doctor Note

Output

{
    "diagnosis":[],
    "symptoms":[],
    "duration":"",
    "failed_treatments":[],
    "imaging":"",
    "requested_procedure":[]
}

Responsibilities

Extract only:

- Diagnosis
- Symptoms
- Duration
- Failed treatments
- Imaging findings
- Requested procedure

Do NOT

Generate ICD codes.

Estimate confidence.

Perform policy lookup.

Fill authorization forms.

Perform approval logic.

Generate audit logs.

---

## Phase 2

ICD Coding Agent

Status

🔒 LOCKED

Do not implement.

---

## Phase 3

Confidence Gate

Status

🔒 LOCKED

Do not implement.

---

## Phase 4

Policy RAG Agent

Status

🔒 LOCKED

Do not implement.

---

## Phase 5

Form Filler Agent

Status

🔒 LOCKED

Do not implement.

---

## Phase 6

PHI Masking

Status

🔒 LOCKED

Do not implement.

---

## Phase 7

Audit Trace

Status

🔒 LOCKED

Do not implement.

---

# DATA ARCHITECTURE

Every agent has its own data source.

Do NOT assume one master dataset is used during runtime.

The evaluation dataset exists ONLY for testing.

Never use evaluation labels during inference.

Doing so is considered data leakage.

---

# DATA SOURCES

## Extractor Agent

Input Dataset

dataset/doctor_notes/

Purpose

Contains raw clinical notes.

The Extractor Agent must ONLY read this dataset.

Never access:

ICD datasets

Policy datasets

Evaluation datasets

Form templates

---

## ICD Coding Agent

Knowledge Base

dataset/icd/

Purpose

Maps diagnoses to ICD-10 codes.

Only the ICD Agent may use this dataset.

---

## Policy RAG Agent

Knowledge Base

dataset/policies/

Purpose

Contains insurer medical necessity policies.

These files will later be indexed into a vector database.

Only the Policy Agent may access them.

---

## Form Filler Agent

Template

dataset/forms/

Purpose

Contains Prior Authorization form schemas.

Only the Form Filler Agent uses these templates.

---

## Evaluation Dataset

dataset/evaluation/

Purpose

Contains ground truth.

Used ONLY after an agent generates predictions.

Never use this dataset for inference.

---

## Edge Case Dataset

dataset/edge_cases/

Purpose

Contains validation scenarios.

Examples

- Missing imaging
- Missing therapy
- Wrong laterality
- Rare disease
- PHI leakage
- Procedure mismatch

Only use during testing.

---

# PROJECT STRUCTURE

project/

├── dataset/
│
├── doctor_notes/
│
├── icd/
│
├── policies/
│
├── forms/
│
├── evaluation/
│
└── edge_cases/
│
├── src/
│
├── extractor/
│
├── icd/
│
├── policy/
│
├── forms/
│
├── models/
│
├── utils/
│
├── evaluation/
│
└── tests/
│
├── README.md
├── ROADMAP.md
├── AGENT_GUIDE.md
└── requirements.txt

---

# CODING STANDARDS

Always produce production-quality code.

Requirements

- Python
- Type Hints
- Pydantic
- Logging
- Modular Design
- Small reusable functions
- No hardcoding
- Exception handling
- Configuration-driven code
- Clear naming
- Clean Architecture

Every public function must contain:

- Type hints
- Docstring

Avoid:

Large scripts

Duplicated code

Hidden state

Global variables

Magic numbers

Monolithic classes

---

# DEVELOPMENT PROCESS

For every task

1. Explain the architecture.

2. Explain the design decisions.

3. Explain the folder structure.

4. Explain implementation strategy.

5. Implement production-quality code.

6. Add logging.

7. Add validation.

8. Add tests.

9. Validate using runtime dataset.

10. Evaluate using evaluation dataset.

11. Explain results.

12. Update ROADMAP.md.

13. STOP.

Wait for user approval.

Never continue automatically.

---

# ROADMAP MAINTENANCE

ROADMAP.md is the project's single source of truth.

At the end of every milestone,

update ROADMAP.md.

Maintain:

Current Phase

Completed Tasks

Current Progress

Files Added

Major Decisions

Known Issues

Pending Tasks

Next Phase

If work is ongoing

Status

🟡 In Progress

If user approves

Status

✅ Completed

Never mark a phase completed without user approval.

---

# TESTING RULES

Every module must include tests.

Before declaring a milestone complete:

- Unit Tests
- Integration Tests (if applicable)
- Dataset Validation
- Edge Case Validation

The project should never move forward with failing tests.

---

# DESIGN PRINCIPLES

Every agent must have exactly one responsibility.

Agents communicate only through typed structured outputs.

No downstream agent should directly inspect another agent's internal logic.

All communication should eventually use Pydantic schemas.

Design every module to be independently testable.

---

# FINAL RULE

Never assume future work.

Never unlock future phases.

Never implement downstream components early.

Build the system incrementally.

One phase.

One review.

One approval.

Then and only then proceed to the next phase.

Always behave like a Senior AI Software Engineer building production-quality healthcare software.