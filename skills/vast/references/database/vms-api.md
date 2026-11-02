# VAST DB objects through the VMS REST API

VMS manages databases (views) and can list and peek at their contents. Data-heavy work belongs
in the SDK or a query engine. All calls below are GETs (safe). Helper: `scripts/vast_api.py`
(run from the skill folder as `python3 scripts/vast_api.py`).

**Check first on the user's cluster**: `vast_api.py spec paths 'schemas|tables|columns|projection|vastdb|bigcatalog'`.
On 5.5.3 the spec lists these paths but gives **no parameters or request bodies** for most of
them, so the parameter names here come from live calls (and the error messages that name
missing fields). The cluster's own reference at `https://<VMS>/docs/` is the next place to look;
a 400 naming a missing field tells you the rest.

## Tenant scoping

Databases belong to a tenant. As a cluster admin, add `tenant_id=<id>` for a database outside
the default tenant; without it 5.5.3 answers 404
`Getting schema list failed ... could not find @s3_bucket_name=<db-bucket> (res=8)`.
Find the tenant from the view: `get views bucket=<db-bucket> fields=id,tenant_id,protocols`.

## Endpoints (5.5 API, seen on 5.5.3)

| Path | Required query parameters | Returns |
|---|---|---|
| `GET /schemas/` | `database_name` (+ `tenant_id`) | `[{database_name, name, properties}]` |
| `GET /schemas/show/` | as above + `name` (check `/docs/`) | one schema |
| `GET /tables/` | `database_name`, `schema_name` (+ `tenant_id`) | paginated `{count,next,previous,results}`; each: `name`, `num_rows`, `size`, `num_partitions`, `partitioning_key_enabled`, `sorting_key_enabled`, `sorting_score`, `sorting_label` (C/B/A/A+), `sorting_done`, `write_amplification` |
| `GET /tables/show/` | `database_name`, `schema_name`, `name` | the above + `is_external_rowid_alloc`, `is_imports_table`, `vector_indexes`, `secondary_index`, `partitions_config` |
| `GET /vastdbtable/columns/` (also `GET /columns/`) | `database_name`, `schema_name`, `table_name` | `[{name, field: {column_type}, raw_field}]` |
| `GET /vastdbtable/stats/` | same | `{count_columns, count_rows}` |
| `GET /vastdbtable/query_data/` | same + `fields` (comma-separated names) + `filters` (JSON, `{}` for none); optional `limit` | `{count, next, prop_list: [cols], results: [[row], ...]}` |
| `GET /vastdbtable/aggregate/` | same + `metrics` + `filters` (names from the 400; values: see `/docs/`) | aggregates |
| `GET /projections/` | `database_name`, `schema_name`, `table_name` | projections of a table |
| `GET /projectioncolumns/` | as above + projection name (check `/docs/`) | its columns |
| `GET /vastdb/vips/` | none (+ `tenant_id`) | "DB access VIPs": `[{vip, port}]` |
| `GET /bigcatalogconfig/` | none | VAST Catalog policy: `enable`, `state`, `frames`, `prefix` |
| `GET /bigcatalogconfig/columns/`, `/stats/` | none | catalog schema, row count |
| `GET|POST /bigcatalogconfig/query_data/` | `path`, `filters` (at least one), `fields`, `limit` | catalog rows (KB "Querying the VAST Catalog") |
| `GET /bigcatalogindexedcolumns/` | none | user-defined indexed attributes |

`filters` shape (seen on 5.5.3 for `vastdbtable/query_data`, documented by the KB for the
catalog): `{"<column>": [{"<op>": <value>}]}`, e.g. `{"id": [{"eq": 42}]}`;
`eq` and `gt` worked on 5.5.3. The operator list per release is on `https://<VMS>/docs/`.

Example (placeholders):

```bash
H=scripts/vast_api.py
python3 $H get schemas database_name=<db-bucket> tenant_id=<tid>
python3 $H get tables database_name=<db-bucket> schema_name=<schema> tenant_id=<tid>
python3 $H get vastdbtable/columns/ database_name=<db-bucket> schema_name=<schema> table_name=<table> tenant_id=<tid>
python3 $H get vastdbtable/query_data/ database_name=<db-bucket> schema_name=<schema> \
    table_name=<table> tenant_id=<tid> 'filters={}' fields=<col1>,<col2> limit=20
```

## Errors seen on 5.5.3

| Call | Error | Meaning |
|---|---|---|
| `tables` without params | 400 `{"database_name": "field required", "schema_name": "field required"}` | pass both |
| `tables`, bad schema | 404 `Getting table list failed ... failed to fetch schema element for @s3_object_name=<schema>` | schema missing |
| `query_data`, bad table | 404 `Getting column list failed ... Fetching table schema element failed` | table missing |
| `query_data` without `fields` | 400 `fields - field required` | pass `fields` |
| `query_data` with `fields='["a","b"]'` | 400 `Following columns do not exist in the table` | use `a,b`, not JSON |
| `aggregate` without params | 400 `{"metrics": "field required", "filters": "field required"}` | |

## Changes through VMS (ask first; dry run with the helper)

`POST /schemas/`, `POST /tables/`, `PATCH /tables/add_columns/`, `PATCH /tables/rename/`,
`DELETE /tables/delete/`, `POST /tables/load_from_file/`, `POST|DELETE /columns/...`,
`POST /projections/`, `DELETE /schemas/delete/` exist on 5.5.3. Their bodies aren't in the spec;
the vcli pages in the KB (`schema create --name <schema> --database-name <db>`,
`table create --database-name ... --schema-name ... --name ... --sorted-column-names ...`)
show the same fields in CLI form. Deletes remove data permanently.

The **database itself** is a view: create/modify it through `/views/` (see `references/views-protocols.md`).
