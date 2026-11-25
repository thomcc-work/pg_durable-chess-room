# The Chess Room

Play White against Stockfish. Make a move, restart Postgres before Black
answers, and come back to the same board. Even if the browser resends your
move, it appears on the scoresheet only once.

This is the playable version of a durable chess game. There is also a [Chess Room prompt evaluator](EVALUATOR.md) for comparing two prompts on a dozen positions; it does not need Stockfish.

## Start a private cluster

Use Linux, uv, Python 3.11+, and PostgreSQL 17 with pg_durable 0.2.9 or
newer installed. Run these commands as a non-root user from this checkout.
`pg_config` on `PATH` selects the installation unless you set `PG_CONFIG`.
On the hackathon host, use:

```sh
export PG_CONFIG="$HOME/.pgrx/17.11/pgrx-install/bin/pg_config"
```

On a fresh checkout, run `uv run -m chess_room init`. If you already have a
stopped `.chess-room/` cluster, run `uv run -m chess_room start` instead.
`init` creates a new cluster; it does not import earlier installations or
overwrite saved data.
If setup is interrupted after the server is initialized, run `uv run -m
chess_room start` to finish it, even if PostgreSQL is already running. Do
not copy or move an initialized data directory to control it from a second
checkout: create a separate cluster there.
The server accepts no TCP connections and keeps its Unix socket, log and
data in this checkout's private `.chess-room/` directory.

## Play

Install Stockfish (e.g. the Debian `stockfish` package) or point `STOCKFISH`
at its executable. The hackathon checkout already has a private copy.

```sh
uv run -m chess_room play
```

Open **[the local board](http://127.0.0.1:8765/)**, choose **New game →
Play White**, select a piece, then a highlighted destination. You can also
type `e2e4` or use the arrow keys and Enter on the board. Start from the
opening for a full game, or try **Rook underpromotion** for a one-move
finish. The game checks moves with python-chess; its SVG renderer draws
the pieces and board. Black's replies come from the actual Stockfish
process over UCI, not fixtures or a cloud endpoint.

Each game has a bookmarkable URL. Select a move on the scoresheet to review
that position, **Return to live board** to keep playing, or **Save PGN**
to take the game elsewhere. Games are untimed. Checkmate, stalemate,
insufficient material, automatic repetition/move-count draws, and resignation
end play. There are no accounts: this room is for a trusted local machine,
not a public multiplayer server.

If the response to **Play White** is lost, retry from the same dialog to
open the game already created. An API client should likewise send a
`request` UUID with `POST /api/games` and reuse it only for that creation.

## Restart in the middle of a turn

1. In a new game, expand **Durable turn receipt**, choose **Hold engine
   reply**, then play `e2e4`. The scoresheet shows `1. e4`. The receipt
   shows the workflow ID, board position in FEN, and White's request ID.
2. In another terminal run `uv run -m chess_room restart`. Only this applet's
   cluster restarts. Reload the same game. The three receipt fields and
   the scoresheet should be unchanged.
3. Choose **Resend last move**. It acknowledges the duplicate without
   adding a ply. Choose **Resume engine**: Black replies and it's your
   turn again.

`uv run -m chess_room game-demo` runs the same check automatically with a new game,
even while the room is open. It verifies that the postmaster really changed,
retries `e4` both before and after Black's reply, plays a second full turn,
and leaves the board available in **Saved games**. In the browser test,
workflow `2a5adcfb` held at `1. e4 e5 2. Nf3`, stayed at three plies after
the restart and retry, then continued `2...Nc6`.

### What is durable?

There is one pg_durable workflow per game. It waits for a `turn` signal
and releases a **committed** move to the engine worker. The signal is a
wake-up, not the move itself: if the signal arrives too early the worker
can send it again. Python validates the move and writes its request ID,
history entry and new position in one transaction. A stale tab can't make
a different move against an old position.

Stockfish searches outside the database. A crash can repeat that search;
its reply can commit only for the same game, phase and ply. The room
reconnects after a database restart and picks up outstanding turns.
No server's HTTP policy has to be relaxed for the engine.

Stop the room with **Ctrl-C**, then use `uv run -m chess_room stop` to stop
Postgres without deleting anything. To discard all applet data, stop
both first and remove only this checkout's `.chess-room/` directory.

## Checks

```sh
uv run python -m unittest discover -s tests
node --test tests/board_ui.test.cjs  # browser-event regressions, no live service needed
# Requires a running applet cluster; creates test games. Run without the room worker.
uv run python -m unittest discover -s tests -p '*_integration.py'
```

The opt-in tests cover concurrent retries, promotion, automatic draws,
PGN export and a search finishing after resignation. Use `game-demo`
for the real engine and actual restart.
