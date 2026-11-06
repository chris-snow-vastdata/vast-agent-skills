---
name: vast
description: "Configure, operate and build on a VAST Data cluster through its VMS REST API on any VAST release: connecting and logging in, tenants and VIP pools, views and view policies (NFS, SMB, S3, block, quotas, QoS, CSI), users, groups, AD/LDAP, S3 keys and policies, roles, snapshots and replication, health, capacity and performance metrics, alarms, VAST Database (vastdb SDK, Trino, Spark), the Kafka-compatible VAST Event Broker, and VAST DataEngine triggers, functions and pipelines. Finds the right endpoint and fields from the cluster's own spec and the VAST knowledge base, and asks before changing anything. Use for any task or question about a VAST cluster."
---

# VAST: connect, discover, change safely

Everything on a VAST cluster (views, tenants, users, snapshots, databases, DataEngine...)
is managed by the **VMS** (VAST Management System) through a REST API at
`https://<VMS address>/api/...`, the same address as the Web UI. The API differs between
releases, so **work out what this cluster supports from the cluster itself and from the docs
for its release**, not from memory.

## The helper

`scripts/vast_api.py` (Python 3.8+, standard library only) does the discovery and safe calls.
It reads the same environment variables as `vastpy-cli`:

```bash
export VMS_ADDRESS=vms.example.com      # VMS host/IP (the Web UI address)
export VMS_USER=admin VMS_PASSWORD=...  # a VMS manager login, or: export VMS_TOKEN=<api token>
export VMS_TENANT_NAME=t1               # only for tenant-scoped work (tenant admins, DataEngine)
export VMS_CERT_FILE=/path/ca.pem       # or VMS_INSECURE=1 for a self-signed lab certificate
```

Ask the user for the address and a login; never guess credentials. Prefer an API token for
anything long-running.

**Keep the password out of the conversation.** Don't ask the user to paste it, and don't type it
into a command or file yourself. Have the user store it once, in a file only they can read, with
nothing echoed or kept in shell history:

```bash
umask 077; read -rs -p "VMS password: " P; printf 'VMS_PASSWORD=%s\n' "$P" > ~/.vms.env; unset P
```

Then load it for each run without reading it, `set -a; . ~/.vms.env; set +a; scripts/vast_api.py ...`,
and ask the user to delete the file when the work is done. Treat a generated secret key the same
way: write it straight to a 0600 file and report only that it was written.

| Step | Command |
|---|---|
| Which release? | `vast_api.py version` |
| Docs for that release | `vast_api.py kb search 'snapshot' --version 5.5` then `vast_api.py kb get <url>` |
| Which endpoints exist | `vast_api.py spec paths 'snapshot'` |
| What a call takes | `vast_api.py spec show /snapshots/ post` |
| A schema, its fields and enums | `vast_api.py spec model View` |
| Where a field/value lives | `vast_api.py spec search 'delegation'` |
| Read | `vast_api.py get views path=/data fields=id,path,protocols` |
| Change (dry run) | `vast_api.py call PATCH /views/12/ --data '{"...": "..."}'` |
| Change (for real, after the user says yes) | the same with `--yes` |

`spec` caches the cluster's spec per build under `~/.cache/vast-skills/`; `spec fetch` refreshes it.
Add `--dataengine` to `spec` (and use `de-get` / `call ... --dataengine`) for the DataEngine API.

## How to do any VAST task

1. **Version**: `vast_api.py version` (name, `sw_version`, `build`).
2. **Docs**: search the KB for the task with `--version <major.minor>`. Product docs describe
   the objects and their rules; the "API Reference" pages describe each call. Pages without a
   version tag may apply to older releases: prefer the tagged ones.
3. **Exact API**: `spec search` / `spec show` / `spec model` on *this* cluster. Use only field
   names and enum values that appear there. If the KB and the spec disagree, the spec is what
   this cluster accepts.
4. **Take stock (read-only)**: list what already exists that the task touches (`get ...`).
5. **Plan, then ask once**: tell the user what exists, what you'll create or change (names,
   the exact requests), and what it affects. Wait for a yes.
6. **Apply step by step**, reading each object back before the next one. Stop at the first error
   and explain it: VMS errors are usually specific (`{"detail": "...", "code": "..."}`).
7. **Report** exactly what was created or changed, so the user can undo it.

## Connecting

**Base URL and versions** (KB "Getting Started", 5.5 API): `https://VMS/api/<version>/<object>/`.
Versions map to releases: `v1` ≤4.3, `v2` ≤4.4, `v3` ≤4.7, `v4` ≤5.0, `v5` ≤5.1, `v6` ≤5.2,
`v7` ≤5.3, `v8` ≤5.5. **A request without a version goes to the oldest API**, so always give one:
`latest` (what the helper and `vastpy` use) or the release's own (`v8` on 5.5) for scripts that
must keep behaving the same after an upgrade. The KB's "Breaking Changes" page lists differences.

**Authentication** (all from the KB, checked on 5.5.3):

| Method | How | Notes |
|---|---|---|
| Basic | `-u user:password` | All releases. Simplest for one-off calls. |
| API token (5.3+) | `POST /api/<v>/apitokens/` `{"name":..., "owner":..., "expiry_date":"30D"}` then `Authorization: Api-Token <token>` | Shown once. Default limit 5 per user. Revoke: `PATCH /apitokens/<id>/revoke`. Needs *create* on the *Security* realm. |
| JWT | `POST /api/token/` `{"username","password"}` → `access` (1 h), `refresh` (24 h); `Authorization: Bearer <access>`; renew with `POST /api/token/refresh/` | Refresh on a 401 and retry. |

