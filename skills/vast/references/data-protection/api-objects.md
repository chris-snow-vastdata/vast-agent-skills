# Data protection API objects (checked on 5.5.3)

Every field below appeared in the spec served by a 5.5.3 cluster (`vast_api.py spec model <Name>`)
unless marked otherwise. The served spec shows most fields as plain strings with no enums and,
for action endpoints, repeats the whole model instead of the real body. Where that happens the
source is named: KB (kb.vastdata.com, 5.5), CLI (the VAST CLI page of the same name, 5.5),
TF (Terraform provider `vast-data/vastdata` docs), Ansible (`vastdata.vms` collection).

Re-check on any cluster:

```bash
vast_api.py spec model Snapshot            # or ProtectionPolicy, ProtectedPath, ...
vast_api.py spec show /protectedpaths/ post
vast_api.py spec search <field>
```

## Endpoints

| Object | Endpoint (5.5) | Notes |
|---|---|---|
| Snapshot | `/snapshots/` GET POST; `/snapshots/{id}/` GET PATCH DELETE; `/snapshots/bulk/` PATCH DELETE | |
| Clone a local snapshot | `POST /snapshots/{id}/clone/` | creates a global snapshot clone |
| Block volume clone | `POST /snapshots/{id}/clone_volume/`, `GET /snapshots/{id}/snapshot_volumes/`, `GET /volumes/{id}/get_snapshots/` | block subsystems |
| Protection policy | `/protectionpolicies/` GET POST; `/{id}/` GET PATCH DELETE | |
| Protected path | `/protectedpaths/` GET POST; `/{id}/` GET PATCH DELETE; `/protectedpaths/get_all_info/` | |
| Protected path actions | `/{id}/restore/` POST, `/{id}/commit/` PATCH, `/{id}/replicate_now/` PATCH, `/{id}/pause/` `/resume/` `/stop/` PATCH (restore control), `/{id}/force_failover/` PATCH, `/{id}/add_stream/` `/remove_stream/` `/modify_member/` `/reattach_stream/` PATCH, `/{id}/validate/` GET, `/{id}/prefetch_path/` GET POST DELETE | bodies not in served spec |
| Replication stream | `/replicationstreams/` GET; `/{id}/` PATCH (QoS priority) | one per destination |
| Restore point | `/replicationrestorepoints/` GET | progress of each replicated snapshot |
| Replication peer (VAST) | `/nativereplicationremotetargets/` GET POST; `/{id}/` GET PATCH DELETE; `/{id}/download_vms_objects/` GET | "Download VMS Data" for DR |
| S3 replication peer | `/replicationtargets/` GET POST; `/{id}/` | backup to S3 (AWS or S3-compatible) |
| Global snapshot clone | `/globalsnapstreams/` GET POST; `/{id}/` GET PATCH DELETE; `/{id}/pause/` `/resume/` `/stop/` PATCH | |
| Remote snapshot discovery | `GET /clusters/list_clone_snapshoted_paths_remote/`, `GET /clusters/list_snapshoted_paths_remote/`, `GET /clusters/get_snapshoted_paths/` | query params not in spec; see CLI `cluster list-...-remote` |
| Indestructibility | `/indestructibility/` GET; `/{id}/` PATCH; `/{id}/generate_token/` `/unlock/` `/reset_passwd/` PATCH | single object, `is_locked` |
| Lifecycle rule | `/s3lifecyclerules/` GET POST; `/{id}/` GET PATCH DELETE; `GET /s3lifecyclerules/get_object_expiration/` | |
| Metrics | `GET /prometheusmetrics/replications`, `GET /prometheusmetrics/lifecycle_metrics` | Prometheus text |
| Legacy | `/snapshotpolicies/`, `/replicationpolicies/` | older model; use protection policies on 5.5 |

## Snapshot

