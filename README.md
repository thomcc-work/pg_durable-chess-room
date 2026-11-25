# Mate in One

Compare two prompts on the same chess position: which one finds a mate, and
which merely gives check? The experiment runs on a disposable local PostgreSQL
cluster with pg_durable. No shared database is needed.

## Start a private cluster

Use Linux, Bash, and a PostgreSQL 17 installation with pg_durable 0.2.9 or
newer installed. As a non-root user, from this checkout:

```bash
# Set PG_CONFIG if the desired installation is not first on PATH.
./scripts/cluster.sh init
./scripts/cluster.sh psql -f sql/schema.sql
run=$(./scripts/run.sh new 2)
./scripts/run.sh finish "$run"
```

`init` refuses to overwrite an existing `.mate/`. The server accepts no TCP
connections; its socket, data, and log are inside that private directory.
The app submits workflows as `mate_app`, not `postgres`. Use
`./scripts/cluster.sh stop` when done and `./scripts/cluster.sh start` to
reopen the same data. To discard it, stop the cluster first, then remove this
checkout's `.mate/` directory.

## Interrupt the experiment

```bash
./scripts/run.sh demo
```

This starts a new twelve-board **fixture** run and restarts **only this
checkout's cluster** after 12 of 24 responses are on disk. Board 6 has two
answers waiting to be graded. Board 7 has two workflows waiting to make
their first request. A 15-second `df.sleep` at each boundary makes the
interruption visible; there is no signal to send or job to recreate.
pg_durable resumes those four instances. The driver submits later boards
one pair at a time, just as it does without an interruption.

See the [sample scorecard and restart evidence](SCORECARD.md). The command
prints the half-finished and final scorecards, compares every
earlier fixture attempt ID, workflow ID and response digest, and checks
that each remaining request arrived after the new server started. If the
driver itself exits, `./scripts/run.sh finish RUN_ID` continues from the
saved instance IDs. This demonstrates recovery of **recorded** answers.
If an actual HTTP request reaches a provider but its reply is lost, a
retry can still incur another charge.

## Read the comparison

These are **fixtures, not model measurements**. On board 1, A returns `a2a8`.
The rook checks along the eighth rank, but the black king can move to h7.
B returns `a2h2`: the rook covers the h-file and the white king on f7 covers
g7 and g8. On board 2 the result goes the other way. Use
`./scripts/run.sh score "$run"` to revisit either comparison.

Omit `2` from `new` for all twelve boards. On board 5 either a queen or a
rook promotion is mate. Board 8 gives A a plausible chess answer in the
wrong notation; board 9 gives B a canned HTTP 429. Neither is a chess miss,
and neither stops board 10 from being evaluated.

`new` freezes both exact prompts, FENs, accepted moves, and canned responses
under a new run ID. `finish` starts one workflow per cell, one pair at a time.
The request is a SQL activity standing in for chat; each invocation appends a
row to `mate.fixture_attempt`. The next activity retains the status, encoding
and body before a separate activity grades the move. A `miss` is a move in
coordinate notation outside the accepted set, not a claim that it was legal.
A bad answer, an invalid chat response and a non-2xx status get distinct verdicts.

The [board key](data/boards.csv) contains **all** mating moves, not one
preferred solution. To verify the key offline with the `chess==1.11.2` Python
package installed, run `python3 scripts/check_boards.py`; alternatively,
`uv run scripts/check_boards.py` installs the pinned checker. Neither Python
nor a chess engine is needed to run the experiment.
