# VAST Database (VAST DB)

Builds on `SKILL.md` (connecting, finding the version, reading the cluster's spec and
the KB). The helper used below is `scripts/vast_api.py`.

## Mental model

| VAST DB term | What it is on the cluster | Notes |
|---|---|---|
| **Database** | A **view** (Element Store path) with the `DATABASE` protocol and an S3 bucket name | The database name *is* the bucket name. Naming rules = S3 bucket names. |
| **Schema** | A container inside the database; can be nested | Naming rules = S3 object names. |
| **Table** | Columnar rows stored in the Element Store | Columns are Apache Arrow types. |
| Projection | A semi-sorted copy of a subset of a table's columns | Speeds up filters on its sorted columns. |
| Snapshot | An Element Store snapshot of the database's path | Read tables "as of" the snapshot. |

Data access never goes through VMS: clients (SDK, Trino, Spark) speak a tabular API over the
**S3 endpoint on the CNodes' virtual IPs**, authenticated with an **S3 access key pair**. VMS
(`https://<VMS>/api/...`) manages the view, the users and keys, and can list and peek at
databases, schemas, tables and rows for administration.

Order of creation: VIP pool (reachable from clients) → user with S3 keys (+ allowed to create
buckets) → identity policy with tabular actions → S3-native view policy → DATABASE view
(the database) with that user as bucket owner → schema → table → data.

KB entry points (5.5): "VAST Database" `https://kb.vastdata.com/documentation/docs/vast-database-55.md`,
"Configuring the VAST Cluster for Database Access"
`https://kb.vastdata.com/documentation/docs/configuring-the-vast-cluster-for-database-access-55.md`.
For another release: `vast_api.py kb search 'VAST Database' --version X.Y`.

## Before anything: check this cluster

```bash
H=scripts/vast_api.py
python3 $H version                                   # release decides API + SDK features
python3 $H spec paths 'schemas|tables|columns|projection|vastdb|bigcatalog'
python3 $H spec model View | grep -iE 'protocol|bucket|policy'   # DATABASE in protocols enum?
pip show vastdb                                      # SDK version on the client
```

The SDK README states the minimum cluster release it supports (2.0.14.1: VAST `5.0.0-sp10` or
later; Python 3.10-3.13). Method names below are from vastdb **2.0.14.1**; if the user's
version differs, check `help(vastdb.table.Table)` or the SDK's CHANGELOG before using one.

## Workflow 1: prepare the cluster (read, plan, ask, create)

KB: "Configuring the VAST Cluster for Database Access" and "Managing Permissions for Accessing
VAST Tabular Databases" (`.../managing-permissions-for-accessing-vast-tabular-databases-55.md`).

1. **Take stock (read-only)**:
   ```bash
   python3 $H get tenants fields=id,name
   python3 $H get vippools fields=id,name,role,ip_ranges,tenant_id
   python3 $H get viewpolicies fields=id,name,flavor,tenant_id
   python3 $H get views fields=id,path,bucket,protocols,policy_id,tenant_id,bucket_owner
   ```
   A view whose `protocols` contains `DATABASE` is an existing database.
2. **VIP pool**: clients connect to CNode VIPs, not to VMS. A pool with the `PROTOCOLS` role
   that the client network can route to is required; the KB recommends a dedicated pool for DB
   workloads. DNS for the pool (VAST DNS) is what the SDK README assumes. See `references/tenants-network.md`.
3. **Database owner user**: a local (or provider) user in the tenant with *allow create bucket*
   and an enabled S3 access key pair. See `references/identity-access.md`. The secret key is shown once:
   ask the user where to keep it; never write it into a committed file.
4. **Permissions**: the SDK README requires a "tabular identity policy with the proper
   permissions": an identity policy (VMS `/s3policies/` on 5.5) attached to the user, with
   actions such as `s3:TabularListSchemas`, `s3:TabularListTables`, `s3:TabularQueryData`,
   `s3:TabularInsertRows`, `s3:TabularCreateTable`... or `s3:Tabular*` for full access.
   Resources are `"<db-bucket>"` (bucket-level, e.g. list schemas) and `"<db-bucket>/*"` or
   `"<db-bucket>/<schema>/*"` (objects). The KB page lists every action and seven example
   policies (read-only, per-schema, delete rows...). Users must also be allowed `ListBuckets`
   in the view policy to see databases.
5. **View policy**: the policy must have the **S3 native** security flavor (`flavor` on 5.5:
   `S3_NATIVE`). Otherwise the view create fails with *"A view where the Database is in the
   list of protocols can only have a view policy where the security flavor is S3 native."*
   *(seen on 5.5.3)*.
