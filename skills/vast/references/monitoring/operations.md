# Operations: support bundles, call home, VMS tasks, upgrades, AI assistants

Checked on VAST 5.5.3 (spec + live read-only GETs) and the KB 5.5 pages named. Nothing here was
created or changed on a cluster while writing it: the POST/PATCH examples are for showing the user.

## Contents
- [Support bundles](#support-bundles)
- [Call home and Uplink](#call-home-and-uplink)
- [VMS tasks (Activities)](#vms-tasks-activities)
- [Upgrades: read-only status](#upgrades-read-only-status)
- [Audit logs (pointer)](#audit-logs-pointer)
- [vast-admin-mcp: monitoring through an AI assistant](#vast-admin-mcp)

## Support bundles

KB **Sending a Support Bundle via VAST Web UI**, **Creating a Support Bundle via CLI**,
**What is Collected in Each Support Bundle Preset?**, API reference **Create a Support Bundle** (5.5).

Read first:

```bash
vast_api.py get supportbundles              # existing bundles and their state
vast_api.py get supportbundlesqueue         # bundles waiting to run (5.5 queues requests)
vast_api.py get callhomeconfigs fields=id,upload_via_vms,support_channel,obfuscated
```

Create (a change: it runs collection on the nodes and uses local disk; ask first, and ask the
support engineer which preset and time window they want). `POST /supportbundles/` fields
*(5.5.3 spec)*:

| Field | Notes |
|---|---|
| `prefix` (required) | Label in the file name: letters, digits, `_`, `-`, ≤64 chars. Name becomes `bundle-<preset>-<cluster>-<prefix>-<timestamp>.tar`. |
| `preset` | 5.5.3 spec enum (lower case): `standard` (default), `debug`, `micro`, `mini`, `performance`, `management`, `traces_and_metrics`, `nfs`, `nfs4`, `smb`, `s3`, `estore`, `raid`, `hardware`, `permission_issues`, `rca`, `dr`, `metadata`. The KB API page shows them upper case and a shorter list: use the spec's values. |
| `start_time`, `end_time` | Keep the window as short as support needs (size). The Web UI page says UTC+0; the API reference text says "UTC+3": send explicit `Z` timestamps and confirm the range in the result. |
| `obfuscated` | Hashes file/dir names, IPs, host and user names, MACs; non-text data is dropped. |
| `cnodes_only`, `dnodes_only`, `cnode_ids`, `dnode_ids`, `vippool_ids`, `vip_ids` | Narrow collection (comma-separated id strings). |
| `upload_via_vms`, `delete_after_send`, max size/split settings | Upload behaviour; see `spec show /supportbundles/ post`. |

```bash
vast_api.py call POST /supportbundles/ --data '{"prefix": "case-12345", "preset": "standard",
  "start_time": "2026-01-15T12:00:00Z", "end_time": "2026-01-15T14:00:00Z", "obfuscated": false}'   # dry run
```

Then follow it: `vast_api.py get supportbundles/<id>` (`state`) and `vtasks`.
Send it to VAST: `PATCH /supportbundles/<id>/upload/` (uses the call home S3 settings or the
`bucket_name`/`access_key`/`secret_key` given). Download it yourself: `GET /supportbundles/<id>/download/`
(binary). Uploading bundles is blocked during an upgrade (KB).

## Call home and Uplink

KB **Configuring Call Home Settings**, **Overview of Uplink**, **How to Allow VAST Call Home and
Support Web Pages Through a Firewall**.

Call home sends logs, metrics (CSV) and heartbeats to VAST Support over HTTPS (443), optionally via
a proxy. Read the settings (don't echo `aws_s3_sk`, `proxy_password`, `cloud_api_key`):

```bash
vast_api.py get callhomeconfigs fields=id,log_enabled,log_interval,cloud_enabled,cloud_registered,proxy_host,proxy_port,proxy_scheme,verify_ssl,support_channel,obfuscated,upload_via_vms,customer,site,location
```

Field meanings (KB API reference): `log_enabled`/`log_interval` (system state data to support),
`cloud_enabled`/`cloud_registered` (Uplink, VAST's SaaS portal), `support_channel` (lets VAST
Support trigger collections remotely), `obfuscated`, `proxy_*`, `verify_ssl`.
Changes: `PATCH /callhomeconfigs/<id>/`; test: `PATCH /callhomeconfigs/<id>/send/` (sends a
real message). After a test, look for the VMS task `send_interactive_callhome` reaching
`COMPLETED` with "Callhome bundle sent" in its messages (KB).

## VMS tasks (Activities)

`/vtasks/` is the Web UI's Activities page: long operations (deploys, expansions, compute
clusters, replication setup, upgrades, call home sends, validations).

```bash
vast_api.py get vtasks page_size=20                       # newest first
vast_api.py get vtasks state=RUNNING
vast_api.py get vtasks state=FAILED page_size=50
vast_api.py get vtasks/<id>                              # messages[] is the step log
```

Fields seen on 5.5.3: `id`, `name`, `state`, `messages` (timestamped lines), `number_of_issues`,
`start_time`, `end_time`, `execution_time`, `timeout_in_seconds`, `info`.
`state` filter accepts `RUNNING`, `COMPLETED`, `FAILED` on 5.5.3 (others are rejected with
"Select a valid choice"). Retrying (`PATCH /vtasks/<id>/retry/`) or editing tasks is for root/support
users (spec) and only on VAST Support's advice.

## Upgrades: read-only status

**Upgrading the cluster is out of scope for this file.** It is a long rolling operation that
restarts every node and blocks many admin operations while it runs (KB **Upgrading Your VAST
Cluster**, 5.5: non-disruptive for client I/O, but blocks VIP pool changes, user/group/key
changes, node activation, support bundle uploads and more). Plan it with VAST Support and the
release notes, and run it from the Web UI or VAST CLI following that KB page. Don't call
`/clusters/{id}/upgrade*`, `/stop_upgrade/`, `/upgrade_ssd/` and similar endpoints on behalf of the user.

Safe status reads:

```bash
vast_api.py get clusters fields=name,sw_version,build,upgrade_state,upgrade_phase,upgrade_progress,leader_upgrade_state,available_upgrade_version
vast_api.py get clusters/<id>/pre_upgrade_validation_exceptions
vast_api.py get vtasks state=RUNNING
vast_api.py get cnodes fields=name,os_version,state       # node OS versions (KB "Check VAST OS Versions")
```

`upgrade_progress` holds `cnodes` and `dnodes` `{done, total}`. Pre-upgrade validations
(Web UI "Test Validations", CLI `cluster run-upgrade-validations`) are also run as tasks,
without upgrading; still a change request, so ask.

## Audit logs (pointer)

Two kinds, both owned by `references/identity-access.md`:
- **VMS/management audit** (who changed what): events with `event_type=SECURITY` and VMS audit
  sent to syslog (`syslog_vms_audit`, `syslog_secure_audit`, `syslog_shell_audit`,
  `syslog_ipmi_audit` in `eventdefinitionconfigs`).
- **Protocol audit** (file/object operations): `/clusters/{id}/auditing/`, and the audit
  database read through `/vastauditlog/query_data/`, `/vastauditlog/columns/`,
  `/vastauditlog/aggregate/`, `/vastauditlog/stats/` (5.5.3 spec). KB **Protocol Auditing** (5.5).
  KB **Finding Hot Directories by IOPS and Capacity Using the VAST Audit Database** is a good
  "who is hammering which directory" recipe once auditing is on.

## vast-admin-mcp

`vast-admin-mcp` (github.com/vast-data/vast-admin-mcp, KB **VAST Admin MCP**) is an MCP server
that lets an MCP-capable assistant answer monitoring questions ("critical unacknowledged alarms
on my clusters", "top views by capacity", "cnode performance last hour") across several clusters.

- Requires VAST 5.2+, Python 3.10+ (or Docker image `vastdataorg/vast-admin-mcp`).
- `pip install vast-admin-mcp`, then `vast-admin-mcp setup` (asks for address, user, password,
  tenant; stores the password in the system keyring or an encrypted file), then
  `vast-admin-mcp mcpsetup <assistant>` prints the client config (`cursor`, `claude-desktop`,
  `vscode`, `windsurf`, `gemini-cli`).
- **Read-only by default.** `--read-write` enables create tools (views, snapshots, clones,
  quotas). Keep monitoring set-ups read-only; use a VMS user with read-only roles too.
- Tools (README): `list_clusters_vast`, `list_performance_vast` (wraps `/monitors/ad_hoc_query/`
  for `cluster`, `cnode`, `host`, `user`, `vippool`, `view`, `tenant`; view windows capped at 8 h),
  `query_users_vast`, plus `list_<name>_vast` tools generated from its YAML template
  (alarms, events, cnodes, dnodes, views, tenants, quotas, support bundles...). Run
  `vast-admin-mcp --help` for the installed version's commands; don't guess flags.
