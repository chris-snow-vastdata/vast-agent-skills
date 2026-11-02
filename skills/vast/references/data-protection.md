# VAST data protection: snapshots, replication, immutability

Builds on `SKILL.md` (connection, helper, safe-change rules): read it first. The
helper is `scripts/vast_api.py`; every command below is that script.

## Mental model

```
                      protection policy  ──(target_object_id)──▶  replication peer  ─▶ remote cluster
                      (schedule "frames",                          (native = async/sync,
                       keep-local, keep-remote,                     needs a REPLICATION VIP pool
                       prefix, indestructible)                      on BOTH clusters)
                              │
 path in the element store ◀──┤ protected path (source_dir [+ target_exported_dir on the peer])
                              │      └─ one or more replication streams (one per destination)
                              ▼
                        snapshots  ──▶ restore points on the peer ──▶ remote snapshots
                          │   (shown in <dir>/.snapshot/<name>)
                          ├─ copy back from .snapshot (client side, non-destructive)
                          ├─ clone to a new path (global snapshot clone, non-destructive)
                          └─ fast restore of the protected path (REPLACES the path)
```

- **Snapshot**: read-only point-in-time image of a directory (or bucket path). Manual or made
  by a protection policy. Lives under the hidden `.snapshot` directory of the path it captured.
  Does not count against quota; holds on to overwritten/deleted blocks (cluster "auxiliary used").
- **Protection policy**: reusable schedule + retention. `clone_type` (5.5 API) is `LOCAL`
  (local backup), `NATIVE_REPLICATION` (async replication to a VAST peer) or
  `CLOUD_REPLICATION` (backup to an S3 replication peer). Changing it changes every protected
  path that uses it; a protected path's policy cannot be swapped after creation (KB), so use one
  policy per protected path when they need to differ.
- **Protected path**: applies a policy to a directory. A remote protected path has one stream per
  destination; the peer mirrors it, with a role per cluster (Source, Destination, Standalone).
- **Replication peer** (API object `nativereplicationremotetargets`): a connection to another
  VAST cluster, made on the source, mirrored on the peer. **S3 replication peer**
  (`replicationtargets`): an AWS or S3-compatible bucket for backup to S3.
- **Indestructibility**: one cluster-wide lock (`/indestructibility/`). Indestructible snapshots and
  policies can't be deleted or shortened until VAST Support helps unlock it (60 minutes).
- **S3 object protection** is set on the bucket's **view**: `s3_versioning`, `locking` (object
  lock/WORM, implies versioning), retention mode and default retention, or the separate
  `is_indestructible_object_enabled` mode. Lifecycle rules (`/s3lifecyclerules/`) expire data.

Order to build: (replication only) VIP pool with role REPLICATION on each cluster → replication
peer → protection policy → protected path → (optionally) views with global sync on both sides.

## First: version, docs, exact API

```bash
vast_api.py version                                   # release, e.g. 5.5.x
vast_api.py kb search 'snapshot|protected path|replication' --version 5.5
vast_api.py spec paths 'snapshot|protect|replicat|indestruct|lifecycle|globalsnap'
vast_api.py spec model ProtectedPath                  # fields this cluster accepts
vast_api.py spec search retention                     # where a field lives (View, Cluster...)
```

The served 5.5 spec lists fields but **not** the bodies of action endpoints (`restore`,
`commit`, `replicate_now`, `force_failover`, `add_stream`...: they echo the whole model) and has
few enums. For those, use the release's KB "API Reference", the cluster's `https://VMS/docs/`,
or the VAST CLI page of the same name (the CLI flag names track the API fields), and prefer the
Web UI or VAST CLI when the body can't be confirmed. Details per object:
[references/data-protection/api-objects.md]()).

## Impact of each change (tell the user before doing it)

