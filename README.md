# Mate in One

Compare two prompts on the same chess position: which one finds a mate, and
which merely gives check? The Python app freezes the inputs, grades the answers,
and prints them side by side. pg_durable runs each request and records its
reply on a disposable local PostgreSQL cluster. No shared database is needed.

## Start a private cluster

Use Linux, uv, Python 3.11+, and a PostgreSQL 17 installation with pg_durable 0.2.9 or
newer installed. On the hackathon host, select that installation first:

```sh
export PG_CONFIG="$HOME/.pgrx/17.11/pgrx-install/bin/pg_config"
```

Elsewhere, `pg_config` on `PATH` is the default. As a non-root user, from
this checkout:

```sh
uv run -m mate init
uv run -m mate new 2       # prints the new run ID
uv run -m mate finish 1    # use the printed ID; 1 on a fresh cluster
```

`init` refuses to overwrite an existing `.mate/`. The server accepts no TCP
connections; its socket, data, and log are inside that private directory.
The app submits workflows as `mate_app`, not `postgres`. Use
`uv run -m mate stop` when done and `uv run -m mate start` to
reopen the same data. To discard it, stop the cluster first, then remove this
checkout's `.mate/` directory.

Already have a cluster from the shell prototype? Use `uv run -m mate start`,
not `init`. The Python client uses the same tables and workflow IDs.

## Interrupt the experiment

```sh
uv run -m mate demo
```

This starts a new twelve-board **fixture** run and restarts **only this
checkout's cluster** after 12 of 24 responses are on disk. Board 6 has two
answers waiting to be graded. Board 7 has two workflows waiting to make
their first request. A 15-second `df.sleep` at each boundary makes the
interruption visible; there is no signal to send or job to recreate.
pg_durable resumes those four instances. Python reconnects, grades their
saved replies, and submits later boards one pair at a time.

See the [sample scorecard and restart evidence](SCORECARD.md). The command
prints the half-finished and final scorecards, compares every
earlier fixture attempt ID, workflow ID and response digest, and checks
that each remaining request arrived after the new server started. If the
driver itself exits, `uv run -m mate finish RUN_ID` continues from the
saved instance IDs. This demonstrates recovery of **recorded** answers.
If an actual HTTP request reaches a provider but its reply is lost, a
retry can still incur another charge.

## Try the original human-versus-engine restart

With the private cluster running, `uv run -m mate game-demo` creates a
separate game against **real Stockfish**. Install the `stockfish` package
(on Debian, `apt install stockfish`), or set `STOCKFISH` to a local UCI
executable. No model credentials are needed. The command records `1. e4`,
waits until the game's workflow releases Black to move, then restarts
Postgres before the engine searches. It resubmits the same command twice
and plays another full turn, checking the move history and workflow ID.
The evaluator does not start or require Stockfish.

## Read the comparison

These are **fixtures, not model measurements**. On board 1, A returns `a2a8`.
The rook checks along the eighth rank, but the black king can move to h7.
B returns `a2h2`: the rook covers the h-file and the white king on f7 covers
g7 and g8. On board 2 the result goes the other way. Use
`uv run -m mate score RUN_ID` to revisit either comparison.

Omit `2` from `new` for all twelve boards. On board 5 either a queen or a
rook promotion is mate. Board 8 gives A a plausible chess answer in the
wrong notation; board 9 gives B a canned HTTP 429. Neither is a chess miss,
and neither stops board 10 from being evaluated.

`new` freezes both exact prompts, FENs, accepted moves, and canned responses
under a new run ID. `finish` starts one workflow per cell, one pair at a time.
In a fixture run, each simulated request appends a row to
`mate.fixture_attempt`. A subsequent workflow step stores the status, encoding
and body. Only then does Python parse the reply and check it against the
frozen answer key. A `miss` is a move in
coordinate notation outside the accepted set, not a claim that it was legal.
A bad answer, an invalid chat response and a non-2xx status get distinct verdicts.

To send the prompts to an **already-authorized** Azure chat deployment,
follow the [live run instructions](LIVE.md). `new` and `demo` never send HTTP.

The [board key](data/boards.csv) contains **all** mating moves, not one
preferred solution. To verify the key offline with the `chess==1.11.2` Python
package installed, run `python3 scripts/check_boards.py`; alternatively,
`uv run scripts/check_boards.py` installs the pinned checker. The experiment
uses the stored answer keys, not an engine, to grade replies.

To test the grader, prompts and comparisons without a database, run
`uv run python -m unittest discover -s tests`.
