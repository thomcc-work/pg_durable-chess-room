#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
psql() { ./scripts/cluster.sh psql "$@"; }
die() { echo "$*" >&2; exit 1; }
positive() { [[ $1 =~ ^[1-9][0-9]*$ ]]; }

case ${1:-} in
    new)
        max=$(($(wc -l < data/boards.csv) - 1))
        boards=${2:-$max}
        positive "$boards" && ((boards <= max)) || die "Choose 1..$max boards"
        psql -qAt -v boards="$boards" -f sql/new-run.sql
        ;;
    finish|score)
        run=${2:-}
        positive "$run" || die 'Pass the numeric run ID printed by new'
        boards=$(psql -Atqc "SELECT count(DISTINCT board) FROM mate.cell WHERE run_id = $run")
        ((boards > 0)) || die "No cells for run $run"
        if [[ $1 == finish ]]; then
            for ((i=1; i<=boards; i++)); do
                # The graph and its ID commit together. Reopening a run only launches untouched cells.
                psql -qc "UPDATE mate.cell c SET instance = df.start(mate.cell_graph(c),
                             format('mate/%s/%s/%s', run_id, board, variant))
                          WHERE run_id = $run AND board = $i AND instance IS NULL"
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
        fi
        psql -v run="$run" -f sql/scorecard.sql
        ;;
    *) die 'Usage: run.sh new [boards] | finish RUN | score RUN' ;;
esac
