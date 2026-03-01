"""Lab CLI — entry point for the quant research lab.

Usage:
    python -m lab.main init                              # Initialize database
    python -m lab.main run [--hours N] [--dry-run]       # Start heartbeat loop
    python -m lab.main status                            # Show dashboard
    python -m lab.main goal add "title" --agents a,b,c   # Add goal
    python -m lab.main goal list                         # List goals
    python -m lab.main tasks [--status S]                # List tasks
    python -m lab.main task approve ID                   # Approve task (user)
    python -m lab.main task reject ID                    # Reject task (user)
    python -m lab.main task move ID STATUS               # Move task (user)
    python -m lab.main dashboard                         # Send dashboard to Telegram
    python -m lab.main listen                            # Listen for Telegram messages
    python -m lab.main status --tg                       # Dashboard + send to Telegram
    python -m lab.main tasks --tg                        # Tasks + send to Telegram
    python -m lab.main report --tg                       # Report + send to Telegram
    python -m lab.main report                            # Full report
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure repo root is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lab.config import AGENT_NAMES, DB_PATH, REPORTS_DIR
from lab.db import LabDB
from lab.heartbeat import HeartbeatLoop
from lab.notifier import LabNotifier


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


import io

def _capture_output(func, *args, **kwargs) -> str:
    """Capture print output from a function into a string."""
    buf = io.StringIO()
    import contextlib
    with contextlib.redirect_stdout(buf):
        func(*args, **kwargs)
    return buf.getvalue()


def _tee_to_telegram(text: str) -> None:
    """Send captured output to Telegram."""
    notifier = LabNotifier(enabled=True)
    notifier.send_output(text)


def get_agents(db: LabDB, notifier: LabNotifier) -> list:
    """Instantiate available agents. Boss always first."""
    from lab.agents.boss import BossAgent
    from lab.agents.infra_guardian import InfraGuardian

    agents = [
        BossAgent(db, notifier),
        InfraGuardian(db, notifier),
    ]

    # Phase 2+ agents (import if available)
    optional = [
        ('lab.agents.edge_analyst', 'EdgeAnalyst'),
        ('lab.agents.risk_governor', 'RiskGovernor'),
        ('lab.agents.robustness_auditor', 'RobustnessAuditor'),
        ('lab.agents.deployment_judge', 'DeploymentJudge'),
        ('lab.agents.meta_research', 'MetaResearchAgent'),
        ('lab.agents.hypothesis_gen', 'HypothesisGenAgent'),
        ('lab.agents.live_monitor', 'LiveMonitor'),
        ('lab.agents.portfolio_architect', 'PortfolioArchitect'),
    ]
    for module_name, class_name in optional:
        try:
            import importlib
            mod = importlib.import_module(module_name)
            cls = getattr(mod, class_name)
            agents.append(cls(db, notifier))
        except (ImportError, AttributeError):
            pass  # Agent not yet implemented

    return agents


# ── Self-Test ─────────────────────────────────────────────

logger = logging.getLogger('lab.main')


def self_test(db: LabDB, notifier: LabNotifier) -> bool:
    """E2E self-test bij startup. Rapporteert naar TG.

    Twee check-levels:
    - HARD: BotToken, DB, Agents, Telegram → False = exit(1)
    - SOFT: Goals → warn only, daemon draait door
    """
    hard_checks: list[tuple[str, bool, str]] = []
    soft_checks: list[tuple[str, bool, str]] = []

    # HARD 1: Bot token aanwezig (notifier laadt .env zelf)
    hard_checks.append(('BotToken', notifier.enabled, 'ok' if notifier.enabled else 'MISSING'))

    # HARD 2: DB writable
    try:
        db.get_status_summary()
        hard_checks.append(('DB', True, ''))
    except Exception as e:
        hard_checks.append(('DB', False, str(e)[:80]))

    # HARD 3: Agents laden
    try:
        agents = get_agents(db, notifier)
        hard_checks.append(('Agents', True, f'{len(agents)} geladen'))
    except Exception as e:
        hard_checks.append(('Agents', False, str(e)[:80]))

    # HARD 4: Telegram bereikbaar
    try:
        notifier.send_output('🧪 Self-test gestart...')
        hard_checks.append(('Telegram', True, ''))
    except Exception as e:
        hard_checks.append(('Telegram', False, str(e)[:80]))

    # SOFT: Goals actief (0 goals = OK maar warn)
    try:
        goals = db.get_goals()
        if goals:
            soft_checks.append(('Goals', True, f'{len(goals)} actief'))
        else:
            soft_checks.append(('Goals', True, '0 actief'))
    except Exception as e:
        soft_checks.append(('Goals', False, str(e)[:80]))

    # Rapport
    hard_ok = all(ok for _, ok, _ in hard_checks)
    no_goals = any(detail == '0 actief' for _, _, detail in soft_checks)

    if hard_ok and not no_goals:
        header = '✅ Lab self-test PASS'
    elif hard_ok:
        header = '⚠️ Lab self-test PASS (degraded — 0 goals)'
    else:
        header = '❌ Lab self-test FAIL'

    lines = [header]
    for name, ok, detail in hard_checks + soft_checks:
        if not ok:
            s = '❌'
        elif detail == '0 actief':
            s = '⚠️'
        else:
            s = '✅'
        lines.append(f'  {s} {name} {detail}')

    msg = '\n'.join(lines)
    logger.info(msg)
    try:
        notifier.send_output(msg)
    except Exception:
        pass

    return hard_ok  # alleen hard fails killen de daemon


# ── Commands ──────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> None:
    """Initialize database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    db = LabDB()
    db.init_schema()
    db.close()
    print(f"Database initialized at {DB_PATH}")
    print(f"Reports directory at {REPORTS_DIR}")
    print(f"Registered {len(AGENT_NAMES)} agents: {', '.join(AGENT_NAMES)}")


