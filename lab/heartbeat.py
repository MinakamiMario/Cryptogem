"""Heartbeat loop — sequential agent execution with stagger."""
from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Optional

from lab.agents.base import BaseAgent
from lab.config import HEARTBEAT_INTERVAL_S, HEARTBEAT_STAGGER_S
from lab.db import LabDB
from lab.notifier import LabNotifier
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
        self._cycle += 1
        cycle_stats = {
            'cycle': self._cycle,
            'reviews': 0,
            'tasks': 0,
            'promotions': 0,
            'errors': 0,
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

        for i, agent in enumerate(self.agents):
            if not self._running:
                break

            # Stagger: 1 min between agents, poll TG every 10s
            if i > 0:
                self._interruptible_sleep(HEARTBEAT_STAGGER_S)

            try:
                self._current_agent = agent.name
                logger.info(f"  [{agent.name}] starting heartbeat")
                stats = agent.heartbeat()
                cycle_stats['reviews'] += stats.get('reviews', 0)
                cycle_stats['tasks'] += stats.get('tasks', 0)
                cycle_stats['promotions'] += stats.get('promotions', 0)
                cycle_stats['errors'] += stats.get('errors', 0)
                self._current_agent = None
                logger.info(
                    f"  [{agent.name}] done: "
                    f"reviews={stats.get('reviews', 0)} "
                    f"tasks={stats.get('tasks', 0)} "
                    f"errors={stats.get('errors', 0)}"
                )
            except Exception as e:
                self._current_agent = None
                logger.error(f"  [{agent.name}] CRASHED: {e}")
                cycle_stats['errors'] += 1
                self.notifier.agent_error(agent.name, str(e))
                # Skip agent, continue with next
                try:
                    self.db.set_status(agent.name, 'error',
                                       note=str(e)[:200])
                except Exception:
                    pass

        # Send summary (only if something happened)
        self.notifier.heartbeat_summary(
            self._cycle,
            cycle_stats['reviews'],
            cycle_stats['tasks'],
            cycle_stats['promotions'],
        )

        logger.info(
            f"=== Cycle {self._cycle} done: "
            f"reviews={cycle_stats['reviews']} "
            f"tasks={cycle_stats['tasks']} "
            f"promotions={cycle_stats['promotions']} "
            f"errors={cycle_stats['errors']} ==="
        )

        return cycle_stats

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
