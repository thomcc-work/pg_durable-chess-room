BEGIN;
CREATE TABLE mate.run (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    provider text NOT NULL CHECK (provider IN ('fixture', 'azure')),
    deployment text NOT NULL,
    settings jsonb NOT NULL,
    base_url text,
    api_version text,
    CHECK ((provider = 'azure') = (base_url IS NOT NULL AND api_version IS NOT NULL))
);

CREATE TABLE mate.cell (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id bigint NOT NULL REFERENCES mate.run,
    board integer NOT NULL,
    title text NOT NULL,
    fen text NOT NULL,
    mates text[] NOT NULL CHECK (cardinality(mates) > 0),
    variant text NOT NULL CHECK (variant IN ('A', 'B')),
    prompt text NOT NULL,
    fixture jsonb,
    instance text UNIQUE,
    http_status integer,
    encoding text,
    body text,
    answer text,
    verdict text,
    UNIQUE (run_id, board, variant)
);

-- A second invocation must leave a second row, even for an identical answer.
CREATE TABLE mate.fixture_attempt (
    attempt bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cell_id bigint NOT NULL REFERENCES mate.cell,
    received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

COMMIT;
