# VAST Event Broker (Kafka-compatible)

Builds on `SKILL.md` (connecting, version, spec, KB). Helper: `scripts/vast_api.py`.
Topics are stored as VAST Database tables, so `references/database.md` applies to reading them.

## Mental model

| Object | What it is | Notes |
|---|---|---|
| **Broker** | A **view** with protocol `KAFKA` (KB: enabling Kafka also enables `S3` and `DATABASE`) | The view's bucket is the broker's database. One broker per view. |
| **Kafka VIP pool** | A `PROTOCOLS` VIP pool set on the view (`kafka_vip_pools`, 5.5 API) | Exactly one pool per broker view, dedicated to it. Clients bootstrap from its VIPs. |
| **Topic** | A table in schema `kafka_topics` of the broker's database | Created via VMS, Web UI, vcli or a Kafka admin client (no auto-create). |
| Consumer group | Kafka consumer group state kept by the broker | ≤256 per broker view; offsets not replicated. |
| Third-party broker | An external Kafka cluster registered in VMS (`/kafkabrokers/`, `/eventbrokers/`) | For publishing S3 events *out*; not the VAST broker. |

Creation order: VIP pool → bucket-owner user (S3 keys, may create buckets) → S3-native view
policy → Kafka view with the pool → topics → (optional) TLS certificate, SASL/mTLS,
authorization → producers/consumers, S3 event notifications, DataEngine triggers.

KB (5.5): "Publishing Events to VAST Event Broker"
`https://kb.vastdata.com/documentation/docs/publishing-events-to-vast-event-broker-55.md`
(configuration, auth, topics, client examples, querying, data protection, event parsing).
Other release: `vast_api.py kb search 'Event Broker|Kafka' --version X.Y`.

## Check this cluster first

```bash
H=scripts/vast_api.py
python3 $H version
python3 $H spec model View | grep -i kafka          # kafka_* fields; KAFKA in protocols enum
python3 $H spec paths 'topic|kafka|eventbroker'
python3 $H get views fields=id,path,bucket,protocols,policy_id,tenant_id   # protocols contains KAFKA = a broker
python3 $H get views/<id>/                          # full view: kafka_vip_pools, auth settings
python3 $H get vippools fields=id,name,role,ip_ranges,tenant_id,kafka_view_id
```

On 5.5.3 `kafka_vip_pools` and the `kafka_*_timeout_sec` fields aren't accepted in a list's
`fields=` ("Unknown fields: ...") but are returned by `get views/<id>/`. A pool's
`kafka_view_id` names the broker view that uses it *(seen on 5.5.3)*.

## Workflow 1: create a broker (read, plan, ask, create)

KB section "Configuring VAST Event Broker".

1. **Take stock** with the reads above; reuse an existing broker view if it fits.
2. **VIP pool**: role `PROTOCOLS`, in the broker's tenant, **at least one VIP per CNode**,
   reachable from every producer/consumer (the broker advertises VIP addresses, not DNS
   names). If the view policy restricts VIP pools, the Kafka pool must be one of them. Each
   broker view needs its own pool. See `references/tenants-network.md`.
3. **User**: a user in the tenant's provider with S3 bucket-create permission and S3 keys; it
   becomes the bucket owner. (For SASL/PLAIN clients, a VAST **local** user: AD/LDAP not supported.)
4. **View policy**: S3-native flavor (as for any DATABASE view; see `references/database.md`).
5. **Plan and ask**: show the exact request. On 5.5 (check `spec model View`):
   ```bash
   python3 $H call POST /views/ --data '{"path": "/<broker-view>", "create_dir": true,
     "protocols": ["KAFKA", "S3", "DATABASE"], "bucket": "<broker-bucket>",
     "bucket_owner": "<owner-user>", "policy_id": <s3-native-policy-id>,
     "tenant_id": <tenant-id>, "kafka_vip_pools": [<pool-id>],
     "is_kafka_unencrypted_conn_allowed": true, "is_kafka_encrypted_conn_allowed": false}'
   ```
   (`create_dir` isn't in the 5.5.3 `View` model but is what vcli `--create-dir` and the
   Terraform provider send.) KB vcli form: `view create --tenant-id 1 --path </dir> --create-dir --policy-id 2 --protocols KAFKA,DATABASE,S3 --bucket mybucket --bucket-owner myadmin --kafka-vip-pools 3`.
   Dry run first; `--yes` only after the user agrees.
