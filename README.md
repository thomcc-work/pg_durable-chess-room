# Mate in One

Compare two prompts on the same chess position: which one finds a mate, and
which merely gives check? The experiment runs on a disposable local PostgreSQL
cluster with pg_durable. No shared database is needed.

## Start a private cluster

Use Linux, Bash, and a PostgreSQL 17 installation with pg_durable 0.2.9 or
newer installed. As a non-root user, from this checkout:

```bash
# Set PG_CONFIG if the desired installation is not first on PATH.
./scripts/cluster.sh init
./scripts/cluster.sh psql -c "SELECT df.start('SELECT 1', 'hello-mate')"
./scripts/cluster.sh psql -c "SELECT * FROM df.list_instances()"
```

`init` refuses to overwrite an existing `.mate/`. The server accepts no TCP
connections; its socket, data, and log are inside that private directory.
The app submits workflows as `mate_app`, not `postgres`. Use
`./scripts/cluster.sh stop` when done and `./scripts/cluster.sh start` to
reopen the same data. To discard it, stop the cluster first, then remove this
checkout's `.mate/` directory.
