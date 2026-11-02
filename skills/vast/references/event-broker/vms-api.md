# Event Broker objects in the VMS REST API

Helper: `scripts/vast_api.py` (run from the skill folder). Field names here are
from the 5.5.3 spec unless tagged *(seen on 5.5.3)*, which means observed in live responses
because the spec has no schema for that endpoint. Re-check on other releases with
`vast_api.py spec model View | grep -i kafka` and `vast_api.py spec paths 'topic|kafka|eventbroker'`.

## Broker view (`/views/`)

| Field (5.5 `View`) | Type | Meaning |
|---|---|---|
| `protocols` | array, enum includes `KAFKA`, `S3`, `DATABASE` | A broker view has all three (KB: Kafka enables the other two). |
| `kafka_vip_pools` | array of integer | The Kafka VIP pool (exactly one). Can't be replaced after creation (KB). |
| `is_kafka_unencrypted_conn_allowed` | boolean | Plaintext listener (9092 in the Web UI). |
| `is_kafka_encrypted_conn_allowed` | boolean | TLS listener (9093 in the Web UI). |
| `kafka_unencrypted_auth_mechanism` | string ≤32 | `NONE` seen; KB: SASL PLAIN. No enum in the spec. |
| `kafka_encrypted_auth_mechanism` | string ≤32 | `NONE` seen; KB: SASL PLAIN or mTLS. |
| `kafka_is_authorization_required` | boolean | Enforce identity-policy Kafka ACLs. |
| `kafka_first_join_group_timeout_sec`, `kafka_rejoin_group_timeout_sec` | integer 1-3600 | Consumer group join timeouts (60 seen). |
| `bucket`, `bucket_owner`, `policy_id`, `tenant_id`, `path` | | As for any S3/DATABASE view. |
| `event_notifications` | array of `EventNotification` | On a *source* S3 view: publish its S3 events to a topic. |

`kafka_vip_pools` and the timeout fields are rejected in a list `fields=` filter on 5.5.3
("Unknown fields"); read them from `GET /views/<id>/`. The VIP pool's `kafka_view_id`
(`VIPPool` model) points back to the broker view.

To find brokers: `get views` and keep the ones whose `protocols` include `KAFKA`.

## Topics (`/topics/`)

| Call | Parameters | Notes |
|---|---|---|
| `GET /topics/` | `database_name` (required), `tenant_id`, `page`, `page_size` | Paginated `{count, next, previous, results: [{database_name, name}]}` *(seen)* |
| `GET /topics/show/` | `database_name`, `name`, `tenant_id` | Full config *(seen)*: `topic_partitions`, `retention_ms`, `cleanup_policy`, `delete_retention_ms`, `min_compaction_lag_ms`, `message_timestamp_type`, `message_timestamp_before_max_ms`, `message_timestamp_after_max_ms`, `max_message_bytes`, `num_events`, `capacity`. Large values come back as strings. |
| `POST /topics/` | body | `{"database_name": "<broker-bucket>", "schema_name": "kafka_topics", "name": "<topic>", "topic_partitions": <n>, "retention_ms": <ms>, "tenant_id": <tid>}` created topics *(seen on 5.5.3)*. Optional fields: the config names above (vcli `topic create` options; Terraform `vastdata_topic` lists `message_timestamp_*`, `retention_ms`). |
| `PATCH /topics/rename/` | see `https://<VMS>/docs/` | Rename. |
| `DELETE /topics/delete/` | see `/docs/` | **Deletes the topic and its events.** |

The spec lists these paths without parameters or bodies; `https://<VMS>/docs/` and the vcli
pages ("topic create|modify|delete|list|show", 5.5) document the fields. Always dry-run first:
`python3 scripts/vast_api.py call POST /topics/ --data '{...}'`.

Topics also appear as tables: `GET /tables/ database_name=<broker-bucket> schema_name=kafka_topics`
(`num_rows`, `size`, `num_partitions`) and can be read with `/vastdbtable/query_data/` (see
`references/database.md` → `references/vms-api.md`). Each broker database has the schema `kafka_topics`.

## S3 event notifications (`View.event_notifications`, 5.5 `EventNotification`)

| Field | Notes |
|---|---|
| `name` (required) | Notification name |
| `topic` (required) | Topic name (must exist) |
| `triggers` | `S3_OBJECT_CREATED_ALL`, `..._PUT`, `..._POST`, `..._COPY`, `..._COMPLETE_MULTIPART_UPLOAD`, `S3_OBJECT_REMOVED_ALL`, `..._DELETE`, `..._DELETE_MARKER_CREATED`, `S3_OBJECT_TAGGING_ALL`, `..._PUT`, `..._DELETE` |
| `prefix_filter`, `suffix_filter` | Object key filters |
| `broker_id` / `internal_broker_id` | Third-party broker (`/kafkabrokers/` id) / VAST broker; read the field descriptions with `spec model EventNotification` before choosing |
| `effective_broker_name` | Read-only |

Set it with `PATCH /views/<source-view-id>/` (dry run, then ask). KB: "Publishing S3 Bucket
Events to VAST Event Broker" and "...to Third-Party Event Brokers" (event format, analytics).
Changing notifications on a live bucket changes what downstream consumers (and DataEngine
triggers) receive.

## Third-party brokers (`/kafkabrokers/`, `/eventbrokers/`)

5.5 `KafkaBroker`: `name` (required, ≤64), `addresses` (bootstrap `host:port` list, ≤5 per
vcli `eventbroker create`), `tenant_id`, `certificate_set_id`, `hostname_verification_enabled`,
`guid`. `GET /kafkabrokers/<id>/list_topics/` lists the external broker's topics. Hosts must be
reachable from the cluster's **management** network (KB). These are not VAST broker views.

## Metrics

`GET /prometheusmetrics/kafka_targets` (5.5 path) and the Web UI Analytics reports whose
names contain "Kafka" (per broker view and per CNode). See `references/monitoring.md`.