6. **Check**: `get views/<id>/` shows `KAFKA` in `protocols` and the pool in `kafka_vip_pools`;
   `get vippools/<pool-id>/` shows `kafka_view_id`; `get schemas database_name=<broker-bucket> tenant_id=<tid>`
   lists `kafka_topics` (the schema the Web UI calls "Kafka-Compatible Broker Topics").
7. **Connectivity** from a client host: TCP to `<vip>:9092` (plaintext) or `:9093` (TLS); these
   ports are the Web UI labels quoted in the KB article "Connect DataEngine to the Kubernetes
   Cluster and Registry". Then list topics with a Kafka admin client (`references/event-broker/kafka-clients.md`).

Rules that can't be undone (KB): **Kafka can't be added to an existing view**; the view's Kafka
VIP pool **can't be replaced** later (only modified). Deleting a broker view deletes its topics
and events: warn and get an explicit yes.

## Workflow 2: topics

KB section "Managing Event Topics"; vcli `topic create|modify|delete|list|show`.

```bash
python3 $H get topics database_name=<broker-bucket> tenant_id=<tid>              # names (paginated)
python3 $H get topics/show/ database_name=<broker-bucket> name=<topic> tenant_id=<tid>
python3 $H call POST /topics/ --data '{"database_name": "<broker-bucket>", "schema_name": "kafka_topics",
  "name": "<topic>", "topic_partitions": <n>, "retention_ms": <ms>, "tenant_id": <tid>}'   # dry run
```

That body created topics on 5.5.3 *(seen)*; the 5.5.3 spec has no body schema for `/topics/`.
Other settings (from `topics/show/` and vcli `topic create`, 5.5): `cleanup_policy`
(`delete`|`compact`), `min_compaction_lag_ms`, `delete_retention_ms` (tombstones),
`message_timestamp_type` (`CreateTime`|`LogAppendTime`), `message_timestamp_before_max_ms`,
`message_timestamp_after_max_ms`, `max_message_bytes`. `topics/show/` also returns
`num_events` and `capacity`. Details and the rename/delete calls: `references/event-broker/vms-api.md`.

- **Partitions are fixed at creation.** The 5.5 KB says both "up to 1000 partitions" per topic
  (Web UI/vcli pages) and "up to 20,000 partitions ... 200,000 per broker view" (limitations
  list): the release's own UI/vcli limit is the safe one. A starting point: the number of CNodes.
- **Retention**: default 7 days; minimum 6 hours; `-1` = keep forever (KB).
- **Max message size** above 5MB disables compaction and database queries on that topic (KB).
- Kafka admin clients can also create topics (`replication_factor` 1 in the KB example).
- Deleting a topic deletes its events: ask first.

## Workflow 3: produce and consume

`references/event-broker/kafka-clients.md` has producer, consumer and admin examples (confluent-kafka and
kafka-python), plus SASL/TLS settings. Essentials:

- `bootstrap.servers`: **three VIPs of the broker's pool** with the port (KB recommendation),
  e.g. `<vip1>:9092,<vip2>:9092,<vip3>:9092`.
- Client support (KB 5.5): Confluent Kafka Python client **2.4-2.8**; **aiokafka not supported**.
  KB examples also use `kafka-python`.
- Turn off what VAST doesn't support: **no over-the-wire compression** (`compression.type=none`),
  **no idempotent producer** (`enable.idempotence=false`; Java clients ≥3.0 enable it by default),
  **no transactions**, no cooperative rebalancing, no `group.instance.id`, no seek by time,
  no fetch sessions, no READ UNCOMMITTED. Records: message ≤1MB, key ≤126KB, value ≤126KB.

