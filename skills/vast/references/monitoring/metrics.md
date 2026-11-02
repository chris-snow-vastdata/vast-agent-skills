# Performance and capacity metrics: the analytics API and Prometheus

Everything here was checked against the VAST 5.5.3 VMS spec and live read-only calls
(*5.5.3 spec*, *seen on 5.5.3*). On another release, re-check with
`scripts/vast_api.py spec show /monitors/ad_hoc_query/ get` and the KB
"API Reference" page **Query Analytics with Ad Hoc Query Parameters** for that release.

## Contents
- [The objects](#the-objects)
- [Discover metric names](#discover-metric-names-do-this-on-every-release)
- [Query: ad hoc](#query-ad-hoc)
- [Query: a saved or predefined monitor](#query-a-saved-or-predefined-monitor)
- [Reading the response](#reading-the-response)
- [Top talkers](#top-talkers)
- [Useful metric names (5.5)](#useful-metric-names-seen-on-553)
- [Prometheus exporter](#prometheus-exporter)
- [Client-side metrics (vnfs-collector)](#client-side-metrics)
- [Pitfalls](#pitfalls)

## The objects

| Object | Endpoint (5.5.3 spec) | What it is |
|---|---|---|
| Metric catalog | `GET /metrics/` (also `GET /analytics/`, same list) | Every metric: `fqn` (the name you query), `class_name`, `object_types`, `units`, `title`. Several thousand entries. |
| Monitor (analytics report) | `GET/POST /monitors/`, `GET /monitors/{id}/` | A saved query: `object_type`, `prop_list`, `time_frame`, `granularity`, `aggregation`, `object_ids`. ~250 `monitor_type: predefined` ones ship with 5.5 (the Web UI's Analytics graphs). |
| Run a monitor | `GET /monitors/{id}/query/` | Optional `time_frame` / `from_time` / `to_time` / `granularity` / `aggregation` override. |
| Ad hoc query | `GET /monitors/ad_hoc_query/` | The same query without saving anything. Read-only. |
| Top-N snapshot | `GET /monitors/topn/` | The latest "Top Actors" frame for users, clients, views, VIPs, VIP pools, CNodes, volumes. |
| Monitored objects | `GET /monitoredusers/`, `/monitoredhosts/`, `/monitoredviews/`, `/monitoredvips/`, `/monitoredvippools/`, `/monitoredcnodes/` | Map the `object_id`s in user/host/view/VIP metrics to a readable `title` (user name, client IP, view path, with tenant). |
| Dashboard | `GET /dashboard/monitoring/` | The Web UI dashboard's last ~10 minutes of cluster samples. |
| Tenants | `GET /tenants/top_tenants/` | Per-tenant `capacity`, `bw`, `iops`, `latency` series. |

`POST /monitors/` (a custom saved report) and `DELETE /monitors/{id}/` change the cluster:
plan and ask first. For one-off questions use the ad hoc query: it saves nothing.

## Discover metric names (do this on every release)

Metric names (`fqn`) are the field you pass in `prop_list`. They change between releases, so
look them up on the user's cluster:

```bash
# helper in this skill (read-only); REGEX matches fqn, object types, units and title
python3 scripts/vast_monitor.py metrics 'ProtoCommon,(iops|bw|latency)$'
python3 scripts/vast_monitor.py metrics --class TopNMetrics
# or straight from the API: class_name and fqn__contains filter the catalog (seen on 5.5.3)
vast_api.py get metrics class_name=ViewMetrics
vast_api.py get metrics fqn__contains=latency
```

Simplest route to a correct `prop_list`: find the predefined monitor that draws the graph the
user means and copy its `prop_list`:

```bash
vast_api.py get monitors object_type=view fields=id,name,prop_list,time_frame
```

`fqn` shapes *(seen on 5.5.3)*:

- `ProtoMetrics,proto_name=<PROTO>,<measure>`: cluster and per-CNode protocol stats. `<PROTO>`
  includes `ProtoCommon` (all client protocols), `NFSCommon` (NFSv3), `NFS4Common`, `SMBCommon`,
  `S3Common`, `BlockCommon`, `KafkaCommon`, `ReplicationCommon`, `ProtoAll`. Measures: `iops`,
  `rd_iops`, `wr_iops`, `md_iops`, `rd_md_iops`, `wr_md_iops`, `bw`, `rd_bw`, `wr_bw`, `latency`,
  `rd_latency`, `wr_latency`, plus statistics such as `read_latency__avg`.
- `ViewMetrics,<measure>__<stat>` (object type `view`), e.g. `read_iops__time_avg`,
  `write_bw__time_avg`, `read_latency__avg`, `qos_wait_for_budget_time__avg`.
- `TenantMetrics,...` (object type `tenant`), e.g. `read_iops__time_avg`, `write_bw__time_avg`,
  `read_latency__avg`, `logical_capacity`, `drr`, `snapshot_aggregated_usage`.
- `TopNMetrics,<measure>` (object types `host`, `user`, `vip`, `vippool`): `iops`, `read_iops`,
  `write_iops`, `md_iops`, `bw`, `read_bw`, `write_bw`, `latency`, `read_latency`,
  `write_latency`, `qos_wait_time`.
- `Capacity,<field>` (object type `cluster`), e.g. `physical_space`, `physical_space_in_use`,
  `logical_space`, `logical_space_in_use`, `usable_capacity_bytes`, `quotas_used_capacity`.
- Others: `VolumeMetrics` (block), `KafkaProtoMetrics`, `NfsMetrics`/`Nfs4Metrics` (per-op),
  `QosMetrics`, `TabularQueryEngineMetrics` (VAST Database), `K8sMetrics` (compute clusters).

## Query: ad hoc

`GET /monitors/ad_hoc_query/` parameters (KB API 5.5 + live):

| Parameter | Values |
|---|---|
| `object_type` (required) | `cluster`, `cnode`, `view`, `tenant`, `user`, `host`, `vip`, `vippool`, `volume`, `dnode`, `ssd`, `nvram`, `replicationstream`... The KB's enum lists only some of these; all of `cluster, cnode, view, tenant, user, host` answered on 5.5.3. Use the `object_types` of the metric in `/metrics/`. |
| `prop_list` | One metric `fqn` per parameter, **repeated**: `prop_list=A&prop_list=B`. |
| `time_frame` | Integer + unit: `m` minutes, `h` hours, `D` days, `W` weeks, `M` months, `Y` years (`10m`, `2h`, `7D`). Bad value → `Invalid time frame: 10x`. |
| `from_time`, `to_time` | Instead of `time_frame`: ISO timestamps, e.g. `2026-01-15T13:00:00Z`. |
| `granularity` | `seconds` (raw, ~10 s samples), `minutes` (5-minute aggregates), `hours`, `days`. |
| `aggregation` | With `minutes`/`hours`/`days`: `avg`, `min`, `max`, `sum`, `stddev`, `latency_weighted_average`. |
| `object_ids` | Repeated, to limit to some objects (ids from the object's list or `/monitored*/`). |

```bash
# this skill's helper repeats prop_list correctly:
python3 scripts/vast_monitor.py query cluster \
  --prop 'ProtoMetrics,proto_name=ProtoCommon,iops' --prop 'ProtoMetrics,proto_name=ProtoCommon,latency' \
  --time-frame 24h --granularity hours --aggregation max
# vastpy-cli repeats a key as a list:
vastpy-cli get monitors/ad_hoc_query object_type=view time_frame=1h \
  prop_list=ViewMetrics,read_iops__time_avg prop_list=ViewMetrics,write_iops__time_avg
# curl
curl -s -u "$VMS_USER:$VMS_PASSWORD" --cacert ca.pem \
 "https://$VMS_ADDRESS/api/latest/monitors/ad_hoc_query/?object_type=cnode&time_frame=1h&granularity=minutes&aggregation=avg&prop_list=ProtoMetrics,proto_name=ProtoCommon,iops"
```

The shared `vast_api.py get` takes one value per key, so with it you can pass only one
`prop_list` per call. Use the helper above, vastpy-cli or curl for several.

## Query: a saved or predefined monitor

```bash
vast_api.py get monitors fields=id,name,object_type,time_frame   # pick one
python3 scripts/vast_monitor.py monitor <id> --time-frame 6h --granularity minutes
```

Predefined cluster monitors default to `time_frame: 10m`, view/user/tenant ones to `2h`
*(seen on 5.5.3)*. Override per call.

## Reading the response

```json
{"object_ids": [1],
 "prop_list": ["timestamp", "object_id", "ProtoMetrics,proto_name=ProtoCommon,bw", "ProtoMetrics,proto_name=ProtoCommon,iops"],
 "data": [["2026-01-15T13:00:00Z", 1, 172061.0, 4.0], ...]}
```

- `data` rows are `[timestamp, object_id, metric values...]`, **in the order of the response's
  `prop_list`, which may differ from the order you asked for** (seen on 5.5.3). Always map by the
  response's `prop_list`.
- Newest row first. Several objects → rows interleave by `object_id`.
- `null` means no sample for that metric at that time.
- Units: check against `units` in `/metrics/`, **but verify with a known value**. On 5.5.3 the raw
  protocol `bw` values matched bytes/s and `latency` microseconds (the cluster object reports
  the same numbers as `bw` vs `bw_mb` and `latency` vs `latency_ms`), although the catalog said
  `MB/Sec` and `ms`. Compare with the Web UI before you report numbers.
- `{"detail": "metrics not available", "code": "property_error"}`: a name in `prop_list` does not
  exist for that object type (typo, or a name from another release). Look it up in `/metrics/`.
- `{"detail": "ContentType matching query does not exist."}`: unknown `object_type`.
- Omitting `prop_list` returns **every** metric of that object type: a huge response. Always pass it.

## Top talkers

Three ways, from coarse to precise:

1. **Now** (`GET /monitors/topn/`): `data.<kind>.<measure>` lists, where kind is `user`,
   `client`, `view`, `vip`, `vippool`, `cnode`, `volume` and measure is `bw`, `iops`, `md_iops`,
   `latency`, `qos_wait_time`. Each entry has `total`, `read`, `write`, `title` (`title` carries
   the name and `[tenant]`). One frame; `timestamp`/`previous` say which.
   `python3 scripts/vast_monitor.py top --kind client --by bw`
2. **Over a period**: ad hoc query with `object_type=user` or `host` and `TopNMetrics,...`
   (e.g. `iops`, `bw`, `latency`) over `time_frame`, then resolve `object_id` via
   `/monitoredusers/` or `/monitoredhosts/` (`title`, `username`, `ip`, `tenant_name`).
   Only the top actors at each sample are recorded, so an object can be missing from some samples.
3. **Per view**: `object_type=view` with `ViewMetrics,read_iops__time_avg` etc., names via
   `/monitoredviews/`.

KB: **Top Actors** and **Data Flow Analytics** (Web UI, 5.5).

## Useful metric names (seen on 5.5.3)

| Question | object_type | prop_list |
|---|---|---|
| Cluster IOPS / bandwidth / latency | `cluster` | `ProtoMetrics,proto_name=ProtoCommon,iops` / `,bw` / `,latency` (and `rd_`/`wr_`) |
| Per protocol | `cluster` | `ProtoMetrics,proto_name=NFSCommon|NFS4Common|SMBCommon|S3Common|BlockCommon,iops` |
| Per CNode balance | `cnode` | same `ProtoMetrics` names |
| Per view | `view` | `ViewMetrics,read_iops__time_avg`, `ViewMetrics,write_bw__time_avg`, `ViewMetrics,read_latency__avg` |
| QoS throttling on a view | `view` | `ViewMetrics,qos_wait_for_budget_time__avg` |
| Per tenant | `tenant` | `TenantMetrics,read_iops__time_avg`, `TenantMetrics,write_latency__avg`, `TenantMetrics,logical_capacity`, `TenantMetrics,drr` |
| Users / clients | `user` / `host` | `TopNMetrics,iops`, `TopNMetrics,bw`, `TopNMetrics,latency`, `TopNMetrics,qos_wait_time` |
| Capacity trend | `cluster` | `Capacity,physical_space_in_use`, `Capacity,logical_space_in_use`, `Capacity,usable_capacity_bytes` |

## Prometheus exporter

VMS serves Prometheus text format at `https://<VMS>/api/prometheusmetrics/<set>` (the versioned
`/api/latest/prometheusmetrics/...` also answers). Authenticate with a VMS manager login (basic
auth) or an API token; a **tenant admin's token scopes the output to that tenant** (KB "Tenant
Admin Metrics Access (API & Prometheus)").

Sets in the 5.5.3 spec: `alarms`, `all`, `basic`, `certificates`, `computeclusters`, `defrag`,
`devices`, `gns`, `host_view`, `kafka_targets`, `licenses`, `lifecycle_metrics`, `nics`,
`protocol_transferred_bytes`, `quotas`, `replications`, `sts`, `switches`, `tenants`,
`user_connections`, `user_view`, `users`, `views`, `views/active`, `vip_view`, `vips`,
`vms_state`, `volumes`, and the bare `/api/prometheusmetrics/` (cluster and CNode metrics not in
the other sets). List them on any release with `vast_api.py spec paths prometheusmetrics`.

- `vms_state`: `vast_vms_state` gauge, 1 = CLUSTERED (OK), 0 = DEGRADED.
- `alarms`: one `vast_vms_alarms` series per active alarm, labelled with `severity`,
  `object_type`, `event_name`, `acknowledged`. Good for Alertmanager rules.
- Avoid `all` on large clusters (KB): scrape the specific sets you graph.

Prometheus scrape job (KB **Exporting Metrics to Prometheus**, 5.5): scheme `https`, target
`<VMS address>:443`, `metrics_path: /api/prometheusmetrics/<set>`, `basic_auth` with a read-only
VMS user, `scrape_interval: 1m`, `scrape_timeout: 30s`, and `tls_config` with the VMS CA (`ca_file`)
rather than `insecure_skip_verify` where possible. One job per set. Custom per-tenant labels
(up to ten, e.g. `customer`) are added with `/tenants/metric_labels/` and
`/tenants/{id}/metric_label_values/` (changes: ask first). Grafana dashboards:
`github.com/vast-data/vast-grafana-dashboards` (KB **VAST Grafana Dashboard**).

## Client-side metrics

To see per-job/per-process NFS I/O from Linux clients (e.g. by `SLURM_JOB_ID`), VAST's
`vnfs-collector` (github.com/vast-data/vnfs-collector) sends client eBPF data into a VAST
Database on the cluster; enable it under Analytics → Client Metrics (`/tenants/{id}/client_metrics/`
in the 5.5.3 spec). Setup creates a bucket, user, identity policy and keys: KB **Client Metrics** (5.5).

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Only the last metric came back | One-value-per-key client collapsed repeated `prop_list` | Repeat the parameter (helper `query`, vastpy-cli, curl) |
| `metrics not available` / `property_error` | Name not valid for that object type or this release | `vast_monitor.py metrics <word>`; copy from a predefined monitor |
| Huge, slow response | No `prop_list` | Always pass the metrics you need |
| Numbers 1000× off | Raw units differ from catalog `units` (5.5.3: bytes/s, µs) | Cross-check with the cluster object (`bw` vs `bw_mb`) or Web UI |
| Values shifted between columns | Response column order ≠ request order | Map by the response `prop_list` |
| A user/host missing from some samples | Top-N metrics keep only the top actors per sample | Treat absence as "not in top N", not zero |
| `granularity=minutes` gives 5-minute rows | That is its meaning | Use `seconds` for raw ~10 s samples over short windows |
| Prometheus 404 on a set named in the KB | KB lists `basic_no_views`; the 5.5.3 cluster serves `basic` (404 for `basic_no_views`) | `vast_api.py spec paths prometheusmetrics` on the cluster |
