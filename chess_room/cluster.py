"""Control only this checkout's private PostgreSQL installation data."""

import os
import re
import shlex
import subprocess
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".chess-room"
DATA = STATE / "data"
MARKER = STATE / "pg-bindir"
LOG = STATE / "server.log"
PORT = "55437"


def use_private_socket() -> None:
    os.umask(0o077)
    for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGDATA", "DATABASE_URL"):
        os.environ.pop(key, None)
    # The pg_durable worker also needs this socket, including after pg_ctl restart.
    os.environ.update(PGHOST=str(STATE), PGPORT=PORT, PGDATABASE="postgres", PGUSER="postgres")


def bindir() -> Path:
    if STATE.is_symlink() or DATA.is_symlink() or MARKER.is_symlink() or not MARKER.is_file():
        raise ValueError("No applet-owned cluster here. Run 'uv run -m chess_room init' first.")
    binaries = Path(MARKER.read_text().strip())
    owner = STATE / "pg-data-owner"
    if owner.is_symlink() or (owner.exists() and owner.read_text().strip() != str(DATA.resolve())):
        raise ValueError("Refusing to control a cluster initialized in another directory.")
    if not owner.exists():
        # Older checkouts recorded only the binaries. Require independent evidence of the data path.
        options = DATA / "postmaster.opts"
        if not options.is_file() or shlex.split(options.read_text()) != [str(binaries / "postgres"), "-D", str(DATA)]:
            raise ValueError("Cannot establish ownership of this legacy data directory; refusing to control it.")
    return binaries


def connect(user: str = "chess_room_app") -> psycopg.Connection:
    bindir()  # Refuse a socket in a directory the applet did not initialize.
    return psycopg.connect(host=str(STATE), port=PORT, dbname="postgres", user=user, autocommit=True)


def psql(args: list[str], user: str = "chess_room_app") -> None:
    subprocess.run([bindir() / "psql", "-X", "-v", "ON_ERROR_STOP=1", "-P", "pager=off",
                    "-U", user, *args], check=True)


def pg_ctl(action: str) -> None:
    binaries = bindir()
    pid = DATA / "postmaster.pid"
    if pid.exists() and pid.read_text().splitlines()[1:2] != [str(DATA)]:
        raise ValueError("Postmaster PID file belongs to another data directory.")
    # Start with our own options rather than replaying postmaster.opts from a backup.
    if action == "restart":
        pg_ctl("stop")
        action = "start"
    subprocess.run([binaries / "pg_ctl", "-D", DATA, "-l", LOG, "-m", "fast", "-w", action], check=True)


def wait_for_worker() -> None:
    deadline = time.monotonic() + 60
    with connect("postgres") as db:
        while time.monotonic() < deadline:
            if db.execute("SELECT EXISTS (SELECT FROM df._worker_epoch "
                          "WHERE last_seen_at >= pg_postmaster_start_time())").fetchone() == (True,):
                return
            time.sleep(0.5)
    raise TimeoutError(f"No fresh pg_durable worker heartbeat. See {LOG}")


def bootstrap() -> None:
    with connect("postgres") as db, db.transaction():
        db.execute("CREATE EXTENSION IF NOT EXISTS pg_durable")
        if not db.execute("SELECT 1 FROM pg_roles WHERE rolname='chess_room_app'").fetchone():
            db.execute("CREATE ROLE chess_room_app LOGIN")
        if not db.execute("SELECT to_regnamespace('chess_room')").fetchone()[0]:
            db.execute("SELECT df.grant_usage('chess_room_app')")
            db.execute("CREATE SCHEMA chess_room AUTHORIZATION chess_room_app")
    wait_for_worker()
    with connect() as db:
        if not db.execute("SELECT to_regclass('chess_room.fixture_attempt')").fetchone()[0]:
            db.execute((ROOT / "sql/schema.sql").read_text())
        else:
            db.execute("ALTER TABLE chess_room.cell ADD COLUMN IF NOT EXISTS workflow_error text")


def start() -> None:
    status = subprocess.run([bindir() / "pg_ctl", "-D", DATA, "status"], stdout=subprocess.DEVNULL)
    if status.returncode == 3:  # A valid, stopped cluster.
        pg_ctl("start")
    else:
        status.check_returncode()
    bootstrap()


def init() -> None:
    cfg = os.environ.get("PG_CONFIG", "pg_config")
    binaries = Path(subprocess.check_output([cfg, "--bindir"], text=True).strip())
    shared = Path(subprocess.check_output([cfg, "--sharedir"], text=True).strip())
    control = shared / "extension/pg_durable.control"
    if not (binaries / "initdb").is_file() or not control.is_file():
        raise ValueError("Select a PostgreSQL server with pg_durable installed using PG_CONFIG.")
    version = re.search(r"^default_version\s*=\s*'(\d+)\.(\d+)\.(\d+)'", control.read_text(), re.M)
    if not version or tuple(map(int, version.groups())) < (0, 2, 9):
        raise ValueError("Set PG_CONFIG to an installation with pg_durable 0.2.9 or newer.")
    try:
        STATE.mkdir(mode=0o700)
    except FileExistsError:
        raise ValueError(f"Refusing to initialize over {STATE}. Use start for an existing demo.") from None

    subprocess.run([binaries / "initdb", "-D", DATA, "-U", "postgres", "--no-locale", "-E", "UTF8",
                    "--auth-local=trust", "--auth-host=reject", "-c", "listen_addresses=",
                    "-c", f"unix_socket_directories={STATE}", "-c", f"port={PORT}"],
                   stdout=subprocess.DEVNULL, check=True)
    with (DATA / "postgresql.conf").open("a") as config:
        config.write("\nshared_preload_libraries = 'pg_durable'\npg_durable.worker_role = 'postgres'\n")
    (STATE / "pg-data-owner").write_text(f"{DATA.resolve()}\n")
    MARKER.write_text(f"{binaries}\n")
    pg_ctl("start")
    bootstrap()
