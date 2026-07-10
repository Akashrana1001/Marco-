"""Runnable dogfood example for agent-breaker against a real CrewAI pipeline.

This is the harness for the ROADMAP's validation gate: run it against real CrewAI loops
(ideally 3 real users' pipelines) before starting Phase 2.

Usage
-----
    pip install agent-breaker crewai
    export OPENAI_API_KEY=sk-...        # or another provider LiteLLM supports

    # Dry-run (default): tracks + warns, never interrupts.
    python examples/quickstart.py

    # Hard-kill: blocks the next LLM call once the budget is breached.
    python examples/quickstart.py --hard-kill --budget 0.01

The example deliberately gives the agent an open-ended, expensive task and a low budget so the
breaker has something to catch.
"""

from __future__ import annotations

import argparse
import os
import sys

from agent_breaker import CircuitBreakerException, crew_circuit_breaker


def build_crew(model: str):
    # Imported lazily so `--help` works without crewai installed.
    from crewai import Agent, Crew, Task

    writer = Agent(
        role="Prolific Author",
        goal="Write an ever-expanding epic",
        backstory="You never stop elaborating and always add more detail.",
        llm=model,
        max_iter=50,
        verbose=True,
    )
    task = Task(
        description=(
            "Write a detailed multi-chapter story about a robot exploring the ocean. "
            "Keep expanding every chapter with more description."
        ),
        expected_output="A very long story.",
        agent=writer,
    )
    return Crew(agents=[writer], tasks=[task])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="agent-breaker CrewAI dogfood example")
    parser.add_argument("--budget", type=float, default=0.02, help="dollar budget for the run")
    parser.add_argument("--hard-kill", action="store_true", help="block + raise on breach")
    parser.add_argument("--model", default=os.environ.get("MODEL", "gpt-4o-mini"))
    args = parser.parse_args(argv)

    @crew_circuit_breaker(max_budget_dollars=args.budget, hard_kill=args.hard_kill)
    def run_pipeline():
        return build_crew(args.model).kickoff()

    mode = "hard-kill" if args.hard_kill else "dry-run"
    print(f"[example] running crew in {mode} mode with ${args.budget:.4f} budget\n")

    try:
        result = run_pipeline()
    except CircuitBreakerException as exc:
        print(f"\n[example] breaker tripped: {exc}")
        return 0
    else:
        print(f"\n[example] crew finished without tripping. Result:\n{result}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
