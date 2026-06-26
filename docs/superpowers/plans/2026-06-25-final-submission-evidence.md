# Final Submission Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the Smart Collect Assistant submission so reports, demo commands, and final presentation evidence match the actual implementation and measurable results.

**Architecture:** Keep the current FastAPI, LangGraph, pandas/openpyxl, React architecture. Improve only the presentation/demo surface and the final markdown reports, using measured benchmark outputs instead of unverified claims.

**Tech Stack:** Python 3.11, FastAPI, LangGraph, pandas, openpyxl, pytest, Vite, React, TypeScript.

## Global Constraints

- Do not claim Gmail MCP, real mail sending, production Langfuse, or live enterprise integration as implemented unless the local code actually performs it.
- Use measured numbers from `backend.smart_collect.benchmark` and `pytest`.
- Preserve original Excel files and generate result files separately.
- Keep the final story focused on why deterministic Excel validation, LangGraph state flow, ToT rule selection, and Self-Correction were needed.

---

### Task 1: Demo Output Hardening

**Files:**
- Modify: `backend/cli.py`
- Modify: `backend/smart_collect/benchmark.py`

**Interfaces:**
- Consumes: existing `cmd_demo`, `_print_table`, and benchmark metrics.
- Produces: PowerShell-safe CLI output without UnicodeEncodeError under CP949 consoles.

- [x] Replace block drawing characters and emoji-only symbols with ASCII text.
- [x] Replace em dash in benchmark heading with ASCII hyphen.
- [x] Run `python backend/cli.py demo` in the default shell.

### Task 2: Testing And Optimization Report

**Files:**
- Modify: `AI_talent_lab/테스트 및 고도화.md`

**Interfaces:**
- Consumes: benchmark metrics from `data/benchmark_metrics.json`.
- Produces: a report section that matches the supplied template and explains test results, discovered issues, and improvements using quantitative evidence.

- [x] Fill the issue table with actual issues: LLM hallucination risk, schema drift false positives, safe auto-correction boundary, Windows console encoding.
- [x] Fill LLM/data quality, performance, guardrail, and additional cases with measured numbers.
- [x] Avoid unimplemented Redis, live RAG, or external API claims.

### Task 3: E2E Service Report

**Files:**
- Modify: `AI_talent_lab/E2E 서비스 개발.md`

**Interfaces:**
- Consumes: implemented API endpoints, frontend flow, tests, and benchmark metrics.
- Produces: a final service report with architecture, KPI Plan vs Actual, value, security, limitations, and next steps.

- [x] Describe the actual E2E flow: React UI -> FastAPI -> LangGraph -> Excel tools -> result download.
- [x] Map KPIs to measured values.
- [x] State operational constraints honestly: mock email, local file storage, approved-send principle.

### Task 4: Verification

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: updated code and reports.
- Produces: verification results for final response and future presentation evidence.

- [x] Run `pytest tests -q`.
- [x] Run `npm run build` in `frontend`.
- [x] Run `python -m backend.smart_collect.benchmark`.
- [x] Run `python backend/cli.py demo`.