| Operation | Impact |
|---|---|
| Delete a snapshot | Permanent; frees space only if no other snapshot holds the blocks. Indestructible ones are refused. |
| Change a protection policy (schedule, retention) | Applies to **every** protected path using it; shorter keep-local/keep-remote prunes existing snapshots. |
| Delete a protected path | Stops snapshots/replication; can't be resumed; recreating it does a **full initial sync**. Existing snapshots and remote restore points stay. |
| Deactivate (pause) a protected path | Snapshots and replication stop; RPO grows. |
| Fast restore + commit | **Replaces the live path** with the snapshot's content; after commit it can't be undone. |
| Graceful failover / turnover | **Path is read-only on all peers** while the delta syncs; clients must be redirected to the new source. |
| Ungraceful / forced failover | Writes not yet replicated are **lost** on the new source; both sides may become writable (split brain until failback). |
| Failback after ungraceful failover | Writes made on the old primary since the last replicated snapshot are **discarded**. |
| Delete a replication peer | Refused while a policy uses it; breaks DR for its paths. |
| Enable versioning or object lock / WORM on a view | **Irreversible**; WORM views can't drop protocols; object lock needs an S3-only view. |
| Compliance retention / legal hold | Data can't be deleted by anyone until it expires / the hold is removed; the view can't be deleted while it holds data. |
| Indestructible snapshot / policy / object mode | Can't be removed or shortened without a Support-assisted unlock. |
| Unlock indestructibility | For 60 minutes, indestructible snapshots and policies can be deleted or changed. |
| Lifecycle rule (enable) | Starts **deleting** matching data immediately (audited as DELETE_BY_LIFECYCLE_RULE). |

## Workflow 1: take a snapshot and restore from it

KB: "Managing Snapshots" (`.../managing-snapshots-55.md`), "Restoring a File or Directory"
(`.../restoring-a-file-or-directory-55.md`), "Cloning a Local Snapshot", "Fast Restore for
Protected Paths". KB pages are under `https://kb.vastdata.com/documentation/docs/`.

1. Take stock: `vast_api.py get snapshots path=<dir> fields=id,name,path,state,created,expiration_time,indestructible`
   and `vast_api.py get tenants fields=id,name`.
2. Plan and ask. Create (dry run, then `--yes`):
   ```bash
   vast_api.py call POST /snapshots/ --data '{"name": "<snap-name>", "path": "<dir>",
     "tenant_id": <tenant-id>, "expiration_time": "<YYYY-MM-DDTHH:MM:SSZ>"}'
   ```
   Fields `name`, `path` (required), `tenant_id`, `expiration_time`, `indestructible` *(5.5 API)*.
   Set `indestructible` only if the user wants it undeletable (see Workflow 6). `locked` exists
   in the model but is documented as unused; use `indestructible`.
3. Check: `get snapshots name=<snap-name>` until `state` is `SUCCEED` (enum
   `SUCCEED|CREATING|DELETING|FAILED|INIT|RETRYING|RETRY_DELETE`, 5.5 API).
4. Restore, least to most disruptive:
   - **Copy back (no admin change)**: from a client, `ls <mount>/.snapshot/` then
     `cp -p <mount>/.snapshot/<snap-name>/<file> <mount>/<file>` (NFS; `rsync -A` for trees);
     SMB: type `\.snapshot` in the address bar, or Windows *Previous Versions*. If `.snapshot` is
     not visible, see the view policy fields in Pitfalls.
   - **Clone to a new path** (instantly writable, the original is untouched):
     ```bash
     vast_api.py call POST /snapshots/<snap-id>/clone/ --data '{"name": "<clone-name>",
       "loanee_root_path": "<new-path>", "loanee_tenant_id": <tenant-id>, "enabled": true}'
     ```
     `enabled` = background sync (copy all data so the clone stops depending on the snapshot).
     Body from the public KB how-to "Creating a Directory Clone and Exposing It as a View with
     CLI" and the `GlobalSnapStream` model *(5.5 API)*; the new path must not exist. Track it in
     `get globalsnapstreams`. Expose it with a view (`references/views-protocols.md`).
   - **Fast restore of a protected path** (DESTRUCTIVE: the path becomes the snapshot): Web UI
     Protected Paths → Restore → wait for the `<path>-restore` global snapshot clone to be
     Complete → Commit Restore; or VAST CLI `protectedpath restore --id <pp-id>
     --local-snapshot-id <snap-id>` then `protectedpath commit --id <pp-id>`. The REST calls
     are `POST /protectedpaths/<id>/restore/` and `PATCH /protectedpaths/<id>/commit/`; their body
     is not in the served spec, so confirm it in `https://VMS/docs/` first. Until commit, the
     clone can be stopped and the path is unchanged.