6. **Plan, then ask once**: show the user what exists and the exact request(s). A database
   view on 5.5 (check `spec model View`):
   ```bash
   python3 $H call POST /views/ --data '{"path": "/<db-bucket>", "create_dir": true,
     "protocols": ["S3", "DATABASE"], "bucket": "<db-bucket>", "bucket_owner": "<owner-user>",
     "policy_id": <s3-native-policy-id>, "tenant_id": <tenant-id>}'      # dry run
   ```
   `path`, `policy_id`, `protocols`, `bucket`, `bucket_owner`, `tenant_id` are in the 5.5.3
   `View` model; `create_dir` is not listed there but is what the Terraform provider
   (`vastdata_view`) and vcli `--create-dir` send, so the call fails if the directory doesn't
   exist and it is left out. Re-run with `--yes` only after the user agrees. (The KB's vcli equivalent:
   `view create --path /vast-db --protocols S3,DATABASE --create-dir --bucket vast-db --bucket-owner <owner> --policy-id <id>`.)
7. **Check it**: `python3 $H get views bucket=<db-bucket>`, then from the client run the SDK
   connectivity test in Workflow 2 (list schemas). Fix access before creating tables.

Changing protocols or the policy on a view that is in use interrupts its clients; deleting a
database view deletes **all its tables and data**. Warn the user and get an explicit yes.

## Workflow 2: connect and work with the vastdb SDK

Full cookbook (all verified against the 2.0.14.1 source): `references/database/sdk.md`.

```python
import pyarrow as pa, vastdb
from ibis import _

session = vastdb.connect(endpoint="http://<db-vip-pool-dns-name>",   # or https://
                         access="<access-key>", secret="<secret-key>",
                         timeout=(5, 300))           # default is no timeout at all
with session.transaction() as tx:                    # every operation runs in a transaction
    bucket = tx.bucket("<db-bucket>")
    print([s.name for s in bucket.schemas()])        # connectivity + permission check
    schema = bucket.create_schema("<schema>", fail_if_exists=False)
    cols = pa.schema([("id", pa.int64()), ("name", pa.utf8()), ("ts", pa.timestamp("us"))])
    table = schema.create_table("<table>", cols, fail_if_exists=False)
    table.insert(pa.table(schema=cols, data=[[1, 2], ["a", "b"], [None, None]]))
    reader = table.select(columns=["id", "name"], predicate=(_.id > 1))
    print(reader.read_all())                         # read inside the open transaction
# leaving the block commits; an exception rolls back
```

- `connect()` falls back to `AWS_S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.
- **Endpoint**: the S3 address of the DB VIP pool (its DNS name, or one VIP). Not the VMS
  address. KB ("VAST DB Python SDK 2.0.14.1 and VAST 5.4.x") says S3 is served on 80 (HTTP) and
  443 (HTTPS), so no port is normally needed; a cluster may be set up differently, so use
  the address and scheme the user's S3 clients already use. VMS lists the DB access VIPs at
  `GET /vastdb/vips/` (5.5 API; returns `vip` and `port` per entry).
- The returned `RecordBatchReader` streams from the cluster: consume it **before** the
  transaction closes.

## Workflow 3: query engines

`references/database/engines.md`: Trino (VAST image `vastdataorg/trino-vast`, `vast.properties`,
version matrix), Spark (`spark.ndb.*` settings, connector from `vast-data/vast-db-connectors`
releases), DuckDB on the SDK's Arrow stream, ADBC (`pip install "vastdb[adbc]"`). Names in SQL:
Trino `vast."<db-bucket>/<schema>".<table>`; Spark `ndb.\`<db-bucket>\`.<schema>.<table>`.

## Workflow 4: inspect DB objects from VMS (admin, read-only)

