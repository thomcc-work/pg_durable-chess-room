# Sourced only by run.sh demo. The fixture logs each request, not just its final result.
early_attempts() {
    psql -Atqc "SELECT c.board, c.variant, c.instance, a.attempt, c.http_status, md5(c.body)
                FROM mate.cell c JOIN mate.fixture_attempt a ON a.cell_id = c.id
                WHERE c.run_id = $run AND c.board <= $mid ORDER BY board, variant, attempt"
}

restart_at_checkpoint() {
    local waiting tick recorded
    for ((tick=0; tick<100; tick++)); do
        waiting=$(psql -Atqc "SELECT count(*) FROM mate.cell c, df.instance_nodes(c.instance) n
                              WHERE c.run_id = $run AND c.board IN ($mid, $mid+1)
                              AND n.node_type = 'SLEEP' AND n.inferred_status = 'running'")
        [[ $waiting == 4 ]] && break
        sleep .2
    done
    [[ $waiting == 4 ]] || die 'Did not observe both pairs at their durable timers; not restarting'
    recorded=$(psql -Atqc "SELECT count(body) FROM mate.cell WHERE run_id = $run")
    ((recorded == 2*mid)) || die "Missed restart window: $recorded recorded responses"
    score
    before=$(early_attempts)
    echo "Run $run: $recorded recorded; board|prompt|instance|fixture attempt|HTTP status|body MD5"
    echo "$before"
    ./scripts/cluster.sh restart
}

verify_recovery() {
    local after valid
    after=$(early_attempts)
    [[ $before == "$after" ]] || die 'Recorded cells changed instance, response or request history'
    valid=$(psql -Atqc "SELECT count(*) = 2*$boards AND bool_and(
                            requests = 1 AND verdict IS NOT NULL AND df.status(instance) = 'completed'
                            AND (board <= $mid OR first_request >= pg_postmaster_start_time()))
                        FROM (SELECT c.*, count(a.attempt) AS requests, min(a.received_at) AS first_request
                              FROM mate.cell c LEFT JOIN mate.fixture_attempt a ON a.cell_id = c.id
                              WHERE c.run_id = $run GROUP BY c.id) receipts")
    [[ $valid == t ]] || die 'Expected one fixture invocation per graded cell, with all later requests after restart'
    echo "Run $run: all $((2*boards)) cells graded. The $((2*mid)) earlier request histories are unchanged;"
    echo "all $((2*(boards-mid))) remaining requests arrived after the new postmaster started."
}
