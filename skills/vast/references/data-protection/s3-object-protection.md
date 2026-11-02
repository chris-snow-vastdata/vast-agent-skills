# S3 and file-level immutability, versioning, lifecycle (5.5)

KB pages (5.5, under `https://kb.vastdata.com/documentation/docs/`): "Object Versioning"
(`object-versioning-55.md`), "S3 Object Locking" (`s3-object-locking-55.md`), "Write Once Read
Many (WORM) Views" (`write-once-read-many-worm-views-55.md`), "Indestructible Object Mode"
(`indestructible-object-mode-55.md`), "Lifecycle Rules" (`overview-of-lifecycle-rules-55.md`,
`managing-lifecycle-rules-55.md`). Buckets are views: create/modify them with the
`references/views-protocols.md`; the protection fields are listed in [api-objects.md](api-objects.md).

## Choosing a mechanism

| Need | Use | Who controls retention | Reversible? |
|---|---|---|---|
| Undo overwrites/deletes of objects | Versioning (`s3_versioning`) | - | No (can't disable) |
| Regulatory WORM for objects, per object or bucket default | Object lock (`locking` + `s3_locks_retention_mode` + `default_retention_period`) | bucket owner / users with S3 permissions | No |
| WORM for NFS/SMB files | WORM view (`locking` + `files_retention_mode`, min/max/default retention, `auto_commit`) | admins + file `atime` / read-only bit | No |
| Hold indefinitely (litigation) | Legal hold (S3 PutObjectLegalHold; Web UI *Legal Hold* for files) | whoever has the permission | Yes, by removing the hold |
| Ransomware-proof fixed window, admin-controlled, no versioning | Indestructible object mode (`is_indestructible_object_enabled`, `indestructible_object_duration` 1-400 days) | VMS admins + indestructibility unlock | Only with unlock |
| Point-in-time copies of a whole path | Snapshots (+ `indestructible`) | protection policy | Only with unlock if indestructible |
| Expire old data / versions | Lifecycle rules | admins | Yes (rule can be disabled) |

## Versioning

- Enable: `PATCH /views/<id>/ {"s3_versioning": true}` (5.5 API), Web UI view S3 tab, CLI `view
  modify --s3-versioning`, or S3 `PutBucketVersioning` Enabled. **Cannot be disabled.**
- Multiprotocol access to versioned objects isn't supported (other protocols see them read-only);
  MFA Delete isn't supported.
- Delete creates a delete marker; restore = copy the old version onto the key, or delete the
  current version. Clean up with lifecycle `noncurrent_days` / `newer_noncurrent_versions` /
  `expired_obj_delete_marker`.

## Object lock

- S3-only view, not in indestructible object mode. Turns versioning on. **Cannot be disabled.**
- VMS: `locking: true`, `s3_locks_retention_mode` (`GOVERNANCE` / `COMPLIANCE`, or `NONE` = set per
  object), `default_retention_period` (`<n>h|d|m|y`). S3: CreateBucket with
  `x-amz-bucket-object-lock-enabled`, PutObjectLockConfiguration, GetObjectLockConfiguration.
- Governance: users with `s3:BypassGovernanceRetention` + header
  `x-amz-bypass-governance-retention:true` can shorten/remove. Compliance: can only be extended.
- Per object: PutObjectRetention (`s3:PutObjectRetention`), GetObjectRetention, PutObjectLegalHold,
  GetObjectLegalHold; HeadObject/GetObject return `x-amz-object-lock-mode`,
  `x-amz-object-lock-retain-until-date`, `x-amz-object-lock-legal-hold` if permitted.
- **KB inconsistency (5.5)**: the "S3 Object Locking" page says compliance mode is not supported
  and the lock mode is always governance (in the HeadObject row), while the same page and the WORM
  page describe compliance mode. Test on a scratch bucket and read back the headers before telling
  a user compliance is enforced.

Example S3 calls (standard AWS CLI against the bucket's S3 endpoint):

```bash
aws s3api create-bucket --bucket <bucket> --object-lock-enabled-for-bucket --endpoint-url https://<s3-endpoint>
aws s3api put-object-lock-configuration --bucket <bucket> --endpoint-url https://<s3-endpoint> \
  --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"GOVERNANCE","Days":30}}}'
aws s3api put-object-legal-hold --bucket <bucket> --key <key> --legal-hold Status=ON --endpoint-url https://<s3-endpoint>
aws s3api head-object --bucket <bucket> --key <key> --endpoint-url https://<s3-endpoint>
```

## WORM views for NFS/SMB

- Choose a file retention mode when enabling (required for NFS/SMB). Default retention can be set
  alone; min and max must be set together with default. `auto_commit` locks files N after last
  modification (needs default retention).
- Lock a file: set its `atime` in the future (`touch -a -t <YYYYMMDDhhmm.ss> <file>`; clamped to
  min/max), or make it read-only (`chmod 444`, `attrib +r`; uses default retention).
- Limits: can't disable WORM; can add but not remove protocols; NFS/SMB and S3 can't share a WORM
  view; no nested views under it; no bulk permission updates; unlocked files can be deleted but not
  renamed or rewritten; the view can be deleted only when empty. Needs NTP: time drift locks views
  from expiry/deletion (contact VAST Support).

## Indestructible object mode

- Enable on the cluster first (`Cluster.is_indestructible_object_enabled`), then per view
  (`is_indestructible_object_enabled`, `indestructible_object_duration`, default 8 days in the UI).
- S3-only view, not `/`, no other views on/under the path, not the audit view, no versioning /
  object lock / WORM, no replication or global access, snapshots can't be restored onto it.
- Objects can't be deleted (even by lifecycle), overwritten, renamed or have metadata/ACL/tags
  changed during retention: set ACLs and tags in the upload request.
- Disabling, changing the duration, or deleting the (empty) bucket needs the indestructibility
  unlock. Clients see a `Retain-Until` header; a proprietary
  `PUT /<bucket>/?extend-indestructible-object-retention-period` request (permission
  `IndestructibleObjectExtendRetentionPeriod`) restarts retention for up to 1000 keys.

## Lifecycle rules

- One rule per view scope (prefix, min/max size, up to 40 tags). Actions: expire current version
  after N days (by creation, access or modification time) or on a date; delete expired delete
  markers (mutually exclusive with expiring current versions: use two rules); abort incomplete
  multipart uploads; delete non-current versions after N days, keeping up to N newest.
- On a non-versioned view, expiry **permanently deletes** files and objects, including data
  written over NFS/SMB. An enabled rule acts immediately on everything that already qualifies:
  create it with `"enabled": false`, check `get_object_expiration` for a sample object, then enable.
- Prefix `sales` also matches `salesforecasts`; use `sales/` for a directory.
