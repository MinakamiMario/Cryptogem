"""Lab resilience — circuit breaker for agent error recovery.

Implements per-agent circuit breaking:
- CLOSED: normal operation (default)
- OPEN: agent paused after repeated failures (skip heartbeat)
- HALF_OPEN: test with one heartbeat, success → CLOSED, fail → OPEN

Also provides blocked task auto-retry with backoff.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger('lab.resilience')

# ── Circuit breaker configuration ────────────────────────
# After N consecutive errors, open the circuit (pause agent).
CIRCUIT_ERROR_THRESHOLD = 3
# Cooldown seconds before trying again (half-open test).
CIRCUIT_COOLDOWN_S = 300  # 5 minutes
# Max consecutive open periods before escalation.
CIRCUIT_MAX_OPEN_PERIODS = 3

# ── Blocked task retry configuration ─────────────────────
# Minimum age (seconds) before a blocked task can be retried.
RETRY_MIN_AGE_S = 600  # 10 minutes
# Maximum retries before giving up on a blocked task.
RETRY_MAX_ATTEMPTS = 3


class CircuitState(Enum):
    CLOSED = 'closed'       # Normal operation
    OPEN = 'open'           # Paused — too many errors
    HALF_OPEN = 'half_open' # Testing — one attempt allowed


@dataclass
class AgentCircuit:
    """Per-agent circuit breaker state."""
    agent_name: str
    state: CircuitState = CircuitState.CLOSED
    consecutive_errors: int = 0
    last_error_time: float = 0.0
    last_error_msg: str = ''
    open_count: int = 0       # How many times circuit has opened
    last_open_time: float = 0.0
    total_errors: int = 0

    def record_success(self) -> None:
        """Agent completed heartbeat successfully.

        Resets open_count on recovery from HALF_OPEN so that
        needs_escalation clears once the agent is healthy again.
        """
        if self.state == CircuitState.HALF_OPEN:
            logger.info(
                f"[circuit] {self.agent_name}: HALF_OPEN → CLOSED "
                f"(recovered after {self.open_count} opens, "
                f"{self.consecutive_errors} errors)"
            )
            self.open_count = 0  # Agent recovered — clear escalation
        self.consecutive_errors = 0
        self.state = CircuitState.CLOSED

    def record_error(self, error_msg: str) -> None:
        """Agent failed. May trip the circuit to OPEN."""
        self.consecutive_errors += 1
        self.total_errors += 1
        self.last_error_time = time.time()
        self.last_error_msg = error_msg[:200]

        if self.consecutive_errors >= CIRCUIT_ERROR_THRESHOLD:
            self.state = CircuitState.OPEN
            self.open_count += 1
            self.last_open_time = time.time()
            logger.warning(
                f"[circuit] {self.agent_name}: → OPEN "
                f"(errors={self.consecutive_errors}, "
                f"open_count={self.open_count})"
            )

    def should_skip(self) -> bool:
        """Check if agent should be skipped this cycle.

        Returns True if circuit is OPEN and cooldown hasn't elapsed.
        Transitions to HALF_OPEN when cooldown expires.
        """
        if self.state == CircuitState.CLOSED:
            return False

        if self.state == CircuitState.HALF_OPEN:
            return False  # Allow one test attempt

        # OPEN: check cooldown
        elapsed = time.time() - self.last_open_time
        if elapsed >= CIRCUIT_COOLDOWN_S:
            self.state = CircuitState.HALF_OPEN
            logger.info(
                f"[circuit] {self.agent_name}: OPEN → HALF_OPEN "
                f"(cooldown elapsed: {elapsed:.0f}s)"
            )
            return False  # Allow test attempt

        return True  # Still in cooldown

    @property
    def needs_escalation(self) -> bool:
        """True if agent has been open too many times — needs attention."""
        return self.open_count >= CIRCUIT_MAX_OPEN_PERIODS


class CircuitBreakerRegistry:
    """Manages circuit breakers for all agents."""

    def __init__(self):
        self._circuits: dict[str, AgentCircuit] = {}

    def get(self, agent_name: str) -> AgentCircuit:
        """Get or create circuit for agent."""
        if agent_name not in self._circuits:
            self._circuits[agent_name] = AgentCircuit(agent_name=agent_name)
        return self._circuits[agent_name]

    def all_circuits(self) -> list[AgentCircuit]:
        """Return all tracked circuits."""
        return list(self._circuits.values())

    def open_circuits(self) -> list[AgentCircuit]:
        """Return circuits that are currently open."""
        return [c for c in self._circuits.values()
                if c.state == CircuitState.OPEN]

    def escalation_needed(self) -> list[AgentCircuit]:
        """Return circuits needing escalation (too many opens)."""
        return [c for c in self._circuits.values()
                if c.needs_escalation]

    def summary(self) -> dict:
        """Return compact summary of all circuit states."""
        return {
            c.agent_name: {
                'state': c.state.value,
                'consecutive_errors': c.consecutive_errors,
                'total_errors': c.total_errors,
                'open_count': c.open_count,
            }
            for c in self._circuits.values()
        }
