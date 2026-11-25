#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
psql() { ./scripts/cluster.sh psql "$@"; }
die() { echo "$*" >&2; exit 1; }
positive() { [[ $1 =~ ^[1-9][0-9]*$ ]]; }

launch_pair() {
    # df.start and the saved ID commit together; finish never replaces an existing instance.
    psql -qc "UPDATE mate.cell c SET instance = df.start(mate.cell_graph(c, '$2'),
                 format('mate/%s/%s/%s', run_id, board, variant))
              WHERE run_id = $run AND board = $1 AND instance IS NULL"
}

action=${1:-}
case $action in
    new|demo)
        max=$(($(wc -l < data/boards.csv) - 1))
        boards=${2:-$max}
        positive "$boards" && ((boards <= max)) || die "Choose 1..$max boards"
        [[ $action != demo ]] || ((boards >= 2)) || die 'The restart demo needs at least two boards'
        run=$(psql -qAt -v boards="$boards" -f sql/new-run.sql)
        if [[ $action == new ]]; then echo "$run"; exit; fi
        ;;
    finish|score)
        run=${2:-}
        positive "$run" || die 'Pass the numeric run ID printed by new'
        boards=$(psql -Atqc "SELECT count(DISTINCT board) FROM mate.cell WHERE run_id = $run")
        ((boards > 0)) || die "No cells for run $run"
        ;;
    *) die 'Usage: run.sh new [boards] | demo [boards] | finish RUN | score RUN' ;;
esac

score() { psql -v run="$run" -f sql/scorecard.sql; }
if [[ $action == score ]]; then score; exit; fi

if [[ $action == demo ]]; then
    source scripts/restart-check.sh
    mid=$((boards / 2))
fi
for ((i=1; i<=boards; i++)); do
    if [[ $action == demo && $i == "$mid" ]]; then
        launch_pair "$i" 'before grade'
        launch_pair "$((i+1))" 'before request'
        restart_at_checkpoint
    else
        launch_pair "$i" ''
    fi
    states=$(psql -Atqc "SELECT df.await_instance(instance, 90)
                          FROM mate.cell WHERE run_id = $run AND board = $i")
    while read -r state; do
        case $state in
            completed) ;;
            failed|cancelled) echo "Run $run board $i: $state; see df.result(instance)" >&2 ;;
            *) die "Run $run board $i is not terminal: $state" ;;
        esac
    done <<< "$states"
done
score
if [[ $action == demo ]]; then verify_recovery; fi
