"""CLI entry point — python -m nightwatch."""

from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv


def main() -> int:
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(
        prog="nightwatch",
        description=(
            "AI-powered production error analysis"
            " — run once, analyze everything, report, done."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    # --- run ---
    run_parser = sub.add_parser("run", help="Analyze production errors")
    run_parser.add_argument("--since", default=None, help="Lookback period (e.g. 24h, 12h)")
    run_parser.add_argument("--max-errors", type=int, default=None, help="Max errors to analyze")
    run_parser.add_argument(
        "--max-issues", type=int, default=None,
        help="Max GitHub issues to create",
    )
    run_parser.add_argument(
        "--dry-run", action="store_true",
        help="Analyze only, no issues/PRs/Slack",
    )
    run_parser.add_argument("--verbose", action="store_true", help="Show iteration details")
    run_parser.add_argument("--model", default=None, help="Override Claude model")
    run_parser.add_argument(
        "--agent", default="base-analyzer",
        help="Agent config name (from nightwatch/agents/*.md)",
    )
    run_parser.add_argument(
        "--workflows", default=None,
        help="Comma-separated workflow names (default: errors)",
    )
    run_parser.add_argument(
        "--guardrails-output", default=None,
        help="Path to write guardrails.md (Ralph integration)",
    )

    # --- check ---
    sub.add_parser("check", help="Validate config and API connectivity")

    args = parser.parse_args()

    # Default to 'run' if no subcommand
    if not args.command:
        args.command = "run"
        args.since = None
        args.max_errors = None
        args.max_issues = None
        args.dry_run = False
        args.verbose = False
        args.model = None
        args.agent = "base-analyzer"
        args.workflows = None
        args.guardrails_output = None

    # Set up logging
    level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command == "check":
        return _check()
    elif args.command == "run":
        return _run(args)
    else:
        parser.print_help()
        return 1


def _check() -> int:
    """Validate config and API connectivity."""
    print("NightWatch config check\n")

    # Config
    try:
        from nightwatch.config import get_settings
        settings = get_settings()
        print("  [OK] Config loaded from .env")
    except Exception as e:
        print(f"  [FAIL] Config: {e}")
        return 1

    # New Relic
    try:
        from nightwatch.newrelic import NewRelicClient
        nr = NewRelicClient()
        result = nr.query_nrql("SELECT count(*) FROM TransactionError SINCE 1 hour ago")
        nr.close()
        count = result[0].get("count", 0) if result else 0
        print(f"  [OK] New Relic: {count} errors in last hour")
    except Exception as e:
        print(f"  [FAIL] New Relic: {e}")

    # GitHub
    try:
        from nightwatch.github import GitHubClient
        gh = GitHubClient()
        repo = gh.repo
        print(f"  [OK] GitHub: {repo.full_name} ({repo.default_branch})")
    except Exception as e:
        print(f"  [FAIL] GitHub: {e}")

    # Slack
    try:
        from nightwatch.slack import SlackClient
        slack = SlackClient()
        uid = slack._get_user_id(settings.slack_notify_user)
        if uid:
            print(f"  [OK] Slack: user '{settings.slack_notify_user}' found ({uid})")
        else:
            print(f"  [WARN] Slack: user '{settings.slack_notify_user}' not found")
    except Exception as e:
        print(f"  [FAIL] Slack: {e}")

    # Claude
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        client.messages.create(
            model=settings.nightwatch_model,
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        print(f"  [OK] Claude: {settings.nightwatch_model}")
    except Exception as e:
        print(f"  [FAIL] Claude: {e}")

    print("\nDone.")
    return 0


def _run(args: argparse.Namespace) -> int:
    """Execute the analysis pipeline."""
    from nightwatch.runner import run

    try:
        run(
            since=args.since,
            max_errors=args.max_errors,
            max_issues=args.max_issues,
            dry_run=args.dry_run,
            verbose=args.verbose,
            model=args.model,
            agent_name=args.agent,
        )
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as e:
        logging.getLogger("nightwatch").error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
