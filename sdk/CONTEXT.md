# CONTEXT — crew-fusebox

> **Start here.** This is the entry-point index for every work session on this project.
> If you are a new contributor (human or AI), read this file first, then follow the links below.

## What is this project?

**crew-fusebox** is a lightweight, near-zero-dependency, open-source Python SDK that acts as an
**economic circuit-breaker** ("fuse box") for multi-agent systems. For the v1 release it focuses
**exclusively on CrewAI**. It sits *inside* the local application runtime, tracks token consumption
and dollar spend in real time, and — depending on configuration — either passively warns you
(default) or forcefully terminates a runaway agent workflow before it produces an invoice-shock
LLM bill. Its one-line hook: *"Stop your AI agents from bankrupting you."*

## Current status

- **Phase: Pre-code, docs-only.** No source code, package folders, or config files exist yet.
- **Source of truth:** [`claude.md`](./claude.md) — the original project blueprint. It is
  authoritative; the documents below derive from and expand on it. Do not modify `claude.md`
  without an explicit instruction to do so.

## Document map

| Document | What it covers |
| --- | --- |
| [`claude.md`](./claude.md) | The original, authoritative project blueprint (source of truth). |
| [`PRD.md`](./PRD.md) | Product requirements: problem, audience, goals, success criteria, scope. |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Technical design, hook-injection strategy, cost model, and a flow diagram. |
| [`ROADMAP.md`](./ROADMAP.md) | Phase 1 (Core Engine) and Phase 2 (Refinement) build checklists. |
| [`GLOSSARY.md`](./GLOSSARY.md) | Definitions of all domain-specific terms used across the docs. |
| [`CONVENTIONS.md`](./CONVENTIONS.md) | Code style and quality rules that future code must follow. |

## The 30-second summary

- **Problem:** Autonomous agents get stuck in loops (tool-retry loops, delegation ping-pong) and
  silently burn `$100–$2,400+` in tokens before anyone notices.
- **Solution:** A native Python SDK — **no network proxy** — that wraps a CrewAI `kickoff()` via a
  simple decorator and enforces a dollar budget.
- **Differentiator:** CrewAI already has per-agent `max_iter`/`max_rpm` (count/rate limits).
  crew-fusebox instead stops loops **by real-time dollar cost, aggregated across the whole crew**,
  and blocks the next LLM call at the budget ceiling.
- **Enforcement point:** CrewAI's **`before_llm_call`** hook (blocks a call *before* dispatch by
  returning `False`) — **not** `step_callback`/`task_callback`, which only report after the fact.
  Cost is priced from **LiteLLM's maintained pricing data**, not a hand-rolled table. Target
  `crewai>=1.14,<2`.
- **Safety-first defaults:** Ships in passive **dry-run / audit mode** (`hard_kill=False`). Only
  when explicitly enabled does it block the next call and raise a `CircuitBreakerException`.
- **Non-negotiable constraints:** Sub-millisecond pre-call evaluation, minimal dependencies, and it
  must **never crash a healthy host application**.
- **Packaging:** PyPI as `crew-fusebox`, **MIT** license (open-core). Validate against **3 real
  users' CrewAI pipelines before Phase 2**.

## How to use these docs across sessions

1. Read this `CONTEXT.md` for the mental map.
2. Read [`PRD.md`](./PRD.md) for *what* and *why*.
3. Read [`ARCHITECTURE.md`](./ARCHITECTURE.md) for *how*.
4. Consult [`ROADMAP.md`](./ROADMAP.md) for *what to build next*.
5. Keep [`GLOSSARY.md`](./GLOSSARY.md) and [`CONVENTIONS.md`](./CONVENTIONS.md) open while working.
