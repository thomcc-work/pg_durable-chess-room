# Compare an already-authorized Azure chat deployment

Skip this page for the fixture demo. A live run sends the two prompts and
the FENs to your deployment and can incur charges. Start with one board
(two calls). Use a deployment that accepts Chat Completions API
`2024-10-21`, `temperature: 0`, `n: 1`, and `max_tokens: 32`.

On the **private applet cluster**, use `./scripts/cluster.sh admin` to grant
HTTP access and bind a foreign server to the authorized resource:

```sql
SHOW pg_durable.http_security;  -- leave at restricted
SELECT df.grant_usage('mate_app', include_http => true);
CREATE SERVER mate_chat FOREIGN DATA WRAPPER pg_durable_fdw
    OPTIONS (base_url 'https://YOUR-RESOURCE.openai.azure.com',
             auth_scheme 'header', header_name 'api-key');
GRANT USAGE ON FOREIGN SERVER mate_chat TO mate_app;
```

Use your trusted provisioning process to create **`mate_app`'s own mapping**
on that server with the `header_value` option. For the DDL and rotation
procedure see **Endpoint Credential Catalog** in your installed version's
[`USER_GUIDE.md`](https://github.com/microsoft/pg_durable/blob/main/USER_GUIDE.md#endpoint-credential-catalog).
A `PUBLIC` mapping is not a fallback. Do not put the key in a command line,
workflow, `df.vars`, the run manifest, or this checkout. Mappings keep it out
of the workflow but are plaintext in catalogs, WAL and backups; provisioning
DDL can also enter logs or client history. Use a trusted server owner and a
disposable, protected cluster. No provisioning of an Azure resource, new
login or HTTP policy change is necessary for the fixture demo.

```bash
run=$(./scripts/run.sh new-live YOUR-DEPLOYMENT 1)  # snapshot only; no network
./scripts/cluster.sh psql -c "SELECT provider, base_url, deployment, api_version, settings FROM mate.run WHERE id = $run"
./scripts/cluster.sh psql -c "SELECT variant, prompt FROM mate.cell WHERE run_id = $run"
./scripts/run.sh finish "$run"                      # sends the two requests
```

The workflow uses `df.http(df.endpoint(...))`; pg_durable resolves the
mapping at send time. Keep the server destination and deployment stable
during the run. The manifest records their names and settings, not the
provider's underlying model weights. Later pairs refuse to launch if the
catalog URL no longer matches the snapshot.

A returned 429 is retained as `provider_error` with its body; the app adds
no retry. A timeout, 5xx or missing credential can fail the activity
without a response envelope. Such a cell shows `workflow_error`, not a
chess miss. Inspect it without starting a replacement:

```sql
SELECT board, variant, instance, http_status, body, state,
       CASE WHEN state = 'workflow_error' THEN
           (SELECT output FROM df.instance_info(c.instance)) END AS reason
FROM mate.results c WHERE run_id = 1 ORDER BY board, variant; -- use your run ID
```

The sample scorecard used no live deployment. Separately, we built these
HTTP graphs and exercised an endpoint-catalog failure on the private
cluster; it failed before a request could be sent. Successful network
transport and Azure's response were not tested. The append-only request
history belongs to the SQL fixture, not an HTTP provider's billing log.