Create: `name` (required), `path` (required), `tenant_id` (default 1), `expiration_time`
(date-time), `indestructible` (bool). Read-only/informational: `state` (`SUCCEED|CREATING|
DELETING|FAILED|INIT|RETRYING|RETRY_DELETE`), `type` (`local|replication|remote|big_catalog`),
`created`, `policy`/`protection_policy_id` (set when made by a policy), `aggr_phys_estimation`,
`unique_phys_estimation` (the UI's Aggregated / Unique Usage), `access_path`.
`locked` is in the model but the Ansible collection documents it as "Not in use"; an older
public KB how-to passes `locked=true` - prefer `indestructible`.

Expiration of an indestructible snapshot can be extended but not shortened without an unlock (KB).

## Snapshot clone (`POST /snapshots/{id}/clone/`) and `GlobalSnapStream`

Body used by the public KB how-to (vastpy-cli): `name`, `loanee_root_path` (new path, must not
exist), `enabled` (true = background sync). `GlobalSnapStream` also has `loanee_tenant_id`
(target tenant, default 1), `loanee_snapshot_id` (local snapshot), `remote_target_id` +
`owner_root_snapshot` (clone from a peer's snapshot), `view_replication_enabled` (5.5),
read-only `state`, `sync_progress`, `health`. CLI: `snapshot clone`, `globalsnapshotclone create`
(`--enable-bucket-replication` is fixed at creation). Removing a clone: `DELETE /globalsnapstreams/{id}/`
(Ansible exposes a `remove_dir` option - check `/docs/` for whether the directory is removed).

## Protection policy

`name` (required), `prefix` (required; snapshots are named `<prefix>_<timestamp>`), `clone_type`
(`LOCAL|NATIVE_REPLICATION|CLOUD_REPLICATION`), `frames` (list), `indestructible` (bool),
`target_object_id` (peer id: a native replication peer for NATIVE_REPLICATION, an S3 replication
peer for CLOUD_REPLICATION - TF docs), `tenant_id`, `remote_tenant`, `is_sync_replication`,
read-only `pretty_schedules`, `target_name`, `schedule_miss`.

`frames` entries (hyphenated keys on the wire - TF converts `start_at`→`start-at`; Ansible sends
hyphens):

| Key | Meaning |
|---|---|
| `every` | period, e.g. `15m`, `1h`, `1D` |
| `start-at` | `YYYY-MM-DD HH:MM:SS` (TF docs: UTC) |
| `keep-local` | retention on this cluster; omit to delete local snapshots right after replication (UI) |
| `keep-remote` | retention of restore points on the peer (async replication) |

Units (KB CLI `protectionpolicy create`): s, m, h, d, W, M, Y. For `CLOUD_REPLICATION` the
minimum period is 6 h and S3 backups don't expire. CLI schedule syntax for comparison:
`every 90m start-at 2025-07-27 20:10:35 keep-local 10h keep-remote 7d`.

## Protected path

Create: `name` (required, ≤64), `source_dir`, `tenant_id`, `protection_policy_id`,
`target_exported_dir` (path on the peer, must not exist), `remote_tenant_guid` (or
`remote_tenant_name` in the CLI), `capabilities`, `remote_target_id` (sync replication / global
access, where there is no policy), `sync_interval` (s, group sync-point guarantee, default 86400),
`sync_disconnect_time` (s, sync replication, default 45), `lease_expiry_time` (global access),
`enabled` (false = paused).

`capabilities` values differ by source - check with an existing object before sending:

| Source | Values |
|---|---|
| TF / Ansible (REST) | `ASYNC_REPLICATION`, `SYNC_REPLICATION`, `STARED_GLOBAL_NAMESPACE` (sic), `REPLICATION_AND_GN`; Ansible also `LOCAL` for local paths |
| VAST CLI 5.5 | `ASYNC_REPLICATION`, `GLOBAL_ACCESS`, `ASYNC_REPLICATION_AND_GLOBAL_ACCESS`, `SYNC_REPLICATION` (`modify-member` page also lists `SYNC_REPLICATION_AND_GLOBAL_ACCESS`) |

Health/read-only: `state` (UI: Format, Initial Sync, Active, Suspended), `health`, `role`,
`protected_path_role`, `peer_connection_state`, `last_snapshot_name`, `last_snapshot_creation_time`,
`last_restore_point_time`, `last_uploading_restore_point_progress`, `bw`, `eta`,
`role_change_progress_promil`, `role_change_eta_sec`, `failback_allowed`, `restore_status`,
`restore_progress`, `members_info`, `replication_stream_roles`.

Failover fields: the Ansible collection (generated for VMS 5.4+) sends `failover`, `graceful`,
`abort` on `PATCH /protectedpaths/{id}/`; they are absent from the 5.5.3 served spec. CLI:
`protectedpath modify --id ID --modify-replication-state --graceful|--ungraceful`, abort with
`--abort-modify-replication-state` (the "Aborting..." KB page writes `--abort-failover`; run
`protectedpath modify --help` in vcli to see which your release takes). Forced: `protectedpath
force-failover --id ID`.

Streams (Ansible `protectedpath_streams`): `add_stream` body `name`, `protection_policy_id`,
`target_exported_dir`, `remote_tenant_guid`, `capabilities`, `remote_target_id`,
`view_replication_enabled`; `remove_stream` body `{"stream_id": "<id>"}`; `modify_member` body
`stream_id` + changed fields.

Restore: CLI `protectedpath restore --id ID --local-snapshot-id SNAP` then `protectedpath commit
--id ID`. REST body for `/restore/` not confirmed on 5.5.3 - read `/docs/`.

## Replication peer (`NativeReplicationRemoteTarget`)

Create: `name` (required, mirrored on the peer with the same name), `leading_vip` (required, any
VIP of the remote REPLICATION pool), `pool_id` (required, local REPLICATION pool), `secure_mode`
(`NONE|SECURE`), `transport_mode` (`TCP|QUIC`), `mss`, `password` (TF example). Read: `state`,
`status`, `health`, `sync_state`, `last_heart_beat`, `remote_version`, `space_left`,
`remote_vips`, `is_local` (false = mirrored from the other side), `peer_certificate`.
Delete is refused while a protection policy uses the peer (KB).

## S3 replication peer (`ReplicationTarget`, backup to S3)

Required: `name`, `type`, `bucket_name`, `http_protocol`, `access_key` (+ secret); optional
`aws_region`, `aws_account_id`, `aws_role`, `custom_bucket_url`. KB: "Managing S3 Replication
Peers" (5.5). Policy `clone_type: CLOUD_REPLICATION`, period ≥ 6 h.

## Indestructibility

`GET /indestructibility/` → one object: `is_locked`, `passwd_delay` (e.g. `1 00:00:00`),
`passwd_delay_eta`, `unlock_system_time`, `token_time`. Actions: `generate_token`, `unlock`
(with the Support token), `reset_passwd` (delayed, raises an alarm), `PATCH /{id}/`
`new_indestructibility_passwd`, `passwd_delay` (only while unlocked). Exact bodies: KB API
reference or `/docs/`. Unlock lasts 60 minutes.

## View fields for S3 / WORM protection (see `references/views-protocols.md` for views in general)

`s3_versioning`, `locking`, `s3_locks_retention_mode` (`NONE` observed; GOVERNANCE/COMPLIANCE per
KB/TF), `files_retention_mode` (NFS/SMB WORM; `NONE` observed), `default_retention_period`,
`min_retention_period`, `max_retention_period`, `auto_commit` (NFS/SMB), `is_indestructible_object_enabled`,
`indestructible_object_duration` (days 1-400). Cluster: `is_indestructible_object_enabled`
(feature on the cluster), `enable_bucket_replication`, `enable_trash`.

View policy fields for the snapshot directory: `enable_snapshot_lookup` (`cd .snapshot` works),
`enable_listing_of_snapshot_dir` (`.snapshot` listed), `enable_visibility_of_snapshot_dir`,
`enable_access_to_snapshot_dir_in_subdirs`. Meanings inferred from names and the KB "Snapshots"
page; confirm on `/docs/` before changing a shared policy.

## Lifecycle rule (`/s3lifecyclerules/`)

Required `name`, `view_id`. Scope: `prefix`, `min_size`, `max_size`, `tags`. Actions:
`expiration_days` or `expiration_date`, `object_age_attr` (`M_TIME|A_TIME|C_TIME`),
`expired_obj_delete_marker`, `noncurrent_days`, `newer_noncurrent_versions` (≤100 per UI),
`abort_mpu_days_after_initiation`, `enabled`. Expiry lookup:
`GET /s3lifecyclerules/get_object_expiration/` (CLI `lifecyclerule get-object-expiration`).
