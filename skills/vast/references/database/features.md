# VAST DB features, rules and limits

From the KB 5.5 "VAST Database Features" section (`https://kb.vastdata.com/documentation/docs/vast-database-features-55.md`)
unless marked otherwise. Rules change between releases: re-read the page for the user's
release (`vast_api.py kb search '<feature>' --version X.Y`) before promising one.

## Transactions

ACID; all operations are transactions. In the SDK one `with session.transaction()` block is
one transaction (commit on exit, rollback on exception). Readers returned by `select()` need
the transaction open. Permissions: `s3:TabularBeginTransaction`, `...CommitTransaction`,
`...RollbackTransaction`, `...GetTransaction`.

## Pushdown

Predicate and dereference pushdown (KB "Supported Pushdowns"). Engines (Trino/Spark) offload
filters and column selection to the CNodes; joins, aggregations beyond the pushdown set and
complex SQL run in the engine. SDK subset: `docs/predicate.md` in the SDK repo.

## Data types

KB "Supported Data Types" maps Arrow, Trino and Spark types. Watch precision on decimal and
timestamp types. Max cell size 126KB.

## Sorted tables (KB "Sorted Tables")

- Set at create (`sorting_key`, vcli `--sorted-column-names`, Web UI) or later
  (`table.add_sorting_key`, Trino `ALTER TABLE ... SET PROPERTIES sorted_by = ARRAY[...]`).
  Not from Spark.
- **Permanent**: can't disable, can't change columns or their order; sort-column values can't
  be updated.
- Not with: projections, exposed `vastdb_rowid`, replicated protected paths.
- Uses the first 8 bytes of a sort column: prefer date/timestamp types over strings.
- Works on 512K-row chunks; worth it above ~1M rows. Insert in large batches.
- Progress: `sorting_label` C → B → A → A+ (VMS `tables`; SDK `sorting_score()`, `sorting_done()`).
  Row count and size may temporarily grow while sorting; `count(*)` stays correct.

## Projections (KB "Managing Table Projections")

Semi-sorted subsets of a table's columns: up to **four** sorted columns plus any number of
unsorted ones. Queries using only projection columns can use them automatically
(`QueryConfig.use_semi_sorted_projections`). Not on sorted tables. SDK `create_projection`,
VMS `/projections/`, vcli `projection create|list|show|rename|delete`.

## Partitioning (KB "Database Partitioning")

Up to four partition columns with transforms `identity`, `bucket[N]`, `truncate[W]`, `year`,
`month`, `day`, `hour`. Defined at table creation from **Trino or Spark**; can't be removed or
changed; partition column values can't be updated. Compatible with sorting (an identity-partition
column can't also be a sort column), snapshots, quotas. SDK: `import_partitioned_files`.

## User-defined row ids (KB "User-Defined Row IDs for Tables")

Add an `int64` column named `vastdb_rowid` (value < 2^47) to expose and choose row ids
(SDK `create_table(..., use_external_row_ids_allocation=True)`). Not with sorting. The SDK's
internal `$row_id` (for update/delete) is a separate, always-available mechanism.

## Schema evolution (KB "Schema Management")

Add, drop and rename columns transactionally (SDK `add_column`, `drop_column`, `rename_column`;
VMS `/tables/add_columns/`, `/columns/`).

## Row and column security (KB "Row and Column Security")

Statements in identity or bucket policies: column allow/deny, column masking, row filtering, and
row filtering by S3 path authorization (reserved column `vastdb_s3_path_auth`). Applied by the
query engine with clauses returned by VAST DB.

## Vector search (KB "Vector Search", "Vector Database Index")

Vector column = fixed-size list of float32; distance functions and nearest-neighbour queries; a
vector index is created with the table (SDK `VectorIndexSpec(column=..., distance_metric=...)`
passed as `create_table(..., vector_index=...)`, or SQL `VECTOR CLUSTER BY`). Needs the ADBC driver.

## Snapshots

Database data lives on its view's path, so Element Store snapshots (and protection policies,
replication, global clones) cover it. Read a past state with `bucket.snapshots()` /
`bucket.snapshot(name)`. Limit 1019 snapshots (KB "Limitations"). Creating, restoring and
deleting snapshots: `references/data-protection.md`. Sorted tables can't be on a replicated path.

## VAST Catalog (KB "VAST Catalog", 5.5)

A cluster-wide table of file/object/directory metadata, indexed from periodic snapshots
(default every 30 minutes, kept 30 minutes; minimum interval 15 minutes). Off by default.
- Config: VMS `bigcatalogconfig` (`enable`, `state`, `frames`); user-defined attributes
  (`tag_<key>`, `metadata_<key>`, `nfs4_xattr_<key>`) via `bigcatalogindexedcolumns`. Enabling
  starts background indexing: ask first.
- Query: Web UI (Database → VAST Catalog), VMS `bigcatalogconfig/query_data` (admin, all tenants),
  SDK `tx.catalog()` (scoped to the key's tenant; needs `s3:TabularList*` + `s3:TabularQueryData`),
  Trino/Spark, VAST Database CLI. KB how-to: "Querying the VAST Catalog"
  `https://kb.vastdata.com/docs/querying-the-vast-catalog.md` (recipes, filter syntax, pitfalls).

## Audit log table

When protocol auditing writes to the database, `tx.audit_log()` reads
`vast-audit-log-bucket/vast_audit_log_schema/vast_audit_log_table` (KB "How To Audit DB Query Guide",
"Finding Hot Directories by IOPS and Capacity Using the VAST Audit Database").

## Limits (KB "Limitations")

| Item | Limit |
|---|---|
| Databases | 16384 (counted in total views) |
| Tables | 1 billion per DBox (counted in file count) |
| Rows per table | 2^48 |
| Columns per table | 31936 |
| Cell size | 126KB |
| Snapshots | 1019 |

See also "VAST Cluster Scale Guidelines" for the release.
