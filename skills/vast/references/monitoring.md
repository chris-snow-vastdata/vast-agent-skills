# VAST monitoring, health and operations

Builds on `SKILL.md`: connect and discover with `scripts/vast_api.py`
(set `VMS_ADDRESS` and a login as described there). This area adds
`scripts/vast_monitor.py` (Python 3.8+, standard library, **GET only**) for a health report,
metric queries with repeated `prop_list`, metric-name search and top talkers. It reads the same
environment variables.

Almost everything here is a read. The few changes (notification settings, webhooks, thresholds,
acknowledging alarms, creating support bundles) need the user's yes on the exact request first.

## Mental model

```
Hardware & services ── state fields on /clusters/ /vms/ /cnodes/ /dnodes/ /dboxes/ /ssds/ /nvrams/ /nics/ ...
        │ VMS samples properties (~10 s) ─────────► metrics  (/metrics/ catalog → /monitors/ queries,
        │                                                      /monitors/topn/, /api/prometheusmetrics/*)
        └ event definitions (/eventdefinitions/) watch properties
              │ trigger ─► events (/events/, 30 days) ─► alarms (/alarms/, MINOR|MAJOR|CRITICAL,
              │                                                  clear themselves when fixed)
              └ actions (/eventdefinitionconfigs/: SMTP, email, syslog; /webhooks/)
Operations: /vtasks/ (Activities), /supportbundles/, /callhomeconfigs/, cluster upgrade_* fields
```

- **State** answers "is it healthy now": object `state` fields plus active alarms.
- **Metrics** answer "how busy / how full over time": names come from the cluster's own catalog
  (`/metrics/`), queried with `/monitors/ad_hoc_query/` or saved monitors.
- **Alarms** are the cluster's own judgement; their definitions say what is watched and at what threshold.

## First steps on any release

1. `vast_api.py version`: note the release (e.g. 5.5).
2. KB for that release: `vast_api.py kb search 'Alarms|Analytics|Prometheus|Support Bundle' --version 5.5`.
3. Spec: `vast_api.py spec paths 'monitor|metric|alarm|event|prometheus|capacity|vtask|supportbundle'`,
   `spec model Cluster`, `spec model EventDefinitionConfig`. Use only names that exist there.
4. Metric names: `python3 scripts/vast_monitor.py metrics '<word>'` or copy a predefined monitor's
   `prop_list` (`vast_api.py get monitors fields=id,name,object_type,prop_list`).

Detail lives in the references:
- `references/monitoring/health-capacity.md`: every health object and state field, capacity definitions, where capacity goes.
- `references/monitoring/metrics.md`: metric catalog, ad hoc/monitor queries, response format, top talkers, Prometheus.
- `references/monitoring/alerting.md`: events, alarms, event definitions, email/syslog/webhooks, SNMP, what each change does.
- `references/monitoring/operations.md`: support bundles, call home, VMS tasks, upgrade status, audit pointer, vast-admin-mcp.

## Workflow: health check report

1. Run `python3 scripts/vast_monitor.py health` (or `--json`). It reads `/clusters/`, `/vms/`,
   every hardware list, `/alarms/` and failed `/vtasks/`, and prints only fields this release has.
2. Read it in this order:
   - Cluster `state` (`ONLINE` when good, seen on 5.5.3), `leader_state`, VMS `state` (`CLUSTERED`).
   - Data protection: `ssd_raid_state`, `nvram_raid_state`, `memory_raid_state` (`HEALTHY`),
     `raid_rebuild_progress`; a rebuild in progress means reduced redundancy until it finishes.
   - Components whose `state` is not `ACTIVE`/`HEALTHY`, or `enabled: false`.
   - Active alarms by severity, then their `alarm_message` and the definition's `user_action`
     (`vast_api.py get eventdefinitions name=<event_name> fields=name,user_action`).
   - Capacity: `physical_space_in_use_percent` against the alarm thresholds (5.5.3 defaults 85/90/95 %).
   - Changes in progress: `upgrade_state`/`upgrade_phase`, `expansion_state`, running `vtasks`.
3. Report: overall verdict, each problem with object, severity, since when, and suggested next step
   (KB page or VAST Support). Don't acknowledge or clear alarms as part of a report.

KB: **Monitoring**, **Dashboard**, **Managing Hardware**, **Alarms and Events** (5.5).

## Workflow: what is using capacity

1. Cluster totals: `vast_api.py get clusters fields=physical_space_in_use_percent,usable_capacity_tb,free_usable_capacity_tb,logical_space_in_use_tb,free_logical_space_tb,drr_text`.
   Explain physical vs usable vs logical (`references/monitoring/health-capacity.md`) before quoting "free".