def cmd_run(args: argparse.Namespace) -> None:
    """Start heartbeat loop with self-test at startup."""
    db = LabDB()
    db.init_schema()
    notifier = LabNotifier(enabled=not args.quiet)

    # Self-test bij startup — hard fails → exit(1)
    if not self_test(db, notifier):
        logger.error("Self-test FAILED — aborting")
        db.close()
        sys.exit(1)

    agents = get_agents(db, notifier)

    print(f"Starting lab with {len(agents)} agents:")
    for a in agents:
        print(f"  - {a.name} ({a.role})")

    loop = HeartbeatLoop(db, notifier, agents)
    try:
        loop.run(max_hours=args.hours, dry_run=args.dry_run)
    finally:
        db.close()


def cmd_status(args: argparse.Namespace) -> None:
    """Show dashboard. With --tg also sends to Telegram."""
    db = LabDB()
    summary = db.get_status_summary()

    lines = ["\n=== CRYPTOGEM LAB STATUS ===\n"]
    lines.append("Tasks:")
    for status, count in summary['tasks'].items():
        if count > 0:
            lines.append(f"  {status:15s} {count}")

    lines.append("\nAgents:")
    for agent, info in summary['agents'].items():
        status = info['status']
        hb = info.get('last_heartbeat', 'never')
        icon = {'idle': '💤', 'working': '🔄', 'error': '🚨'}.get(status, '⚪')
        lines.append(f"  {icon} {agent:25s} {status:8s} (last: {hb})")

    if summary['goals']:
        lines.append("\nGoals:")
        for g in summary['goals']:
            done = g['done']
            total = g['total_tasks']
            pct = (done / total * 100) if total else 0
            lines.append(f"  [{g['id']}] {g['title'][:50]:50s} "
                         f"{done}/{total} ({pct:.0f}%)")

    lines.append("")
    output = '\n'.join(lines)
    print(output)

    if getattr(args, 'tg', False):
        notifier = LabNotifier(enabled=True)
        notifier.send_dashboard(db)
    db.close()


def cmd_goal_add(args: argparse.Namespace) -> None:
    """Add a goal."""
    agents = [a.strip() for a in args.agents.split(',')]
    for a in agents:
        if a not in AGENT_NAMES:
            print(f"Warning: '{a}' is not a registered agent")

    db = LabDB()
    db.init_schema()
    goal_id = db.create_goal(
        title=args.title,
        agents=agents,
        tasks_per_day=args.tasks_per_day,
    )
    db.close()
    print(f"Goal #{goal_id} created: {args.title}")
    print(f"  Agents: {', '.join(agents)}")
    print(f"  Tasks/day: {args.tasks_per_day}")


