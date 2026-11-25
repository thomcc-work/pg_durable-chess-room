-- Run as mate_app on the applet cluster; no workflow is started.
BEGIN;
DO $test$
DECLARE
    run_key bigint;
    cell_key bigint;
    test record;
    got mate.cell;
BEGIN
    INSERT INTO mate.run(provider, deployment, settings)
    VALUES ('fixture', 'grader-test', '{}') RETURNING id INTO run_key;
    INSERT INTO mate.cell(run_id, board, title, fen, mates, variant, prompt)
    VALUES (run_key, 1, 'Rook underpromotion', 'k7/2P5/1K6/8/8/8/8/8 w - - 0 1',
            ARRAY['c7c8q','c7c8r'], 'A', 'grader test') RETURNING id INTO cell_key;

    FOR test IN SELECT * FROM (VALUES
        (200, 'text', '{"choices":[{"message":{"content":" c7c8r\n"}}]}', 'mate', 'c7c8r'),
        (200, 'text', '{"choices":[{"message":{"content":"c7c8b"}}]}', 'miss', 'c7c8b'),
        (200, 'text', '{"choices":[{"message":{"content":"c8=Q#"}}]}', 'malformed', 'c8=Q#'),
        (429, 'text', 'not even JSON', 'provider_error', NULL),
        (200, 'text', 'not JSON', 'response_error', NULL),
        (200, 'text', '{"choices":[]}', 'response_error', NULL),
        (200, 'text', '{"choices":[{"message":{"content":42}}]}', 'response_error', NULL),
        (200, 'base64', 'Y2hlc3M=', 'response_error', NULL)
    ) AS cases(status, encoding, body, verdict, answer) LOOP
        UPDATE mate.cell SET http_status = test.status, encoding = test.encoding,
                             body = test.body WHERE id = cell_key;
        PERFORM mate.grade_cell(cell_key);
        SELECT * INTO STRICT got FROM mate.cell WHERE id = cell_key;
        IF (got.verdict, got.answer) IS DISTINCT FROM (test.verdict, test.answer) THEN
            RAISE EXCEPTION 'HTTP % body %: expected (%, %), got (%, %)',
                test.status, test.body, test.verdict, test.answer, got.verdict, got.answer;
        END IF;
    END LOOP;
END
$test$;
ROLLBACK;
