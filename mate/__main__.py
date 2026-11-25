import argparse
import subprocess
import sys

import psycopg

from . import cluster, experiment, recovery


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="uv run -m mate", description="Mate in One prompt evaluator")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("init", "create a private cluster and install the applet schema"),
        ("start", "open the saved cluster"), ("stop", "stop it without deleting data"),
        ("restart", "restart the applet cluster"), ("psql", "open psql as mate_app (accepts psql flags)"),
        ("admin", "open the private cluster's admin console (accepts psql flags)"),
        ("game-demo", "restart mid-game, retry a move and continue against real Stockfish"),
    ):
        commands.add_parser(name, help=help_text)
    for name in ("new", "demo"):
        cmd = commands.add_parser(name, help="snapshot fixtures" if name == "new" else "run the fixture restart demo")
        cmd.add_argument("boards", nargs="?", type=int, help="number of positions (default: all)")
    live = commands.add_parser("new-live", help="snapshot prompts for an authorized deployment; no network")
    live.add_argument("deployment")
    live.add_argument("boards", nargs="?", type=int, default=1)
    for name in ("finish", "score"):
        commands.add_parser(name, help=f"{name} a saved run").add_argument("run_id", type=int)
    console = bool(argv) and argv[0] in ("psql", "admin")
    args = parser.parse_args(argv[:1] if console else argv)
    cluster.use_private_socket()
    if console:
        cluster.psql(argv[1:], "postgres" if args.command == "admin" else "mate_app")
    elif args.command == "init":
        cluster.init()
    elif args.command in ("start", "stop", "restart"):
        cluster.pg_ctl(args.command)
        if args.command != "stop":
            cluster.wait_for_worker()
    elif args.command == "demo":
        recovery.demo(args.boards)
    elif args.command == "game-demo":
        from .game_demo import demo
        demo()
    else:
        with cluster.connect() as db:
            if args.command in ("new", "new-live"):
                print(experiment.new_run(db, args.boards, getattr(args, "deployment", None)))
            else:
                run = experiment.get_run(db, args.run_id)
                if args.command == "finish":
                    experiment.finish(db, run)
                else:
                    experiment.scorecard(db, run)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
    except (ValueError, OSError, psycopg.Error) as exc:
        sys.exit(f"mate: {exc}")
