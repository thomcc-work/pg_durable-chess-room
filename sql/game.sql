CREATE TABLE IF NOT EXISTS chess_room.game (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instance text UNIQUE,
    title text NOT NULL,
    engine text NOT NULL,
    engine_paused boolean NOT NULL DEFAULT false,
    start_fen text NOT NULL,
    fen text NOT NULL,
    ply integer NOT NULL DEFAULT 0 CHECK (ply >= 0),
    phase text NOT NULL DEFAULT 'human'
        CHECK (phase IN ('human','submitted','engine','closing','finished')),
    result text NOT NULL DEFAULT '*' CHECK (result IN ('*','1-0','0-1','1/2-1/2')),
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((result <> '*') = (phase IN ('closing','finished')))
);

CREATE TABLE IF NOT EXISTS chess_room.game_move (
    game_id bigint NOT NULL REFERENCES chess_room.game,
    ply integer NOT NULL CHECK (ply > 0),
    actor text NOT NULL CHECK (actor IN ('human','engine')),
    uci text NOT NULL,
    san text NOT NULL,
    request_id uuid,
    played_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (game_id, ply),
    UNIQUE (game_id, request_id),
    CHECK ((actor = 'human') = (request_id IS NOT NULL))
);