5. Report the snapshot id/name (and clone path) so the user can delete them later
   (`DELETE /snapshots/<id>/`, `DELETE /globalsnapstreams/<id>/`).

## Workflow 2: hourly snapshots with retention (local backup)

KB: "Configuration Workflow for Scheduling Snapshots", "Managing Protection Policies",
"Managing Protected Paths" (5.5).

1. Take stock: `get protectionpolicies fields=id,name,clone_type,frames,prefix,indestructible`,
   `get protectedpaths fields=id,name,source_dir,protection_policy_name,state`. Note any
   existing protected path above or below `<dir>`: async-replicated ones can't be nested (KB), and
   nested snapshots hold the same blocks (capacity estimates count them once).
2. Plan: one policy per distinct schedule. Example: hourly, keep 48 h; plus daily, keep 30 d.
   ```bash
   vast_api.py call POST /protectionpolicies/ --data '{"name": "<policy-name>",
     "clone_type": "LOCAL", "prefix": "<prefix>", "indestructible": false,
     "frames": [{"every": "1h", "start-at": "<YYYY-MM-DD HH:MM:SS>", "keep-local": "48h"},
                {"every": "1D", "start-at": "<YYYY-MM-DD HH:MM:SS>", "keep-local": "30D"}]}'
   ```
   `frames` is a list of schedules with **hyphenated** keys `every`, `start-at`, `keep-local`,
   `keep-remote` (the Terraform provider converts its `start_at` to `start-at` before calling the
   API; the Ansible collection sends hyphens). Units: s, m, h, D/d, W, M, Y (KB CLI page). The
   served spec only says `frames: object`, so read back the policy and compare.
3. Check: `get protectionpolicies name=<policy-name>`; `pretty_schedules` shows the parsed schedule.
4. Apply it to the directory:
   ```bash
   vast_api.py call POST /protectedpaths/ --data '{"name": "<pp-name>", "source_dir": "<dir>",
     "tenant_id": <tenant-id>, "protection_policy_id": <policy-id>, "capabilities": "LOCAL"}'
   ```
   `capabilities: "LOCAL"` is what the public Ansible collection sends for local paths; the
   spec has no enum, so if it's refused, read an existing local protected path, or create one in
   the Web UI (*New Local Protected Path*) and copy its fields.
5. Check after the first period: `get protectedpaths name=<pp-name>` (`state` Active,
   `last_snapshot_name`, `last_snapshot_creation_time`) and `get snapshots path=<dir>`
   (names are `<prefix>_<timestamp>`).
6. Keep the total under the cluster snapshot limit (KB "VAST Cluster Scale Guidelines"): new
   snapshots are not created past it. Retention × frequency × number of paths is the budget.

## Workflow 3: replicate a path to a second cluster and check health

KB: "Async Replication Configuration Workflows" (`.../async-replication-configuration-workflows-55.md`),
"Managing Replication Peers", "Async Replication Best Practices", "Monitoring Replication".
Details, multi-destination groups and sync replication: [references/data-protection/replication.md]()).

You need logins to **both** clusters (two sets of `VMS_*` variables).

1. Take stock on both: `get vippools fields=id,name,role,ip_ranges`,
   `get nativereplicationremotetargets`, `get tenants fields=id,name,guid`; check versions on
   both (`version`); note whether mTLS certificates are installed if the user wants `SECURE`.
2. On **each** cluster, a VIP pool with role `REPLICATION` (no domain name; optionally pinned to
   CNodes or a VLAN). VIP pools are covered in `references/tenants-network.md`.
3. On the source, the peer:
   ```bash
   vast_api.py call POST /nativereplicationremotetargets/ --data '{"name": "<peer-name>",
     "leading_vip": "<one VIP of the remote REPLICATION pool>", "pool_id": <local-repl-pool-id>,
     "secure_mode": "NONE"}'
   ```
   Required `name`, `leading_vip`, `pool_id`; `secure_mode` `NONE|SECURE`, `transport_mode`
   `TCP|QUIC` *(5.5 API)*. Check `get nativereplicationremotetargets name=<peer-name>` on both
   clusters: connected, `health`, `last_heart_beat`, `remote_version`, `space_left`.