## Workflow 4: security

KB sections "Configuring User Authentication / mTLS / Authorization for the VAST Event Broker
View" and "Granting Kafka Permissions in an Identity Policy".

| Need | Where (5.5) |
|---|---|
| Plaintext vs TLS listeners | View `is_kafka_unencrypted_conn_allowed`, `is_kafka_encrypted_conn_allowed` |
| Authentication per listener | View `kafka_unencrypted_auth_mechanism`, `kafka_encrypted_auth_mechanism` (seen `NONE`; KB: SASL `PLAIN` on either, `mTLS` on the encrypted one). The spec gives no enum: read the values from an existing view or `/docs/` before setting one. |
| TLS certificate | One Kafka certificate per cluster (Web UI Settings → Certificates → Kafka; vcli `certificate create --cert-type KAFKA`). **SANs must list every Kafka VIP as an IP address**; issue it from an internal CA. Adding a broker view later means reissuing it with the new VIPs. |
| mTLS | TLS 1.3; cluster-wide CA (+ tenant identification by SAN `otherName` OID) or per-tenant CA (`tlscertificate create --protocols KAFKA`); then the view's encrypted mechanism = mTLS. |
| Authorization (ACLs) | View `kafka_is_authorization_required`; then identity-policy actions `KafkaRead`, `KafkaWrite`, `KafkaCreate`, `KafkaDelete`, `KafkaDescribe`, `KafkaDescribeConfigs`, `KafkaAlterConfigs` (topics), Read/Delete/Describe (groups), Alter/AlterConfig/ClusterAction/Create/Describe/DescribeConfigs (cluster). KB resource example: `vast:kafka:topic:<broker>:<topic>`. With no matching statement, operations are **allowed** (KB). |
| Group timeouts | View `kafka_first_join_group_timeout_sec`, `kafka_rejoin_group_timeout_sec` (1-3600; 60 seen) |

Switching a live broker's listeners, auth or authorization disconnects or locks out clients
that don't match: warn the user, and change it in a quiet window.

## Workflow 5: query topics as tables