**Tenant context**: tenant admins and application users add `X-Tenant-Name: <tenant>`.
A cluster admin acting inside a tenant (needed for the DataEngine API) must use a **JWT plus
`X-Tenant-Name`**: basic auth with that header is rejected as "Invalid username/password" and a
JWT without it gets "No tenant was provided in request" *(seen on 5.5.3)*. The helper does this.

**Certificates**: VMS often has a self-signed certificate. Prefer the user's CA bundle
(`VMS_CERT_FILE`, `curl --cacert`); use `VMS_INSECURE=1` / `curl -k` only when they accept it.
mTLS can be required by VMS (`/vms/<id>/set_client_certificate/`): then present a client cert.

**Permissions**: calls run with the RBAC rights of the login (*realms* such as Security,
Logical, Database, Events; actions create/view/edit/delete). A 403 means the login lacks the
right, not that the call is wrong: tell the user which realm it needs.

## Working with the API

- **Lists**: `page_size` and `page` paginate (`count`, `next`, `previous`, `results`); without them
  most lists return a plain array. Some endpoints always paginate or cap at 1000 (KB:
  "Enforced Pagination"). Follow `next` until it is null. `fields=a,b` trims the response.
- **Filters**: most lists filter by field (`views/?path=/data`, `?tenant_id=3`, `?name=x`);
  check with `spec show <path> get`. Filter results again client-side if exactness matters
  (some filters are prefix or substring matches). A filter a list doesn't support is ignored,
  and the call returns every row *(seen on 5.5.0)*. So always re-check the rows yourself before
  acting on one, and above all before a delete.
- **Objects are referenced by `id`** in most calls (e.g. `policy_id`, `tenant_id`), by name in
  some; `spec model` shows which.
- **Async work**: long operations (compute clusters, replication, upgrades, some deletes) run as
  VMS tasks. Follow them in `GET /vtasks/?page_size=20` (`state`, `messages`), or poll the
  object's own `state`/`status` field until it settles. Don't fire the next dependent call early.
- **Errors**: 400 with `detail` explains which field or rule failed; 404 can also mean "not
  visible in this tenant"; 409/503 from DataEngine often wrap a VMS rule (read `detail` fully).
- **Idempotence**: look the object up by name/path first; create only if missing. Re-running a
  plan must not create duplicates.

## Other ways in (all public)

| Tool | Use it for |
|---|---|
| Web UI (`https://VMS`) | Show the user the result; some settings are easier there. |
| REST API docs on the cluster | `https://VMS/docs/` in a browser (this release's reference). |
| `vastpy` / `vastpy-cli` (`pip install vastpy`) | VMS REST from Python or the shell, any release: `vastpy-cli get views path=/data`. Defaults to `latest`. |
| Terraform provider `vast-data/vastdata` | Declarative, repeatable configuration. |
| `vast-admin-mcp` (`pip install vast-admin-mcp`) | An MCP server exposing cluster listing/metrics (read-only by default). |
| VAST CLI (`vcli`) on a CNode | Admin shell; KB documents each command per release. |
| `vastdb` SDK, `vastde` CLI, `vast-csi` | See `references/database.md`, `references/dataengine.md`, `references/views-protocols.md`. |

## Areas: read the one(s) the task needs

This file is the foundation for every task. For the task's area, read the matching file in
`references/` (and only what it points to); a task that spans areas (e.g. a DataEngine pipeline:
views, identity, event broker, DataEngine) reads each of them.

| When the task is about | Read |
|---|---|
| tenants, tenant admins, VIP pools, DNS, VLANs, BGP, tenant-wide QoS | `references/tenants-network.md` |
| views, view policies and flavors, NFSv3/NFSv4, SMB, S3 buckets, quotas, QoS policies, block (NVMe/TCP), the CSI driver | `references/views-protocols.md` |
| local users and groups, AD/LDAP/NIS, S3 keys, identity and bucket policies, managers, roles and realms, certificates, encryption, auditing | `references/identity-access.md` |
| snapshots, protection policies, replication and failover, clones, S3 versioning, object lock, indestructibility | `references/data-protection.md` |
| health, capacity, performance metrics, top clients, alarms and events, notifications, Prometheus, support bundles, tasks, upgrades (status) | `references/monitoring.md` |
| VAST Database: prerequisites, schemas and tables, the `vastdb` SDK, Trino, Spark | `references/database.md` |
| the VAST Event Broker (Kafka): broker views, topics, Kafka clients, TLS/SASL, ACLs | `references/event-broker.md` |
| VAST DataEngine: enablement, compute, registries, source views, triggers, functions, pipelines, troubleshooting | `references/dataengine.md` |

Scripts (Python 3.8+, standard library only, run from this folder): `scripts/vast_api.py`
(everything above) and `scripts/vast_monitor.py` (read-only health report, metric queries,
top talkers; see `references/monitoring.md`).

Verified: VAST 5.5.3 (the helpers run live; specs and KB 5.5 read). Each file in `references/`
ends with its own Verified line.