4. Policy with `clone_type: "NATIVE_REPLICATION"`, `target_object_id: <peer-id>`, and frames with
   `keep-remote` (e.g. `{"every": "15m", "keep-local": "1D", "keep-remote": "7D"}`). It is mirrored
   to the peer for the reverse direction.
5. Protected path on the source:
   ```bash
   vast_api.py call POST /protectedpaths/ --data '{"name": "<pp-name>", "source_dir": "<dir>",
     "tenant_id": <tenant-id>, "protection_policy_id": <policy-id>,
     "target_exported_dir": "<new dir on peer>", "remote_tenant_guid": "<peer tenant guid>",
     "capabilities": "ASYNC_REPLICATION"}'
   ```
   The target directory must **not** exist on the peer and can't be `/`. Bucket replication
   (recreate S3 buckets on the peer) is fixed at creation (5.5 KB; on 5.5 the cluster default is
   `Cluster.enable_bucket_replication`; confirm the per-path field in `/docs/`).
6. Health checks (run on either side):
   ```bash
   vast_api.py get protectedpaths fields=id,name,role,state,health,peer_connection_state,last_restore_point_time,eta,bw
   vast_api.py get replicationrestorepoints page_size=20 fields=name,state,progress_promil,upload_finish_time,peer_cluster_name
   vast_api.py get replicationstreams fields=id,name,role,state,last_snapshot_name
   vast_api.py get nativereplicationremotetargets fields=name,state,health,last_heart_beat,space_left
   ```
   States: Format → Initial Sync → Active; Suspended means paused, disconnected or after failover
   (KB "Managing Protected Paths"). RPO ≈ now − `last_restore_point_time`. Prometheus:
   `/prometheusmetrics/replications`. To replicate immediately: Web UI *Replicate Now*, VAST CLI
   `protectedpath replicate-now`, or `PATCH /protectedpaths/<id>/replicate_now/` (confirm body).
7. For NFSv3 clients that must survive failover without remounting, create views with *global
   sync* on the replicated path on both clusters (KB "Preparing for Seamless Replication Failover
   (NFSv3)").

## Workflow 4: planned (graceful) failover and failback

KB: "Failover Capabilities and Scenarios for Asynchronous Replication", "Performing Failover and
Failback for Asynchronous Replication", "Aborting Asynchronous Replication Failover",
"Deploying a Failed-Over Replication Peer as a Working Cluster" (5.5).

> **Disruptive.** During a graceful failover the path is **read-only on every peer** until the
> delta is synced; afterwards clients must use the other cluster. Agree a window with the user,
> and confirm DNS/VIP/mount changes on the client side are ready.

1. Readiness (read-only, on the destination): peer connected; protected path `role` Destination,
   `state` Active; last restore point COMPLETE and recent. On the destination cluster, check that
   views, view policies, users/groups, S3 keys/identity policies, quotas, VIP pools exist for
   clients (download *VMS Data* from the peer in the Web UI; KB "Deploying a Failed-Over...").
2. Shrink the delta: on the source, replicate now; when it completes, replicate now once more.
3. Start the failover **on the destination cluster**: Web UI Protected Paths → Replications →
   Modify Replication State → *Source is enabled* → Fail Over; or VAST CLI
   `protectedpath modify --id <pp-id-on-destination> --modify-replication-state --graceful`.
   REST: the public Ansible collection sends `PATCH /protectedpaths/<id>/` with
   `{"failover": true, "graceful": true}`; these fields are **not** in the 5.5.3 served spec, so
   verify in `/docs/` before using the API, or use the UI/CLI.
4. Follow `role`, `role_change_progress_promil`, `role_change_eta_sec` on both clusters until the
   destination shows role Source and state Active. Abort is possible only in the read-only phase
   (Web UI *Abort Failover*; CLI flag per KB `--abort-modify-replication-state`).
5. Point clients at the new source; check writes work.
6. **Failback** after a graceful failover: repeat steps 1–5 from the original primary (now the
   destination).

Unplanned (source down): **ungraceful** failover from the destination (`--ungraceful`, or
`protectedpath force-failover --id <id>` / `PATCH /protectedpaths/<id>/force_failover/` in group
replication). Data not yet replicated is lost; both sides may end up writable (Standalone). Fail
back per the KB: resume replication from the survivor, wait for a complete restore point, then fail
over gracefully. Writes on the old primary after the last replicated snapshot are discarded.

## Workflow 5: object lock (WORM) on an S3 bucket

KB: "S3 Object Locking", "Write Once Read Many (WORM) Views", "Object Versioning" (5.5).
More (legal hold, indestructible object mode, lifecycle): [references/data-protection/s3-object-protection.md]()).

