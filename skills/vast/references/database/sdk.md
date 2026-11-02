# vastdb Python SDK cookbook

Source: `github.com/vast-data/vastdb_sdk`, version **2.0.14.1** (README, `vastdb/*.py`). Docs:
`https://vastdb-sdk.readthedocs.io/`. Before using a call on another SDK version, check it
exists: `pip show vastdb`, `python -c "import vastdb, inspect; print(inspect.signature(vastdb.table.Table.select))"`,
or the CHANGELOG. Install: `pip install vastdb` (Python 3.10-3.13; extras: `vastdb[adbc]`).
Predicates use Ibis (`from ibis import _`).

## Session and transactions

```python
import vastdb
from vastdb.config import BackoffConfig, QueryConfig, ImportConfig

session = vastdb.connect(
    endpoint="https://<db-vip-pool-dns-name>",   # S3 endpoint on the CNode VIPs, never VMS
    access="<access-key>", secret="<secret-key>", # or env AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
    timeout=(5, 300),                            # (connect, read) seconds, passed to requests
    backoff_config=BackoffConfig(max_tries=3, max_time=60),
    ssl_verify=True,                             # False only if the user accepts it
)
with session.transaction() as tx:   # begins on enter; commits on normal exit, rolls back on exception
    ...
```

Other `connect()` keywords (2.0.14.1): `max_entities_per_page`, `adbc_driver_path`, `end_user`.
`vastdb.version()` returns the SDK version. `tx.txid` is the transaction id.

## Buckets (databases), schemas, tables

```python
bucket = tx.bucket("<db-bucket>")                       # raises if missing / not visible
schema = bucket.create_schema("<schema>", fail_if_exists=False)
schema = bucket.schema("<schema>")                       # fail_if_missing=True by default
for s in bucket.schemas(): print(s.name)
sub = schema.create_schema("<child>")                    # schemas can be nested

import pyarrow as pa
cols = pa.schema([("id", pa.int64()), ("v", pa.float64()), ("tag", pa.utf8())])
table = schema.create_table("<table>", cols, fail_if_exists=False,
                            sorting_key=[],               # column names or indexes to sort by (see features.md)
                            use_external_row_ids_allocation=False)
table = schema.table("<table>")
names = schema.tablenames(); tables = schema.tables()
table.columns(); table.stats; table.get_stats()          # num_rows, size_in_bytes, sorting_*...
table.add_column(pa.schema([("extra", pa.int32())]))
table.drop_column(pa.schema([("extra", pa.int32())]))
table.rename_column("v", "value")
table.rename("<new-name>"); table.drop(); schema.rename("<new>"); schema.drop()
```

`drop()` on a table or schema deletes its data: ask the user first.

Supported Arrow types (docs/types.md): uint8-64, int8-64, string, list, struct, map, bool,
float, double, binary, decimal128, date32, timestamp, time32, time64, null.

## Insert, select, update, delete

```python
from ibis import _
data = pa.table(schema=cols, data=[[1, 2, 3], [0.5, 1.5, 2.5], ["a", "b", None]])
row_ids = table.insert(data)           # RecordBatch or Table; returns the new row ids

reader = table.select(columns=["id", "tag"],
                      predicate=(_.v > 1) & _.tag.isnull(),
                      limit_rows=1000)  # pa.RecordBatchReader
for batch in reader:                    # stream; or reader.read_all()
    ...

# update / delete address rows by the internal row id column "$row_id" (uint64)
hits = table.select(columns=["id"], predicate=_.id == 2, internal_row_id=True).read_all()
upd = hits.append_column("v", pa.array([9.9]))
table.update(upd, columns=["v"])
table.delete(hits)                      # needs only "$row_id"
```

Predicate pushdown (docs/predicate.md): an `AND` of column predicates, each an `OR` of:
`<, <=, ==, >, >=, !=`, `.isin([...])`, `.isnull()`, `~.isnull()`, `.startswith("p")`,
`.contains("s")`, `.between(a, b)` (README). Pushdown types: int8-64, float32/64, utf8, bool,
decimal128, binary, date32, time32, time64, timestamp. Anything else: filter client-side.

DuckDB on the stream (inside the transaction): `duckdb.connect().execute("SELECT sum(id) FROM reader")`.
Parquet export: write each batch with `pyarrow.parquet.ParquetWriter`.

## Parallel reads

```python
cfg = QueryConfig(data_endpoints=["http://<vip1>", "http://<vip2>", "http://<vip3>"], num_splits=3)
# or with DNS round-robin (TTL 0 / multi-answer): ["https://<pool-dns-name>"] * N
table.select(columns=[...], predicate=..., config=cfg)
```

