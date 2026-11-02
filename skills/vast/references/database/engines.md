# Query engines and other clients for VAST DB

All of them need the same cluster prerequisites as the SDK (DATABASE view, S3 keys with
tabular permissions, a VIP pool reachable from **every** engine node) and a low-latency,
high-bandwidth network to the cluster. Check the KB pages for the user's release; the values
below are from the 5.5 pages.

## Trino

KB: "Installing and Configuring the VAST Connector for Trino"
`https://kb.vastdata.com/documentation/docs/installing-and-configuring-the-vast-connector-for-trino-55.md`.

- VAST ships Trino + connector as a Docker image: `https://hub.docker.com/r/vastdataorg/trino-vast`.
- Version matrix (KB 5.5): Trino 478 ↔ VAST 5.5; 475 ↔ 5.4+; 462 ↔ 5.3+; 443 ↔ 5.2+;
  429 ↔ 5.1+; 420 ↔ 5.0+; 375 ↔ 4.7+. Pick the row for the cluster's release.
- Catalog file `vast.properties`:
  ```properties
  connector.name=vast
  endpoint=http://<db-vip-or-pool-dns-name>
  region=us-east-1
  access_key_id=<access-key>
  secret_access_key=<secret-key>
  data_endpoints=http://<vip1>,http://<vip2>,...
  vast.http-client.request-timeout=60m
  vast.http-client.idle-timeout=60m
  # optional: vast.compression=zstd  (over-the-wire result compression)
  ```
- Names: `SHOW SCHEMAS IN vast;` lists `"<db-bucket>/<schema>"`; tables are
  `vast."<db-bucket>/<schema>".<table>`. Sorting: `ALTER TABLE ... SET PROPERTIES sorted_by = ARRAY['c1','c2']`.
  Trino also supports database views (`CREATE VIEW vast."<db>/<schema>".<view> AS SELECT ...`).
- VAST also runs managed Trino on CNodes in some releases (KB "Trino Managed CNode Applications").

## Spark

KB: "Installing the VAST Connector for Spark"
`https://kb.vastdata.com/documentation/docs/installing-the-vast-connector-for-spark-4.md`.

- Connector releases: `https://github.com/vast-data/vast-db-connectors/releases` (match the
  cluster release and the Spark version the KB names; it describes Spark 3.5.1).
- `spark-defaults.conf` (core settings):
  ```properties
  spark.ndb.endpoint=http://<one-vip>
  spark.ndb.data_endpoints=http://<vip1>,http://<vip2>,...
  spark.ndb.access_key_id=<access-key>
  spark.ndb.secret_access_key=<secret-key>
  spark.ndb.num_of_splits=256
  spark.ndb.num_of_sub_splits=10
  spark.sql.catalog.ndb=spark.sql.catalog.ndb.VastCatalog
  spark.sql.extensions=ndb.NDBSparkSessionExtension
  ```
- Names: ``ndb.`<db-bucket>`.<schema>.<table>`` (`spark.sql("show schemas in ndb")`).
- Sorting can't be enabled from Spark (KB "Sorted Tables").

## Others

- **Dremio**: KB "Installing and Configuring the VAST Connector for Dremio" (5.5).
- **DuckDB / pandas / Polars**: through the SDK's Arrow `RecordBatchReader` (see `sdk.md`).
- **ADBC**: the `adbc-driver-vastdb` package (`pip install "vastdb[adbc]"`), used by the SDK for
  vector search; public repo `vast-data/vastdb-adbc-driver`. Read its README for standalone use.
- **VAST Database CLI** (Docker image `vastdataorg/vast-db-cli:<version>`) for the Catalog and
  Audit Log tables: KB "VAST Database CLI Quick Start Guide" (5.5).

## Credentials

Never put the access/secret keys into files that will be committed. Use the engine's secret
mechanism (environment variables, Trino secrets `${ENV:VAR}`, Spark conf from the job submitter).