def cmd_goal_list(args: argparse.Namespace) -> None:
    """List goals."""
    db = LabDB()
    goals = db.get_goals()
    db.close()

    if not goals:
        print("No active goals. Create one with: python -m lab.main goal add")
        return

    print("\n=== ACTIVE GOALS ===\n")
    for g in goals:
        tasks = db.get_tasks_by_goal(g.id) if hasattr(db, 'conn') else []
        print(f"  [{g.id}] {g.title}")
        print(f"      Agents: {', '.join(g.agents)}")
        print(f"      Tasks/day: {g.tasks_per_day}")
        print()


def cmd_tasks(args: argparse.Namespace) -> None:
    """List tasks. With --tg also sends to Telegram."""
    db = LabDB()
    if args.status:
        tasks = db.get_tasks_by_status(args.status)
    else:
        tasks = []
        for s in ['in_progress', 'peer_review', 'review', 'approved',
                  'todo', 'proposal', 'backlog']:
            tasks.extend(db.get_tasks_by_status(s))

    if not tasks:
        print("No tasks found.")
        db.close()
        return

    lines = [f"\n{'ID':>4} {'Status':>13} {'Agent':>22} {'Title'}"]
    lines.append("-" * 80)
    for t in tasks:
        lines.append(f"  {t.id:>3} {t.status:>13} {t.assigned_to:>22} {t.title[:40]}")
    lines.append("")
    output = '\n'.join(lines)
    print(output)

    if getattr(args, 'tg', False):
        _tee_to_telegram(output)
    db.close()


def cmd_task_approve(args: argparse.Namespace) -> None:
    """Approve a task (user action). Syncs status to Telegram.

    Handles: approved → done (executive signoff), backlog → todo (deprecated).
    """
    db = LabDB()
    notifier = LabNotifier(enabled=True)
    task = db.get_task(args.id)
    if not task:
        print(f"Task #{args.id} not found")
        return

    try:
        if task.status == 'approved':
            db.transition(args.id, 'done', actor='user')
            print(f"Task #{args.id} approved and done: {task.title}")
            notifier.notify_task_done(args.id, task.title, via='cli')
        elif task.status == 'backlog':
            db.transition(args.id, 'todo', actor='user')
            print(f"Task #{args.id} moved to todo: {task.title}")
        else:
            print(f"Task #{args.id} is in '{task.status}', "
                  f"expected 'approved' or 'backlog'")
    except ValueError as e:
        print(f"Error: {e}")
    finally:
        db.close()


def cmd_task_reject(args: argparse.Namespace) -> None:
    """Reject a task (user action). Sends back to in_progress, syncs to Telegram.

    Handles: approved → in_progress (user reject).
    """
    db = LabDB()
    notifier = LabNotifier(enabled=True)
    task = db.get_task(args.id)
    if not task:
        print(f"Task #{args.id} not found")
        return

    try:
        if task.status == 'approved':
            db.transition(args.id, 'in_progress', actor='user')
            db.add_comment(
                args.id, 'user',
                '❌ Afgekeurd via CLI — terug naar in_progress',
                'rejection'
            )
            print(f"Task #{args.id} rejected → in_progress: {task.title}")
            notifier.notify_task_rejected(args.id, task.title, via='cli')
        else:
            print(f"Task #{args.id} is in '{task.status}', expected 'approved'")
    except ValueError as e:
        print(f"Error: {e}")
    finally:
        db.close()


def cmd_task_move(args: argparse.Namespace) -> None:
    """Move task to specific status (user action)."""
    db = LabDB()
    try:
        db.transition(args.id, args.status, actor='user')
        print(f"Task #{args.id} moved to '{args.status}'")
    except ValueError as e:
        print(f"Error: {e}")
    finally:
        db.close()


