"""Heartbeat loop — sequential agent execution with stagger."""
from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Optional

from lab.agents.base import BaseAgent
from lab.config import (
    CAP_BREACH_ESCALATE_CYCLES,
    DAILY_DIGEST_INTERVAL_S,
    HEARTBEAT_INTERVAL_S,
    HEARTBEAT_STAGGER_S,
)
from lab.db import LabDB
from lab.notifier import LabNotifier
from lab.resilience import (
    CircuitBreakerRegistry,
    CircuitState,
    RETRY_MAX_ATTEMPTS,
    RETRY_MIN_AGE_S,
)
from lab.shell_guard import install as install_shell_guard
from lab.shell_guard import set_violation_callback

logger = logging.getLogger('lab.heartbeat')


class HeartbeatLoop:
    """Runs agents sequentially on a timer."""

    def __init__(self, db: LabDB, notifier: LabNotifier,
                 agents: list[BaseAgent]):
        self.db = db
        self.notifier = notifier
        self.agents = agents
        self._running = True
        self._cycle = 0
        self._current_agent: str | None = None

        # Guardrail v1: drain mode tracking
        self._prev_drain_mode = False
        self._drain_cycles = 0
        # Daily digest: send on first cycle, then every 24h
        self._last_digest_time = 0.0

        # Resilience: per-agent circuit breakers
        self._circuits = CircuitBreakerRegistry()

        # Hard kill-switch: block gh, git, pytest, etc.
        # Fail-closed: if guard can't install → exit(1).
        try:
            install_shell_guard()
        except Exception as e:
            logger.critical(f"Shell guard install FAILED: {e}")
            sys.exit(1)

        # TG alert on every blocked shell attempt
        def _on_violation(binary: str) -> None:
            agent = self._current_agent or 'unknown'
            try:
                self.notifier.shell_violation(binary, agent)
            except Exception:
                pass  # never crash the guard path
        set_violation_callback(_on_violation)

        # Graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, frame) -> None:
        logger.info(
            f"Received signal {signum}, shutting down gracefully... "
            f"cycle={self._cycle}, current_agent={self._current_agent or 'none'}"
        )
        self._running = False

    def shutdown(self) -> None:
        """Explicit shutdown — log state and stop."""
        logger.info(f"Shutdown requested. Cycle={self._cycle}, "
                    f"current_agent={self._current_agent or 'none'}")
        self._running = False

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep with Telegram polling every 10s for responsive callbacks."""
        end = time.time() + seconds
        poll_interval = 10
        next_poll = time.time() + poll_interval
        while time.time() < end and self._running:
            time.sleep(1)
            if time.time() >= next_poll:
                try:
                    _, tg_messages = self.notifier.poll_telegram(self.db)
                    for msg in tg_messages:
                        logger.info(f"  [telegram] 💬 Bericht: {msg}")
                except Exception:
                    pass  # Non-critical
                next_poll = time.time() + poll_interval

    def run_once(self) -> dict:
        """Run one heartbeat cycle across all agents."""
        cycle_start = time.time()
        self._cycle += 1
        cycle_stats = {
            'cycle': self._cycle,
            'reviews': 0,
            'tasks': 0,
            'promotions': 0,
            'errors': 0,
            'agent_timings': {},
        }

        logger.info(f"=== Heartbeat cycle {self._cycle} ===")

        # Process any pending Telegram updates (approvals + messages)
        try:
            tg_actions, tg_messages = self.notifier.poll_telegram(self.db)
            if tg_actions:
                logger.info(f"  [telegram] {tg_actions} approval(s) processed")
            for msg in tg_messages:
                logger.info(f"  [telegram] 💬 Bericht: {msg}")
                print(f"\n💬 [Telegram] {msg}\n")
        except Exception as e:
            logger.warning(f"  [telegram] poll failed: {e}")

        skipped_agents = 0
        for i, agent in enumerate(self.agents):
            if not self._running:
                break

            # Stagger: 1 min between agents, poll TG every 10s
            if i > 0:
                self._interruptible_sleep(HEARTBEAT_STAGGER_S)

            # ── Circuit breaker: skip agents in cooldown ──────
            circuit = self._circuits.get(agent.name)
            if circuit.should_skip():
                logger.info(
                    f"  [{agent.name}] SKIPPED (circuit OPEN, "
                    f"errors={circuit.consecutive_errors}, "
                    f"open_count={circuit.open_count})"
                )
                skipped_agents += 1
                continue

            try:
                self._current_agent = agent.name
                is_half_open = circuit.state == CircuitState.HALF_OPEN
                mode = " [HALF_OPEN test]" if is_half_open else ""
                logger.info(
                    f"  [{agent.name}] starting heartbeat{mode}")
                agent_start = time.time()
                stats = agent.heartbeat()
                agent_elapsed = time.time() - agent_start
                cycle_stats['agent_timings'][agent.name] = round(
                    agent_elapsed, 2)
                cycle_stats['reviews'] += stats.get('reviews', 0)
                cycle_stats['tasks'] += stats.get('tasks', 0)
                cycle_stats['promotions'] += stats.get('promotions', 0)
                cycle_stats['errors'] += stats.get('errors', 0)
                self._current_agent = None

                # Circuit breaker: record success
                circuit.record_success()

                logger.info(
                    f"  [{agent.name}] done ({agent_elapsed:.1f}s): "
                    f"reviews={stats.get('reviews', 0)} "
                    f"tasks={stats.get('tasks', 0)} "
                    f"errors={stats.get('errors', 0)}"
                )
            except Exception as e:
                self._current_agent = None
                logger.error(f"  [{agent.name}] CRASHED: {e}")
                cycle_stats['errors'] += 1
                self.notifier.agent_error(agent.name, str(e))

                # Circuit breaker: record error, may trip to OPEN
                circuit.record_error(str(e))
                if circuit.state == CircuitState.OPEN:
                    self.notifier.agent_circuit_open(
                        agent.name, circuit.consecutive_errors,
                        circuit.open_count)

                # Escalation: too many open periods → TG alert
                if circuit.needs_escalation:
                    self.notifier.agent_circuit_escalation(
                        agent.name, circuit.open_count,
                        circuit.last_error_msg)

                # Skip agent, continue with next
                try:
                    self.db.set_status(agent.name, 'error',
                                       note=str(e)[:200])
                except Exception as status_err:
                    logger.warning(
                        f"  [{agent.name}] Failed to set error status: "
                        f"{status_err}"
                    )

        # ── Resilience: blocked task auto-retry ────────────
        cycle_stats['skipped_agents'] = skipped_agents
        retried = self._retry_blocked_tasks()
        cycle_stats['retries'] = retried

        # ── Guardrail v1: drain mode reporting ──────────────
        drain = self.db.is_drain_mode()
        cycle_stats['drain_mode'] = drain

        if drain and not self._prev_drain_mode:
            # Transition: OFF → ON
            breaches = self.db.get_cap_breaches()
            self.notifier.drain_mode_entered(breaches)
            logger.warning(f"  [guardrail] Drain mode ENTERED: {breaches}")
            self._drain_cycles = 1
        elif drain:
            self._drain_cycles += 1
            if self._drain_cycles > CAP_BREACH_ESCALATE_CYCLES:
                # Persistent breach — escalate per cap
                breaches = self.db.get_cap_breaches()
                for status, (count, cap) in breaches.items():
                    self.notifier.cap_breach_alert(status, count, cap)
                logger.warning(
                    f"  [guardrail] Drain persistent "
                    f"({self._drain_cycles} cycles): {breaches}"
                )
        elif not drain and self._prev_drain_mode:
            # Transition: ON → OFF
            self.notifier.drain_mode_exited()
            logger.info("  [guardrail] Drain mode EXITED")
            self._drain_cycles = 0

        self._prev_drain_mode = drain

        # ── Guardrail v1: daily digest ─────────────────────
        now = time.time()
        if now - self._last_digest_time >= DAILY_DIGEST_INTERVAL_S:
            try:
                self.notifier.daily_digest(self.db)
                self._last_digest_time = now
                logger.info("  [guardrail] Daily digest sent")
            except Exception as e:
                logger.warning(f"  [guardrail] Daily digest failed: {e}")

        # Send summary (only if something happened)
        self.notifier.heartbeat_summary(
            self._cycle,
            cycle_stats['reviews'],
            cycle_stats['tasks'],
            cycle_stats['promotions'],
        )

        # ── Persist cycle metrics ─────────────────────────
        cycle_stats['agent_count'] = len(self.agents)
        cycle_stats['drain_cycles'] = self._drain_cycles
        cycle_stats['cycle_duration_s'] = time.time() - cycle_start
        try:
            self.db.save_cycle_metrics(cycle_stats)
        except Exception as e:
            logger.warning(f"  [metrics] save failed: {e}")

        # ── Log circuit breaker summary if any non-closed ────
        open_circuits = self._circuits.open_circuits()
        if open_circuits:
            names = [c.agent_name for c in open_circuits]
            logger.warning(f"  [circuit] Open circuits: {names}")

        logger.info(
            f"=== Cycle {self._cycle} done: "
            f"reviews={cycle_stats['reviews']} "
            f"tasks={cycle_stats['tasks']} "
            f"promotions={cycle_stats['promotions']} "
            f"errors={cycle_stats['errors']} "
            f"skipped={skipped_agents} "
            f"retries={retried} "
            f"duration={cycle_stats['cycle_duration_s']:.1f}s ==="
        )

        return cycle_stats

    def _retry_blocked_tasks(self) -> int:
        """Auto-retry blocked tasks older than RETRY_MIN_AGE_S.

        Returns number of tasks retried (moved blocked → in_progress).
        Respects RETRY_MAX_ATTEMPTS via comment counting.
        """
        retried = 0
        try:
            blocked = self.db.get_tasks_by_status('blocked')
        except Exception as e:
            logger.warning(f"  [retry] failed to query blocked tasks: {e}")
            return 0

        now_ts = time.time()

        for task in blocked:
            if not task.blocked_since:
                continue

            # Parse blocked_since timestamp
            try:
                from datetime import datetime, timezone
                blocked_dt = datetime.strptime(
                    task.blocked_since, '%Y-%m-%d %H:%M:%S')
                blocked_dt = blocked_dt.replace(tzinfo=timezone.utc)
                blocked_age_s = now_ts - blocked_dt.timestamp()
            except (ValueError, AttributeError):
                continue

            if blocked_age_s < RETRY_MIN_AGE_S:
                continue

            # Count previous retry attempts via comments
            try:
                comments = self.db.get_comments(task.id)
                retry_count = sum(
                    1 for c in comments
                    if '🔄 Auto-retry' in (c.body or '')
                )
            except Exception as count_err:
                logger.debug(
                    f"  [retry] Task #{task.id} comment query failed: "
                    f"{count_err}"
                )
                retry_count = 0

            if retry_count >= RETRY_MAX_ATTEMPTS:
                logger.info(
                    f"  [retry] Task #{task.id} max retries "
                    f"({RETRY_MAX_ATTEMPTS}) reached — skipping"
                )
                continue

            # Attempt retry: blocked → in_progress
            try:
                self.db.transition(task.id, 'in_progress',
                                   actor=task.assigned_to)
                self.db.add_comment(
                    task.id, 'heartbeat',
                    f"🔄 Auto-retry #{retry_count + 1}/{RETRY_MAX_ATTEMPTS} "
                    f"(blocked {blocked_age_s / 60:.0f}m)",
                    'comment',
                )
                retried += 1
                logger.info(
                    f"  [retry] Task #{task.id} retried "
                    f"(attempt {retry_count + 1}/{RETRY_MAX_ATTEMPTS})"
                )
            except ValueError as e:
                # Transition blocked (drain mode, WIP cap, etc.)
                logger.debug(f"  [retry] Task #{task.id} retry blocked: {e}")
            except Exception as e:
                logger.warning(
                    f"  [retry] Task #{task.id} retry failed: {e}")

        return retried

    def run(self, max_hours: Optional[float] = None,
            dry_run: bool = False) -> None:
        """Run heartbeat loop. max_hours=None → infinite."""
        start_time = time.time()
        max_seconds = max_hours * 3600 if max_hours else float('inf')

        logger.info(
            f"Heartbeat loop started. "
            f"Interval: {HEARTBEAT_INTERVAL_S}s, "
            f"Agents: {len(self.agents)}, "
            f"Max hours: {max_hours or 'infinite'}"
        )

        while self._running:
            self.run_once()

            if dry_run:
                logger.info("Dry run: stopping after 1 cycle")
                break

            elapsed = time.time() - start_time
            if elapsed >= max_seconds:
                logger.info(f"Max runtime reached ({max_hours}h)")
                break

            # Sleep until next heartbeat — poll TG every 10s
            remaining = HEARTBEAT_INTERVAL_S - (time.time() - start_time) % HEARTBEAT_INTERVAL_S
            logger.info(f"Sleeping {remaining:.0f}s until next heartbeat...")
            self._interruptible_sleep(remaining)

        logger.info(
            f"Heartbeat loop stopped. "
            f"Completed {self._cycle} cycles, "
            f"last_agent={self._current_agent or 'none'}"
        )
