# Mate in One: fixture run 4

PostgreSQL 17.11, pg_durable 0.2.9, 2026-11-25. These are **canned
answers**, not measurements from a model. Both prompts requested one move
in lowercase coordinate notation. B also asked the model to check that
the opponent had no legal reply.

| Board | Position | A answer | A verdict | B answer | B verdict | Comparison |
|---:|---|---|---|---|---|---|
| 1 | Rook on the h-file | `a2a8` | miss | `a2h2` | mate | B gain |
| 2 | Back rank | `e1e8` | mate | `e1e7` | miss | B regression |
| 3 | Black rook on the h-file | `a7a8` | miss | `a7h7` | mate | B gain |
| 4 | Two queen landings | `e6h3` | mate | `e6h6` | mate | same |
| 5 | Rook underpromotion | `c7c8r` | mate | `c7c8q` | mate | same |
| 6 | Smothered knight | `g5h7` | miss | `g5f7` | mate | B gain |
| 7 | Remove the h-pawn | `h1h6` | mate | `h1h6` | mate | same |
| 8 | Black back rank | `Ra1#` | malformed | `a8a1` | mate | needs attention |
| 9 | Queen on the a-file | `h2a2` | mate | — | HTTP 429 | needs attention |
| 10 | Rook behind the pawn | `c7c8` | mate | `c7h7` | miss | B regression |
| 11 | Four queen mates | `g1g7` | mate | `g1h1` | mate | same |
| 12 | Black promotes | `c2c1b` | miss | `c2c1r` | mate | B gain |

On board 1 (`7k/5K2/8/8/8/8/R7/8 w - - 0 1`), both answers give
check. After A's rook goes to a8, Black can play `h8h7`. After B's rook
goes to h2, h7 is covered and the white king covers g7 and g8. There is
no escape. On board 2 the advantage reverses: from e8 the rook checks
along the eighth rank, with Black's own pawns on a7 and b7 blocking
escape. B's rook on e7 doesn't even give check.

## What crossed the restart

The driver stopped only the applet's cluster with 12 of 24 responses
retained. Board 6 was recorded but ungraded; board 7 was submitted but
had made no requests. The same run finished with one fixture attempt per
cell. The earlier twelve attempt histories matched before and after.
At the boundary:

| Board / prompt | Workflow ID | Fixture attempt ID | Request received | Graded |
|---|---|---:|---|---|
| 6 / A | `e14ea7c0` | 43 | before restart | after restart |
| 6 / B | `de5c0cba` | 44 | before restart | after restart |
| 7 / A | `02e8c0cb` | 45 | after restart | after restart |
| 7 / B | `22c8edee` | 46 | after restart | after restart |

The malformed answer and 429 were also fixtures; the run made no HTTP
requests and did not retry the rate limit. Nothing here establishes how
often a real provider bills a request lost in flight. [Replay the demo](README.md#interrupt-the-experiment)
to see the checkpoint and inspect your own attempt IDs.