def cmd_listen(args: argparse.Namespace) -> None:
    """Listen for Telegram messages and print them to console."""
    import time as _time
    db = LabDB()
    db.init_schema()
    notifier = LabNotifier(enabled=True)
    if not notifier.enabled:
        print("Telegram notifier not active — check LAB_TELEGRAM_BOT_TOKEN")
        return

    print("Luisteren naar Telegram... (Ctrl+C om te stoppen)\n")
    notifier.send_output("🔗 CLI luistert mee — berichten worden hier opgepakt")

    try:
        while True:
            actions, messages = notifier.poll_telegram(db)
            if actions:
                print(f"  [{actions} actie(s) verwerkt]")
            for msg in messages:
                print(f"💬 [Telegram] {msg}")
            _time.sleep(3)
    except KeyboardInterrupt:
        print("\nGestopt.")
    finally:
        db.close()


def cmd_dashboard_tg(args: argparse.Namespace) -> None:
    """Send full dashboard to Telegram."""
    db = LabDB()
    notifier = LabNotifier(enabled=True)
    notifier.send_dashboard(db)
    db.close()
    print("Dashboard verstuurd naar Telegram.")


def cmd_report(args: argparse.Namespace) -> None:
    """Full comprehensive report — JSON + markdown."""
    db = LabDB()
    summary = db.get_status_summary()
    activity = db.get_recent_activity(limit=30)
    goals = db.get_goals()

    report = {
        'generated_at': __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc
        ).isoformat(),
        'goals': [],
        'tasks_by_status': summary['tasks'],
        'agents': summary['agents'],
        'blocked_tasks': [],
        'recent_artifacts': [],
        'recent_activity': activity[:15],
    }

    # Goals detail
    for g in goals:
        tasks = db.get_tasks_by_goal(g.id)
        done = sum(1 for t in tasks if t.status == 'done')
        report['goals'].append({
            'id': g.id,
            'title': g.title,
            'agents': g.agents,
            'tasks_total': len(tasks),
            'tasks_done': done,
            'progress_pct': round(done / len(tasks) * 100, 1) if tasks else 0,
        })

    # Blocked tasks (>24h in blocked/in_progress)
    for status in ['blocked', 'in_progress']:
        for task in db.get_tasks_by_status(status):
            report['blocked_tasks'].append({
                'id': task.id,
                'title': task.title,
                'status': task.status,
                'assigned_to': task.assigned_to,
                'updated_at': task.updated_at,
            })

    # Recent artifacts (last 10 tasks with artifacts)
    for status in ['done', 'approved', 'review', 'peer_review']:
        for task in db.get_tasks_by_status(status):
            if task.artifact_path:
                report['recent_artifacts'].append({
                    'task_id': task.id,
                    'title': task.title[:50],
                    'agent': task.assigned_to,
                    'path': task.artifact_path,
                })
    report['recent_artifacts'] = report['recent_artifacts'][:10]

    db.close()

    # Output format
    if getattr(args, 'json_output', False):
        output = json.dumps(report, indent=2, default=str)
        print(output)
        if getattr(args, 'tg', False):
            _tee_to_telegram(output)
    else:
        output = _capture_output(_print_report_markdown, report)
        print(output, end='')
        if getattr(args, 'tg', False):
            _tee_to_telegram(output)


def _print_report_markdown(report: dict) -> None:
    """Print report as readable markdown to stdout."""
    print("\n# Cryptogem Lab Report")
    print(f"\nGenerated: {report['generated_at']}")

    # Goals
    print("\n## Goals\n")
    for g in report['goals']:
        bar = '█' * int(g['progress_pct'] / 5) + '░' * (20 - int(g['progress_pct'] / 5))
        print(f"  [{g['id']}] {g['title']}")
        print(f"      {bar} {g['progress_pct']:.0f}% "
              f"({g['tasks_done']}/{g['tasks_total']})")
        print(f"      Agents: {', '.join(g['agents'])}")

    # Tasks by status
    print("\n## Tasks\n")
    for status, count in report['tasks_by_status'].items():
        if count > 0:
            icon = {'done': '✅', 'in_progress': '🔄', 'blocked': '🚧',
                    'peer_review': '👀', 'review': '📋', 'todo': '📝',
                    'backlog': '📦', 'approved': '✓'}.get(status, '⚪')
            print(f"  {icon} {status:15s} {count}")

    # Blocked tasks
    if report['blocked_tasks']:
        print("\n## ⚠️ Blocked/Stuck Tasks\n")
        for t in report['blocked_tasks']:
            print(f"  #{t['id']:3d} [{t['status']:12s}] "
                  f"{t['assigned_to']:>22s}  {t['title'][:40]}")

    # Recent artifacts
    if report['recent_artifacts']:
        print("\n## Recent Artifacts\n")
        for a in report['recent_artifacts'][:5]:
            print(f"  #{a['task_id']:3d} [{a['agent']:>22s}] {a['path']}")

    # Agent status
    print("\n## Agents\n")
    for agent, info in report['agents'].items():
        status = info['status']
        hb = info.get('last_heartbeat', 'never')
        icon = {'idle': '💤', 'working': '🔄', 'error': '🚨'}.get(status, '⚪')
        print(f"  {icon} {agent:25s} {status:8s} (last: {hb})")

    # Recent activity
    if report['recent_activity']:
        print("\n## Recent Activity\n")
        for a in report['recent_activity'][:10]:
            print(f"  {a['created_at']} [{a['agent']:>20s}] "
                  f"{a['action']:>15s}")

    print()