2. Biggest views: `vast_api.py get views fields=path,tenant_name,logical_capacity,physical_capacity ordering=-logical_capacity page_size=20`.
3. Per tenant: ad hoc `object_type=tenant` with `TenantMetrics,logical_capacity` and `TenantMetrics,drr`, or `GET /tenants/top_tenants/`.
4. Inside a path: `vast_api.py get capacity path=/some/dir type=unique tenant_id=<id>` (`unique` = space freed if deleted); note the response `time`.
5. Quotas close to their limit: `vast_api.py get quotas fields=name,path,used_capacity,hard_limit,percent_capacity,pretty_state`.
6. Trend: `python3 scripts/vast_monitor.py query cluster --prop Capacity,physical_space_in_use --time-frame 30D --granularity days --aggregation max`.
7. Report the top consumers, their DRR, snapshot usage (tenant `snapshot_aggregated_usage`), and
   growth per day. Deleting data or snapshots is the user's decision, through the relevant area (`SKILL.md` lists them).

KB: **Understanding VAST Capacity**, **Capacity Overview**, **Viewing Capacity Analytics**, **Capacity Analysis with vastpy-cli**.

## Workflow: top clients, users and views by IOPS or bandwidth

1. Right now: `python3 scripts/vast_monitor.py top --kind client --by iops` (kinds: `user`,
   `client`, `view`, `vip`, `vippool`, `cnode`, `volume`; by: `iops`, `bw`, `md_iops`, `latency`, `qos_wait_time`).
2. Over a period: `python3 scripts/vast_monitor.py query host --prop TopNMetrics,iops --prop TopNMetrics,bw --time-frame 1h`
   (use `user` for users), then map `object_id` to names with `vast_api.py get monitoredhosts`
   (or `monitoredusers`, `monitoredviews`). Aggregate per object client-side (sum or max over rows).
3. Per view: `query view --prop ViewMetrics,read_iops__time_avg --prop ViewMetrics,write_bw__time_avg`.
4. Report a ranked table with the time window and units (check units: `references/monitoring/metrics.md`).

KB: **Top Actors**, **Data Flow Analytics** (5.5).

## Workflow: why is it slow?

1. Is the cluster degraded? Run the health check: failed or rebuilding components, alarms, a
   running upgrade or expansion, `burst_mode_state`.
2. Is it the whole cluster or one workload? Compare cluster latency over time:
   `query cluster --prop ProtoMetrics,proto_name=ProtoCommon,latency --prop ProtoMetrics,proto_name=ProtoCommon,iops --time-frame 6h --granularity minutes --aggregation avg`,
   then per protocol (`NFSCommon`, `NFS4Common`, `SMBCommon`, `S3Common`, `BlockCommon`).
3. Uneven CNodes? Same `ProtoMetrics` names with `query cnode`: one hot CNode often means VIP
   distribution or a single client pinned to one VIP (`top --kind vip`).
4. QoS throttling? `query view --prop ViewMetrics,qos_wait_for_budget_time__avg` and
   `top --kind user --by qos_wait_time`. Non-zero waits mean a QoS policy is limiting it
   (KB **Monitoring QoS Performance**); policy changes belong to `references/views-protocols.md`.
5. One noisy client or user? Top talkers workflow for the same window.
6. Capacity near full or many handles in use (`used_handles_percent`)? Both slow writes (KB
   **Cluster Available Capacity Alerts**, **Cluster Handles Alerts**).
7. Nothing on the cluster side? It is likely client or network: point to KB **VAST NFS
   Performance Troubleshooting Guide** and client metrics (`vnfs-collector`).
8. If support is needed: a `performance` preset support bundle covering the slow window (below).

## Workflow: set up alerts (email, syslog, webhook) and Prometheus

