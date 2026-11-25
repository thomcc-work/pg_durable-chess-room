BEGIN;
CREATE TEMP TABLE seeds (
    board int PRIMARY KEY, title text, fen text, mates text,
    a_status int, a_text text, b_status int, b_text text
) ON COMMIT DROP;
\copy seeds FROM 'data/boards.csv' WITH (FORMAT csv, HEADER true)

INSERT INTO mate.run(provider, deployment, settings)
VALUES ('fixture', 'canned-v1', '{"temperature":0,"max_tokens":32,"n":1}')
RETURNING id AS run \gset

INSERT INTO mate.cell(run_id, board, title, fen, mates, variant, prompt, fixture)
SELECT :run, board, title, fen, string_to_array(mates, ' '), v.variant,
       concat('Find mate in one for the side to move. ', v.hint,
              'Return exactly one move in lowercase UCI coordinate notation, ',
              'with a promotion suffix if needed. No other text.', E'\nFEN: ', fen),
       jsonb_build_object('status', v.status, 'body', (CASE WHEN v.status = 200
           THEN jsonb_build_object('choices', jsonb_build_array(
                    jsonb_build_object('message', jsonb_build_object('content', v.response))))
           ELSE jsonb_build_object('error', jsonb_build_object('message', v.response)) END)::text)
FROM seeds CROSS JOIN LATERAL (VALUES
    ('A', '', a_status, a_text),
    ('B', 'Before choosing, check that the opponent has no legal reply. ', b_status, b_text)
) v(variant, hint, status, response)
WHERE board <= :boards ORDER BY board, variant;
COMMIT;
\echo :run
