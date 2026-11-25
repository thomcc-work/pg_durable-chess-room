import argparse
import subprocess
import sys

import psycopg

from . import cluster


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="uv run -m mate", description="Mate in One prompt evaluator")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("init", "create a private cluster and install the applet schema"),
        ("start", "open the saved cluster"), ("stop", "stop it without deleting data"),
        ("restart", "restart the applet cluster"), ("psql", "open psql as mate_app (accepts psql flags)"),
        ("admin", "open the private cluster's admin console (accepts psql flags)"),
    ):
        commands.add_parser(name, help=help_text)
    console = argv[:1] in (["psql"], ["admin"])
    args = parser.parse_args(argv[:1] if console else argv)
    cluster.use_private_socket()
    if console:
        cluster.psql(argv[1:], "postgres" if args.command == "admin" else "mate_app")
    elif args.command == "init":
        cluster.init()
    else:
        cluster.pg_ctl(args.command)
        if args.command != "stop":
            cluster.wait_for_worker()


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
    except (ValueError, OSError, psycopg.Error) as exc:
        sys.exit(f"mate: {exc}")
