BEGIN;
CREATE TABLE mate.run (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    provider text NOT NULL,
    deployment text NOT NULL,
    settings jsonb NOT NULL
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
    fixture jsonb NOT NULL,
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

CREATE FUNCTION mate.fixture_request(cell_id bigint)
RETURNS TABLE(status integer, encoding text, body text) LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO mate.fixture_attempt(cell_id) VALUES ($1);
    RETURN QUERY SELECT (fixture->>'status')::integer, 'text', fixture->>'body'
                 FROM mate.cell WHERE id = $1;
END
$$;

CREATE FUNCTION mate.grade_cell(cell_id bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    c mate.cell;
    content jsonb;
    move text;
    outcome text;
BEGIN
    SELECT * INTO STRICT c FROM mate.cell WHERE id = cell_id;
    IF c.http_status IS NULL THEN
        RAISE EXCEPTION 'No retained response for cell %', cell_id;
    ELSIF c.http_status NOT BETWEEN 200 AND 299 THEN
        outcome := 'provider_error';
    ELSIF c.encoding <> 'text' OR NOT pg_input_is_valid(c.body, 'jsonb') THEN
        outcome := 'response_error';
    ELSE
        content := c.body::jsonb #> '{choices,0,message,content}';
        IF jsonb_typeof(content) IS DISTINCT FROM 'string' THEN
            outcome := 'response_error';
        ELSE
            move := btrim(content #>> '{}', E' \t\r\n');
            outcome := CASE WHEN move !~ '^[a-h][1-8][a-h][1-8][qrbn]?$' THEN 'malformed'
                            WHEN move = ANY(c.mates) THEN 'mate'
                            ELSE 'miss' END;
        END IF;
    END IF;
    UPDATE mate.cell SET answer = move, verdict = outcome WHERE id = cell_id;
END
$$;

CREATE FUNCTION mate.cell_graph(c mate.cell, pause_at text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE
    capture text := (format('SELECT * FROM mate.fixture_request(%s)', c.id) |=> 'reply')
        ~> format('UPDATE mate.cell SET http_status = $reply.status, encoding = $reply.encoding,
                       body = $reply.body WHERE id = %s', c.id);
BEGIN
    CASE pause_at
        WHEN 'before request' THEN capture := df.sleep(15) ~> capture;
        WHEN 'before grade' THEN capture := capture ~> df.sleep(15);
        WHEN '' THEN NULL;
        ELSE RAISE EXCEPTION 'Unknown pause point: %', pause_at;
    END CASE;
    RETURN capture ~> format('SELECT mate.grade_cell(%s)', c.id);
END
$$;

CREATE VIEW mate.results AS
SELECT c.*, coalesce(verdict, CASE
    WHEN instance IS NOT NULL AND df.status(instance) IN ('failed','cancelled') THEN 'workflow_error'
    WHEN http_status IS NOT NULL THEN 'recorded'
    ELSE 'pending' END) AS state
FROM mate.cell c;
COMMIT;