Each topic is a table `<broker-bucket>/kafka_topics/<topic>`: Trino `SHOW TABLES IN vast."<broker-bucket>/kafka_topics";`,
the vastdb SDK (`tx.bucket("<broker-bucket>").schema("kafka_topics").table("<topic>").select()`),
or VMS `get tables database_name=<broker-bucket> schema_name=kafka_topics tenant_id=<tid>` and
`vastdbtable/query_data/` (see `references/database.md`). Columns of a topic table on 5.5.3 *(seen)*:
`key` (binary), `value` (binary), `timestamp_broker`, `timestamp_producer` (timestamp[ms]),
`headers` (list of key/value structs), `external_offset` (int64), `compaction_process_seq_num`,
`extra_metadata`. Re-check with `vastdbtable/columns/` on other releases. Decode `key`/`value`
client-side (they're the raw Kafka bytes). Queries by partition aren't supported.

**Parse JSON events into a table** ("blob expansion", KB section "Parsing Kafka Events into a
VAST Database Table"): Web UI, vcli `blobexpansion create|add-columns|drop-columns|show|delete`,
or SDK `table.create_blob_expansion(...)`. Needs `s3:Tabular*BlobExpansion` permissions.

## Workflow 6: S3 events and DataEngine

- **S3 bucket notifications to a VAST broker** (KB "Publishing S3 Bucket Events to VAST Event
  Broker"): set `event_notifications` on the *source* S3 view (5.5 `EventNotification`: `name`,
  `topic`, `triggers` such as `S3_OBJECT_CREATED_ALL`/`S3_OBJECT_REMOVED_ALL`/...,
  `prefix_filter`, `suffix_filter`, and the broker: `broker_id` for a third-party broker,
  `internal_broker_id` for a VAST broker view (check the field description with
  `spec model EventNotification`). The topic must exist first (no auto-create).
- **DataEngine** uses a VAST broker view as the tenant's Kafka broker: tenant setup takes
  `kafka_broker` (type `Internal`, name = broker view's bucket), `default_topic_name`,
  `dead_letter_topic_name`; triggers carry `broker` + `topic_name` (DataEngine API, 5.5;
  `spec search topic --dataengine`). Plaintext 9092 is what the KB DataEngine walkthrough uses.
  See `references/dataengine.md`.
- **Third-party Kafka** (VAST publishes to your Kafka): `/kafkabrokers/` (`name`, `addresses`
  `host:port` list up to five, `tenant_id`, `certificate_set_id`), vcli `eventbroker create`;
  KB "Publishing S3 Bucket Events to Third-Party Event Brokers".

## Limits and behaviour (KB 5.5 "Kafka Protocol Support")

Supported: Producer, Consumer, consumer groups, Admin (create/describe/alter configs/delete
topics, delete groups), compaction, SSL, database queries on topics. Not: compression on the
wire, automatic topic creation, transactions, idempotence, topic access by UUID. ≤256 consumer
groups per broker view (and per listing). One VIP pool per broker. Not subject to protocol
auditing or QoS. Data protection: snapshots, global clones, async replication (destination is
read-only; recreate the Kafka view and a same-named pool there; consumer offsets aren't
replicated; no fast restore of a path holding a Kafka view). Metrics: Web UI Analytics
reports with "Kafka"; VMS `/prometheusmetrics/kafka_targets`.

## Pitfalls

| Symptom / error | Cause | Fix |
|---|---|---|
| Client connects to bootstrap, then times out | Broker advertises VIPs the client can't reach | Route the client to every VIP in the Kafka pool. |
| Produce requests fail while the client compresses (expected from the KB support list; not reproduced) | No wire compression | `compression.type=none`. |
| Producer errors at start-up or on first send mentioning idempotence/transactions (expected; not reproduced) | Idempotent/transactional producer (Java clients ≥3.0 enable idempotence by default) | `enable.idempotence=false`; don't set `transactional.id`. |
| Produce to a new topic name fails with unknown topic | No auto-create (KB) | Create the topic first. |
| VMS `topics/show/` → 400 `Failed to get Kafka configs for topic "<t>": KafkaConfigs_ErrorCode.UNKNOWN_TOPIC_OR_PARTITION` *(5.5.3)* | Topic doesn't exist | `get topics database_name=...`. |
| VMS `get topics` → 400 `{"database_name": "field required"}` *(5.5.3)* | Missing parameter | Pass `database_name` (+ `tenant_id`). |
| View create rejects DATABASE/Kafka with "...can only have a view policy where the security flavor is S3 native." *(5.5.3)* | Policy flavor | Use an `S3_NATIVE` policy. |
| Can't enable Kafka on an existing view | Not allowed (KB) | Create a new view. |
| TLS handshake fails / hostname mismatch | Certificate lacks the VIP IP SANs | Reissue with every Kafka VIP as an IP SAN. |
| SASL with AD/LDAP user fails | Only VAST local users (KB) | Use a local user. |
| `offsetsForTimes` / seek by timestamp fails | Not supported | Seek by offset. |
| Consumer group fails with a cooperative assignor (KB: not supported) | Cooperative rebalancing | Use an eager assignor (`range`/`roundrobin`). |
| aiokafka client fails | Not supported (KB) | Use confluent-kafka 2.4-2.8. |

## Related areas

`SKILL.md`, `references/database.md` (topics are tables), `references/views-protocols.md` (views, policies),
`references/tenants-network.md` (VIP pools), `references/identity-access.md` (users, keys, identity policies,
certificates), `references/dataengine.md` (triggers on topics), `references/data-protection.md`, `references/monitoring.md`.

Verified: VAST 5.5.3 — spec read (View kafka fields, KafkaBroker, EventNotification, DataEngine
Broker/Topic models), live read-only calls (views, vippools, schemas, topics, topics/show, tables
in `kafka_topics`) and their errors; topic-create body seen working on 5.5.3; KB 5.5 pages read.
Kafka client settings follow the KB's support list; no client was run against the cluster for
this file.
