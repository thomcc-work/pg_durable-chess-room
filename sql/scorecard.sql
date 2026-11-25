\pset null '-'
SELECT id AS run, provider, deployment, settings FROM mate.run WHERE id = :run;

WITH cells AS MATERIALIZED (
    SELECT r.*, CASE state
        WHEN 'provider_error' THEN 'HTTP ' || http_status
        WHEN 'workflow_error' THEN concat('workflow_error: ', (SELECT output FROM df.instance_info(r.instance)))
        ELSE state END AS display_verdict
    FROM mate.results r WHERE run_id = :run
)
SELECT a.board, a.title, a.answer AS "A answer", a.display_verdict AS "A verdict",
       b.answer AS "B answer", b.display_verdict AS "B verdict",
       CASE WHEN a.state = 'miss' AND b.state = 'mate' THEN 'B gain'
            WHEN a.state = 'mate' AND b.state = 'miss' THEN 'B regression'
            WHEN a.state IN ('mate','miss') AND a.state = b.state THEN 'same'
            WHEN a.state IN ('pending','recorded') OR b.state IN ('pending','recorded') THEN 'unfinished'
            ELSE 'needs attention' END AS comparison
FROM cells a JOIN cells b USING (board)
WHERE a.variant = 'A' AND b.variant = 'B' ORDER BY a.board;