`references/database/vms-api.md` has each endpoint, its required parameters and responses as seen on
5.5.3. Summary (5.5 API; the spec lists these paths but not their parameters, so the
parameter names below come from live calls and the cluster's `/docs/` page):

| Need | Call |
|---|---|
| Schemas of a database | `get schemas database_name=<db-bucket> tenant_id=<id>` |
| Tables (with `num_rows`, `size`, sorting state) | `get tables database_name=... schema_name=... tenant_id=...` |
| One table's detail | `get tables/show/ database_name=... schema_name=... name=<table> tenant_id=...` |
| Columns and types | `get vastdbtable/columns/ database_name=... schema_name=... table_name=... tenant_id=...` |
| Row/column counts | `get vastdbtable/stats/ ...same...` |
| Peek at rows | `get vastdbtable/query_data/ ...same... filters='{}' fields=c1,c2 limit=20` |
| Projections of a table | `get projections database_name=... schema_name=... table_name=... tenant_id=...` |
| VAST Catalog config / rows | `get bigcatalogconfig`, `bigcatalogconfig/query_data/` (see reference) |

VMS also has POST/PATCH/DELETE on `/schemas/`, `/tables/`, `/columns/`, `/projections/`
(create, add columns, rename, delete). Prefer the SDK or SQL for data changes; if you do use VMS,
check the body on the cluster's `https://<VMS>/docs/` page first and dry-run with the helper.

## Features to know (details in `references/database/features.md`)

- **Transactions**: ACID; each `with session.transaction()` block is one transaction.
- **Pushdown**: predicates `AND` of per-column `OR`s of `< <= == > >= !=`, `isin`, `isnull`,
  `startswith`, `contains`; projection = only the columns you name.
- **Update / delete**: by internal row id (`$row_id`, from `select(..., internal_row_id=True)`).
- **Import Parquet** already on the cluster's S3: `table.import_files([...])`,
  `vastdb.util.create_table_from_files(...)`; CNodes read the files, nothing passes the client.
- **Sorted tables** (`sorting_key` at create, or `table.add_sorting_key`), **projections**
  (`create_projection`), **partitioning** (Trino/Spark): each one is permanent and they exclude
  each other in ways listed in the reference. Ask before enabling.
- **Snapshots**: `bucket.snapshots()` / `bucket.snapshot(name)` read a database as of a
  snapshot of its path (snapshots themselves: `references/data-protection.md`).
- **VAST Catalog** (`tx.catalog()`) and **audit log** (`tx.audit_log()`) are built-in tables.
- **Row/column security**, **vector search**, **user-defined row ids** (`vastdb_rowid`).

## Performance (KB "VAST DB Python SDK 2.0.14.1 and VAST 5.4.x")

- Name the columns, push filters into `predicate`, iterate the reader batch by batch.
- Large scans: `QueryConfig(data_endpoints=[...VIPs or the pool name repeated N times], num_splits=N)`;
  without `data_endpoints` only the CNode behind `endpoint` serves the query, and the worker
  count is `min(len(data_endpoints), num_splits)`.
- Don't fan out small or `limit_rows` queries; one endpoint is faster.
- Insert big Arrow batches, not single rows; inserts/updates/deletes always use the session endpoint.
- Repeated jobs: `TableMetadata` + `tx.table_from_metadata()` avoids metadata round trips.
- Sorted tables: insert in large batches; sorting works on 512K-row chunks (>1M rows to pay off).

## Limits (KB "Limitations"; re-check for the user's release)

Max databases 16384 (counted in views); tables 1 billion per DBox; rows 2^48; columns 31936;
**cell 126KB**; snapshots 1019. VAST DB pushes down filters and projections; joins and complex
SQL run in the query engine (Trino/Spark), not on the cluster.

## Pitfalls

| Symptom / error | Cause | Fix |
|---|---|---|
| View create: "A view where the Database is in the list of protocols can only have a view policy where the security flavor is S3 native." *(5.5.3)* | Policy is NFS/SMB/mixed | Use (or create) an `S3_NATIVE` policy. |
| SDK hangs or times out on connect, though VMS works | Endpoint is the VMS address, or the client can't route to the VIP pool | Point at a DB VIP (pool DNS name); test `curl http(s)://<vip>/` from the client. |
| SDK works for one call then stalls, or works on some workers only | Some VIPs in `data_endpoints`/DNS not reachable from this client | Check every VIP; list only reachable ones. |
| `MissingBucket` for `<db-bucket>` | Wrong name, wrong tenant's keys, no `ListBuckets`/tabular permission, or not a DATABASE view | `get views bucket=<db-bucket>`; check the keys' tenant and the identity policy. |
| `MissingBucket: vast-big-catalog-bucket` | Catalog opened with `tx.bucket(...)` | Use `tx.catalog()` (KB "Querying the VAST Catalog"). |
| 403 / AccessDenied on a tabular action | Identity policy lacks that `s3:Tabular*` action/resource | Add the action for `<db-bucket>` and `<db-bucket>/*`. |
| HTTPS with listed VIP addresses fails TLS | Certificate has the DNS name, not the IPs | Repeat the pool DNS name instead, or VIPs over HTTP (KB). |
| VMS `get schemas` → 404 "could not find @s3_bucket_name=<db>" *(5.5.3)* | Database is in another tenant | Add `tenant_id=<id>`. |
| VMS `tables` → 404 "Getting table list failed ... failed to fetch schema element" *(5.5.3)* | Schema doesn't exist | List schemas first. |
| VMS `query_data` → 404 "Getting column list failed..." *(5.5.3)* | Table doesn't exist | `get tables ...` first. |
| VMS `query_data` → 400 "fields - field required" *(5.5.3)* | `fields` is mandatory | Pass `fields=c1,c2` (comma-separated, not a JSON list). |
| Reader errors after the `with` block | Transaction closed while streaming | Consume (or `read_all()`) inside the block. |
| `NotImplementedError` from `select` | Predicate outside the pushdown subset | Push down what's supported, filter the rest client-side. |
| Sort column gives poor pruning | Strings like `YYYY-MM-..`: only the first 8 bytes are used | Use date/timestamp types. |

## Related areas

`SKILL.md` (foundation), `references/views-protocols.md` (views, view policies), `references/identity-access.md`
(users, S3 keys, identity policies), `references/tenants-network.md` (VIP pools, DNS),
`references/event-broker.md` (Kafka topics are DB tables), `references/data-protection.md` (snapshots,
replication), `references/dataengine.md` (functions writing to tables).

Verified: VAST 5.5.3 — spec read (paths, View/EventNotification models), live read-only VMS calls
(schemas, tables, tables/show, vastdbtable columns/stats/query_data with filters, vastdb/vips,
bigcatalogconfig) and their error texts; KB 5.5 pages read; SDK calls taken from vastdb 2.0.14.1
source (not run against the cluster).