> **Irreversible.** Object lock can't be disabled; it turns on versioning, which can't be
> disabled either. Compliance retention can't be shortened by anyone.

1. Take stock: `get views path=<bucket-path> fields=id,path,bucket,protocols,locking,s3_versioning,s3_locks_retention_mode,default_retention_period,is_indestructible_object_enabled`.
   The view must be **S3 only** (no NFS/SMB) and not in indestructible object mode. Check NTP is
   configured (WORM uses true time).
2. Plan and ask, then:
   ```bash
   vast_api.py call PATCH /views/<view-id>/ --data '{"locking": true,
     "s3_locks_retention_mode": "GOVERNANCE", "default_retention_period": "30d"}'
   ```
   Fields *(5.5 API)*: `locking`, `s3_locks_retention_mode` (`NONE` seen on 5.5.3; `GOVERNANCE`,
   `COMPLIANCE` per the KB and Terraform docs), `default_retention_period` (`<n>h|d|m|y`; required
   with GOVERNANCE/COMPLIANCE per Terraform docs). Or from an S3 client: CreateBucket with
   `x-amz-bucket-object-lock-enabled: true`, then PutObjectLockConfiguration.
3. Check: read the view back; from S3, `aws s3api get-object-lock-configuration --bucket <bucket>
   --endpoint-url https://<s3-vip>`.
4. Per-object: `put-object-retention`, `put-object-legal-hold --legal-hold Status=ON`; overriding
   governance needs `s3:BypassGovernanceRetention` and the `x-amz-bypass-governance-retention:true`
   header. Grant the S3 permissions with identity or bucket policies (`references/identity-access.md`).

## Workflow 6: make backups immutable (indestructibility)

KB: "Indestructibility Overview", "Managing the Indestructibility Mechanism",
"Managing Indestructible Protection Policies and Snapshots" (5.5).