`QueryConfig` fields (2.0.14.1): `num_sub_splits` (4), `num_splits` (estimated from rows/
`rows_per_split`=4,000,000), `data_endpoints`, `limit_rows_per_sub_split`,
`num_row_groups_per_sub_split` (8; keep 8 for semi-sorted projections),
`use_semi_sorted_projections` (True), `semi_sorted_projection_name`, `queue_priority`, `query_id`.
`vastdb.util.expand_ip_ranges(["http://<a.b.c.10-13>"])` expands a last-octet range.
`table.select_splits(...)` returns one reader per split for your own parallelism.

## Import Parquet from the cluster's S3

```python
from vastdb import util
t = util.create_table_from_files(schema=schema, table_name="<table>",
                                 parquet_files=["/<src-bucket>/<prefix>/file.parquet"])
table.import_files(["/<src-bucket>/<prefix>/more.parquet"], config=ImportConfig(import_concurrency=4))
table.import_partitioned_files({"/<src-bucket>/p/f.parquet": <pa.RecordBatch of partition values>})
```

The access key needs read access to the source objects. CNodes read the files directly.

## Reuse metadata across transactions

```python
from vastdb.table_metadata import TableMetadata, TableRef
md = TableMetadata(TableRef("<db-bucket>", "<schema>", "<table>"))
with session.transaction() as tx:
    md.load(tx)
with session.transaction() as tx:
    t = tx.table_from_metadata(md)
    t.insert(pa.RecordBatch.from_pylist(rows, schema=md.arrow_schema))
```

## Sorting, projections, snapshots

```python
table.add_sorting_key([0, 1])               # column indexes or names (SortingKey = list[int] | list[str]); permanent
table.sorted_columns(); table.sorting_done(); table.sorting_score()
p = table.create_projection("<proj>", sorted_columns=["tag"], unsorted_columns=["id"])
list(table.projections()); p.get_stats(); p.drop()

snaps = list(bucket.snapshots())             # snapshots of the database's path
old = bucket.snapshot("<snapshot-name>")
old.schema("<schema>").table("<table>").select().read_all()
```

The README shows `create_projection('proj', sorted=[...], unsorted=[...])` and
`bucket.list_snapshots()`; the 2.0.14.1 source names are `sorted_columns=`/`unsorted_columns=`
and `bucket.snapshots()`. Trust the installed source.

## Built-in tables

```python
cat = tx.catalog()                          # VAST Catalog (must be enabled; see features.md)
cat.select(["parent_path", "name", "size"], predicate=_.element_type == "FILE")
list(tx.catalog_snapshots())                # older catalog copies; tx.catalog(snapshot=...)
tx.audit_log()                              # protocol audit table, when auditing to DB is enabled
```

Well-known names (in the SDK): `vast-big-catalog-bucket/vast_big_catalog_schema/vast_big_catalog_table`
and `vast-audit-log-bucket/vast_audit_log_schema/vast_audit_log_table`. Open them with
`tx.catalog()` / `tx.audit_log()`, not `tx.bucket(...)` (the catalog bucket doesn't answer S3
bucket calls: `MissingBucket`).

## Kafka topics and blob expansion

Event Broker topics are tables in schema `kafka_topics` of the broker view's bucket, readable
with `select()`. `table.create_blob_expansion(...)` parses JSON message values into another
table (KB "Publishing Events to VAST Event Broker" has a full example). See `references/event-broker.md`.

## Vector search and ADBC

`create_table(..., vector_index=...)` and `table.vector_search(vec, columns, limit, predicate=None)`
need the ADBC driver (`pip install "vastdb[adbc]"`, package `adbc-driver-vastdb`).
`tx.adbc_conn` exposes an ADBC connection in the same transaction. Check the release's KB
"Vector Search" and "Vector Database Index" pages for supported metrics and limits.

## Errors (vastdb.errors)

`MissingBucket`, `MissingSchema`, `MissingTable`, `MissingSnapshot`, `MissingProjection`,
`SchemaExists`, `TableExists`, `MissingRowIdColumn` (update/delete without `$row_id`),
HTTP errors (`NotFound`, `Forbidden`, `BadRequest`, `Slowdown` = 503 SlowDown, retried),
`TooWideRow`/`TooLargeRequest`, `NotSupportedVersion` (cluster release too old for a feature),
and Python `NotImplementedError` for a predicate outside the pushdown subset. The full list is in
`vastdb/errors.py` of the installed version.
