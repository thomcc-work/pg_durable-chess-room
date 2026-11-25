\pset null '-'
SELECT id AS run, provider, deployment, settings FROM mate.run WHERE id = :run;

WITH cells AS MATERIALIZED (
    SELECT * FROM mate.results WHERE run_id = :run
)
SELECT a.board, a.title, a.answer AS "A answer",
       CASE WHEN a.state = 'provider_error' THEN 'HTTP ' || a.http_status ELSE a.state END AS "A verdict",
       b.answer AS "B answer",
       CASE WHEN b.state = 'provider_error' THEN 'HTTP ' || b.http_status ELSE b.state END AS "B verdict",
       CASE WHEN a.state = 'miss' AND b.state = 'mate' THEN 'B gain'
            WHEN a.state = 'mate' AND b.state = 'miss' THEN 'B regression'
            WHEN a.state IN ('mate','miss') AND a.state = b.state THEN 'same'
            WHEN a.state IN ('pending','recorded') OR b.state IN ('pending','recorded') THEN 'unfinished'
            ELSE 'needs attention' END AS comparison
FROM cells a JOIN cells b USING (board)
WHERE a.variant = 'A' AND b.variant = 'B' ORDER BY a.board;