# ── CLI Parser ────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='lab',
        description='Cryptogem Quant Research Lab',
    )
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Disable Telegram notifications')

    sub = parser.add_subparsers(dest='command')

    # init
    sub.add_parser('init', help='Initialize database')

    # run
    run_p = sub.add_parser('run', help='Start heartbeat loop')
    run_p.add_argument('--hours', type=float, default=None)
    run_p.add_argument('--dry-run', action='store_true')

    # status
    status_p = sub.add_parser('status', help='Show dashboard')
    status_p.add_argument('--tg', action='store_true',
                          help='Also send output to Telegram')

    # dashboard (send to Telegram)
    sub.add_parser('dashboard', help='Send dashboard to Telegram')

    # listen
    sub.add_parser('listen', help='Listen for Telegram messages')

    # goal
    goal_p = sub.add_parser('goal', help='Goal management')
    goal_sub = goal_p.add_subparsers(dest='goal_cmd')

    goal_add = goal_sub.add_parser('add', help='Add goal')
    goal_add.add_argument('title', type=str)
    goal_add.add_argument('--agents', type=str, required=True)
    goal_add.add_argument('--tasks-per-day', type=int, default=2)

    goal_sub.add_parser('list', help='List goals')

    # tasks
    tasks_p = sub.add_parser('tasks', help='List tasks')
    tasks_p.add_argument('--status', type=str, default=None)
    tasks_p.add_argument('--tg', action='store_true',
                         help='Also send output to Telegram')

    # task
    task_p = sub.add_parser('task', help='Task actions')
    task_sub = task_p.add_subparsers(dest='task_cmd')

    task_approve = task_sub.add_parser('approve', help='Approve task')
    task_approve.add_argument('id', type=int)

    task_reject = task_sub.add_parser('reject', help='Reject task')
    task_reject.add_argument('id', type=int)

    task_move = task_sub.add_parser('move', help='Move task')
    task_move.add_argument('id', type=int)
    task_move.add_argument('status', type=str)

    # report
    report_p = sub.add_parser('report', help='Full report')
    report_p.add_argument('--json', dest='json_output', action='store_true',
                          help='Output as JSON')
    report_p.add_argument('--tg', action='store_true',
                          help='Also send output to Telegram')

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(verbose=getattr(args, 'verbose', False))

    if args.command == 'init':
        cmd_init(args)
    elif args.command == 'run':
        cmd_run(args)
    elif args.command == 'status':
        cmd_status(args)
    elif args.command == 'dashboard':
        cmd_dashboard_tg(args)
    elif args.command == 'listen':
        cmd_listen(args)
    elif args.command == 'goal':
        if args.goal_cmd == 'add':
            cmd_goal_add(args)
        elif args.goal_cmd == 'list':
            cmd_goal_list(args)
        else:
            parser.parse_args(['goal', '-h'])
    elif args.command == 'tasks':
        cmd_tasks(args)
    elif args.command == 'task':
        if args.task_cmd == 'approve':
            cmd_task_approve(args)
        elif args.task_cmd == 'reject':
            cmd_task_reject(args)
        elif args.task_cmd == 'move':
            cmd_task_move(args)
        else:
            parser.parse_args(['task', '-h'])
    elif args.command == 'report':
        cmd_report(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