1. `vast_api.py get indestructibility` → `is_locked` (true by default), `passwd_delay`.
2. Before relying on it: the indestructibility password must be changed from its default (needs
   an unlock), and the users allowed to unlock must be enrolled with VAST Support (KB "Required
   First Steps").
3. Mark policies/snapshots `"indestructible": true` (on create, or PATCH). After that, deleting,
   shortening retention, pausing their protected path or turning the flag off needs an unlock:
   generate a VMS token (`PATCH /indestructibility/<id>/generate_token/` or Web UI), give it to VAST
   Support, enter their token (`.../unlock/`). It relocks after 60 minutes. Never script the unlock
   on the user's behalf; it is a deliberate human procedure.
4. A password reset to default has a delay (1 day by default) and raises an alarm: if the user
   didn't start one, treat it as a security incident.

## Pitfalls

| Symptom / error | Cause | Fix |
|---|---|---|
| `.snapshot` not visible from clients | View policy hides it (seen on 5.5.3 defaults: `enable_visibility_of_snapshot_dir` false, `enable_listing_of_snapshot_dir` false, `enable_snapshot_lookup` true) | `cd .snapshot` / type the path explicitly; or change those view policy fields (affects every view on the policy). `enable_access_to_snapshot_dir_in_subdirs` exposes parent snapshots in subdirectories. |
| Scheduled snapshots stop being created | Cluster snapshot limit reached, or replication slower than the period (snapshots are skipped) | Shorten retention or frequency; check bandwidth/QoS (KB "Replication QoS"). |
| Snapshot delete refused / expiration can't be shortened | Snapshot or its policy is indestructible | Wait for expiry, or Support-assisted unlock (Workflow 6). |
| Deleted a snapshot while services were degraded; it vanished from the UI but space is still used | Known behaviour (KB "Managing Snapshots", 5.5) | Contact VAST Support. |
| Protected path create fails: target exists | `target_exported_dir` must be a new directory on the peer, not `/` | Pick a new subdirectory. |
| Can't move files into/out of a replicated path (rename fails across the boundary) | Not allowed for async/S3-replicated protected paths (KB) | Copy instead of move. |
| Can't nest async protected paths | Not supported (KB) | Protect the parent, or separate trees. |
| "cannot replicate to more than one tenant on the same remote cluster" | Tenant A → tenant B on a peer excludes A → C on that same peer (KB) | Use the same remote tenant, or another peer. |
| Changing a policy affected other paths | Policies are shared; a path's policy can't be swapped (KB) | One policy per protected path when schedules differ. |
| Peer state Not Connected / Error | Remote VIP not in the remote REPLICATION pool, firewall, or peer points at itself | Check both pools, routing, and `leading_vip`; Error also means "same cluster as source". |
| `SECURE` peer won't connect | mTLS certificates (cert, key, same root CA) missing on one side | Install under Settings → Certificates → replication on both clusters. |
| Failover option missing / refused | Run on the source instead of the destination, another member already becoming source, or group change in progress | Run on the destination; wait for the other operation. |
| After ungraceful failover both sides take writes | Expected: role Standalone | Fail back per Workflow 4; decide which side's new writes to keep. |
| S3 clients get AccessDenied on the DR cluster after failover | Replicated access keys / identity policies are stored as *remote* and need enabling; local users aren't replicated | Enable them; recreate local users (KB "Deploying a Failed-Over..."). |
| Buckets missing on the peer | Bucket replication off for that protected path (fixed at creation; off by default on fresh 5.5 installs) | Create the buckets on the peer, or recreate the protected path with it on (full resync). |
| Object lock can't be enabled | View also has NFS/SMB, or indestructible object mode is on | Use an S3-only view; the two modes are exclusive. |
| HeadObject shows governance though compliance was set | KB "S3 Object Locking" (5.5) says compliance isn't returned/supported in headers while other 5.5 pages document COMPLIANCE | Read the view's `s3_locks_retention_mode` and test on a scratch bucket before relying on it. |
| WORM view locked from expiry/deletion | NTP time drift detected | Fix NTP; contact VAST Support. |
| Lifecycle rule didn't delete objects | Objects are under indestructible object mode or object-lock retention | Expected; they expire after retention. |
| Fast restore refused on a bucket | Snapshots can't be restored on a view in indestructible object mode (KB) | Clone to a new path instead. |

## Other releases

- 5.5 KB pages carry `-55` in the URL; search with `--version 5.5`, or e.g. `--version 5.3` for
  older ones. Older APIs also expose `/snapshotpolicies/` and `/replicationpolicies/`
  (legacy, empty on 5.5.3 here); on 5.5 use protection policies.
- Units `W`, `M`, `Y` in schedules need 4.6.0-SP22 or later (KB). Global access on an async
  destination needs 5.4+ on both peers. S3 sync replication KB pages start at 5.2.
- Field names checked here (5.5.3): `ProtectionPolicy.frames/clone_type/target_object_id`,
  `ProtectedPath.capabilities/source_dir/target_exported_dir/remote_tenant_guid`,
  `View.locking/s3_versioning/s3_locks_retention_mode`. Re-check with `spec model` on any other release.

## Related areas

`SKILL.md` (connection, helper), `references/views-protocols.md` (views, view policies, buckets),
`references/tenants-network.md` (VIP pools, tenants), `references/identity-access.md` (S3 keys, identity
policies), `references/database.md` (DB tables live in buckets: protect the bucket path), `references/monitoring.md`.

Verified: VAST 5.5.3 (served spec read; live read-only calls on a single cluster with no
replication peer; KB 5.5 pages; public vastpy, Terraform provider and Ansible collection
examples). Not run end to end: replication, failover, restore/commit, object lock.
