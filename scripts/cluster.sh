#!/usr/bin/env bash
set -euo pipefail
umask 077

root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
state="$root/.mate"
data="$state/data"
unset PGHOSTADDR PGSERVICE PGSERVICEFILE PGOPTIONS PGDATA DATABASE_URL
export PGHOST="$state" PGPORT=55437 PGDATABASE=postgres PGUSER=postgres

die() { echo "$*" >&2; exit 1; }
sql() { "$bin/psql" -X -v ON_ERROR_STOP=1 -P pager=off "$@"; }
ready() {
    local i
    for ((i=0; i<120; i++)); do
        if [[ $(sql -Atqc 'SELECT EXISTS (SELECT FROM df._worker_epoch WHERE last_seen_at >= pg_postmaster_start_time())') == t ]]; then
            return
        fi
        sleep .5
    done
    die "No fresh pg_durable worker heartbeat. See $state/server.log"
}

action=${1:-}
if [[ $action == init ]]; then
    cfg=${PG_CONFIG:-pg_config}
    bin=$("$cfg" --bindir)
    control=$("$cfg" --sharedir)/extension/pg_durable.control
    [[ -x $bin/initdb && -r $control ]] || die 'Select a PostgreSQL server with pg_durable installed using PG_CONFIG.'
    version=$(awk -F"'" '/^default_version/{print $2}' "$control")
    printf '%s\n' 0.2.9 "$version" | sort -VC || die "Selected pg_durable $version; set PG_CONFIG to an installation with 0.2.9 or newer."
    mkdir -m 700 -- "$state" || die "Refusing to initialize over $state. Use start for an existing demo."
    "$bin/initdb" -D "$data" -U postgres --no-locale -E UTF8 --auth-local=trust --auth-host=reject \
        -c "listen_addresses=" -c "unix_socket_directories=$state" -c "port=$PGPORT" >/dev/null
    printf "%s\n" "shared_preload_libraries = 'pg_durable'" "pg_durable.worker_role = 'postgres'" >> "$data/postgresql.conf"
    printf '%s\n' "$bin" > "$state/mate-bindir"
    "$bin/pg_ctl" -w -D "$data" -l "$state/server.log" start
    sql -c 'CREATE EXTENSION pg_durable' \
        -c 'CREATE ROLE mate_app LOGIN' \
        -c "SELECT df.grant_usage('mate_app')" \
        -c 'CREATE SCHEMA mate AUTHORIZATION mate_app'
    ready
    sql -c "SELECT current_setting('server_version') AS postgres, extversion AS pg_durable FROM pg_extension WHERE extname = 'pg_durable'"
    exit
fi

[[ $action =~ ^(psql|admin|restart|start|stop)$ ]] || die 'Usage: cluster.sh init|start|stop|restart|psql [psql args...]|admin [psql args...]'
[[ -f $state/mate-bindir && ! -L $state && ! -L $data ]] || die 'No applet-owned cluster here. Run cluster.sh init first.'
read -r bin < "$state/mate-bindir"
shift
case $action in
    psql) PGUSER=mate_app sql "$@" ;;
    admin) sql "$@" ;;
    stop) "$bin/pg_ctl" -D "$data" -m fast -w stop ;;
    start|restart)
        "$bin/pg_ctl" -D "$data" -l "$state/server.log" -m fast -w "$action"
        ready
        ;;
esac
