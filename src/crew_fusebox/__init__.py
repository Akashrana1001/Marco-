"""crew-fusebox: an economic circuit-breaker for CrewAI multi-agent systems.

Stop your AI agents from bankrupting you. Wrap a CrewAI ``kickoff()`` with a single
decorator to track real-time dollar spend across the whole crew, warn in dry-run mode,
and deterministically block the next LLM call (hard-kill mode) once a budget is breached.
"""

from crew_fusebox.breaker import crew_circuit_breaker
from crew_fusebox.exceptions import CircuitBreakerException

__version__ = "0.1.0"

__all__ = ["CircuitBreakerException", "__version__", "crew_circuit_breaker"]