1. Read current settings: `vast_api.py get eventdefinitionconfigs` (don't echo `smtp_password`)
   and `vast_api.py get webhooks`.
2. Ask the user for the destination: SMTP host/port/TLS/sender/recipients, syslog host/port/`udp|tcp`,
   or the webhook URL, method, headers and payload template.
3. Show the exact request(s) as dry runs, e.g.
   `vast_api.py call PATCH /eventdefinitionconfigs/<id>/ --data '{"syslog_host": "<syslog-host>", "syslog_port": 514, "syslog_protocol": "udp"}'`.
   Field list, webhook variables and an example payload: `references/monitoring/alerting.md`.
4. After a yes, apply with `--yes`, read the object back, and (another yes) send a test:
   `PATCH /eventdefinitionconfigs/<id>/test/` or `PATCH /eventdefinitions/<id>/test/`.
5. Optional: tune which alarms notify (`PATCH /eventdefinitions/<id>/`: `email_recipients`,
   `webhooks`, `alarm_only`, thresholds). Show current vs new values first.
6. **SNMP**: not configurable in the 5.5 API or KB. Offer syslog, a webhook into the NMS, or
   Prometheus alarms instead; re-check `spec search snmp` on newer releases.
7. **Prometheus**: give the user a scrape job per needed set (`/api/prometheusmetrics/views`,
   `/tenants`, `/alarms`, `/vms_state`, ...; list with `vast_api.py spec paths prometheusmetrics`),
   `scheme: https`, port 443, a read-only VMS user or API token, `scrape_interval: 1m`,
   `scrape_timeout: 30s`. Avoid `/all` on large clusters. Grafana dashboards:
   github.com/vast-data/vast-grafana-dashboards.

KB: **Managing Alarms and Events** (Default Notification Actions), **Sending Alarms to a Syslog
Server**, **Managing Webhooks**, **Exporting Metrics to Prometheus** (5.5).

## Workflow: collect a support bundle

1. Ask what VAST Support asked for: preset, time window (keep it short), obfuscation, nodes.
2. Read: `vast_api.py get supportbundles`, `vast_api.py get supportbundlesqueue`, and whether an
   upgrade is running (bundle upload is blocked during upgrades).
3. Check the preset values on this cluster: `vast_api.py spec show /supportbundles/ post`
   (5.5.3: lower case `standard`, `performance`, `nfs`, `smb`, `s3`, `hardware`, `rca`...).
4. Dry run, then after a yes: `vast_api.py call POST /supportbundles/ --data '{"prefix": "case-<n>", "preset": "standard", "start_time": "<ISO>Z", "end_time": "<ISO>Z"}' --yes`.
   Collection runs on the nodes and uses local disk; it can take a while.
5. Follow `vast_api.py get supportbundles/<id>` (`state`) and `vtasks`. Upload to VAST
   (`PATCH /supportbundles/<id>/upload/`, another yes) or download (`GET /supportbundles/<id>/download/`).

KB: **Sending a Support Bundle via VAST Web UI**, **What is Collected in Each Support Bundle Preset?**,
**Configuring Call Home Settings** (5.5). Details: `references/monitoring/operations.md`.

## Workflow: check a running task or upgrade

- `vast_api.py get vtasks state=RUNNING`, then `vast_api.py get vtasks/<id>`: read `messages`
  (timestamped steps), `number_of_issues`, `state` (`RUNNING`, `COMPLETED`, `FAILED` on 5.5.3).
- Upgrade status: `vast_api.py get clusters fields=sw_version,build,upgrade_state,upgrade_phase,upgrade_progress`.
- **Starting, stopping or resuming an upgrade is out of scope and disruptive** (rolling node
  restarts; many admin operations blocked while it runs). Point to KB **Upgrading Your VAST
  Cluster** for the release and VAST Support; don't call the `/clusters/{id}/upgrade*` endpoints.

## Monitoring through an AI assistant (vast-admin-mcp)

`vast-admin-mcp` exposes clusters, alarms, events, hardware and performance (it wraps
`/monitors/ad_hoc_query/`) as MCP tools for Cursor, Claude Desktop, VS Code and others.
`pip install vast-admin-mcp`, `vast-admin-mcp setup`, `vast-admin-mcp mcpsetup <assistant>`.
Read-only by default; keep it that way for monitoring (no `--read-write`). VAST 5.2+.
See `references/monitoring/operations.md` and KB **VAST Admin MCP**.

## Pitfalls

| Symptom or error | Cause | Fix |
|---|---|---|
| Only one metric returned though several were asked | `prop_list` must be repeated; one-value-per-key clients (including `vast_api.py get`) keep the last | `vast_monitor.py query --prop A --prop B`, `vastpy-cli ... prop_list=A prop_list=B`, or curl |
| `{"detail": "metrics not available", "code": "property_error"}` | Metric name not valid for that object type/release *(5.5.3)* | `vast_monitor.py metrics <word>`; copy from a predefined monitor |
| `Invalid time frame: 10x` | Units are `m h D W M Y` | e.g. `10m`, `7D` |
| Ad hoc query without `prop_list` is huge | It returns every metric for the type | Always pass `prop_list` |
| Numbers look 1000× off | Raw values on 5.5.3 were bytes/s and µs though the catalog said MB/s and ms | Cross-check with cluster `bw` vs `bw_mb`, `latency` vs `latency_ms`, or the Web UI |
| Columns don't match what you asked | Response `prop_list` order can differ | Map columns by the response `prop_list` |
| An events filter "did nothing" | Unknown filter names are ignored silently *(5.5.3)* | Check `count`; use `timestamp__gte`, `severity`, `object_type`, `event_type` |
| Prometheus 404 for `basic_no_views` | KB 5.5 names it; 5.5.3 serves `basic` | `vast_api.py spec paths prometheusmetrics` |
| No alert emails | No `smtp_host`, `disable_actions: true`, or no recipients | Read `eventdefinitionconfigs`; test after a yes |
| Alarms "disappeared" | They clear when the condition clears; or someone acknowledged or cleared them | Check `/events/` for the history |
| `/capacity/` shows zeros | Capacity estimation hasn't scanned yet | Use view `logical_capacity`; check the response `time` |
| 403 on a read | The login lacks view rights on that realm (e.g. Events, Hardware) | Ask for a read-only role with those realms |

## Related areas

`SKILL.md` (connecting, spec, KB), `references/views-protocols.md` (views, quotas, QoS policies),
`references/tenants-network.md` (VIP pools, tenants), `references/identity-access.md` (audit logs, users, roles,
API tokens for Prometheus), `references/data-protection.md` (snapshots and replication monitoring),
`references/database.md` (VAST Database monitoring), `references/dataengine.md`.

Verified: VAST 5.5.3 (spec read, KB 5.5 pages, live read-only calls of every GET shown, including
ad hoc and monitor queries, top-N, Prometheus sets and the helper script). No changes were made
to a cluster; POST/PATCH examples were checked against the spec only.
