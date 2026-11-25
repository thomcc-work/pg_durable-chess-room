# The Chess Room: prompt evaluator

Which positions does B solve that A misses, and where does it regress?
Python freezes both prompts, accepted mating moves, deployment and settings
under one run ID. One pg_durable workflow per cell records the reply; Python
then grades it and puts both answers on the same row.

[Start the private cluster](README.md#start-a-private-cluster), then try two boards:

```sh
uv run -m chess_room new 2       # prints the run ID
uv run -m chess_room finish 1    # use that ID; 1 on a fresh cluster
uv run -m chess_room score 1     # revisit without launching another workflow
```

These are **fixtures, not model measurements**. On board 1, A's `a2a8`
gives check but allows `h8h7`. B's `a2h2` covers the h-file and the white
king covers g7 and g8. On board 2 the result goes the other way.
Omit `2` from `new` for all twelve boards. Board 5 accepts either a queen
or rook promotion; board 8 has a plausible answer in the wrong notation;
board 9 has a canned HTTP 429. Neither a format error nor a rate limit
counts as a missed mate.

## Interrupt the experiment

```sh
uv run -m chess_room demo
```

The driver restarts **only this checkout's Postgres** after 12 of 24
responses are on disk. Board 6 has two answers waiting for grading; board
7 has two workflows waiting to make their first request. A 15-second
durable timer at each boundary makes the interruption visible.

The [sample scorecard](SCORECARD.md) shows the result and the request
receipts at the boundary. The command compares each earlier fixture attempt
ID, workflow ID and response digest, verifies the remaining requests arrived
after restart, and prints the completed comparison. If the driver itself
exits, `uv run -m chess_room finish RUN_ID` continues from the saved instances.
This is evidence about *recorded* replies, not exactly-once HTTP billing.
A recorded reply can still be graded after pg_durable expires its workflow
history. Observed workflow failures stay on the scorecard. For an existing
cluster, `uv run -m chess_room start` applies the schema update without
replacing data.

`new` and `demo` never send HTTP. To send the same frozen prompts to an
**already-authorized** Azure deployment, follow the [live run instructions](LIVE.md).
A non-2xx response, an invalid chat envelope, an unparseable answer and a
coordinate move outside the accepted set all get different verdicts.

The [board key](data/boards.csv) contains every mating move, not one preferred
solution. Recompute it with `uv run scripts/check_boards.py`, or use
`python3 scripts/check_boards.py` with `chess==1.11.2` installed. The evaluator
uses the stored keys, not a running chess engine or another model.
