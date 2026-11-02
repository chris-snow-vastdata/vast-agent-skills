# View policies: fields, flavors, host rules

Field names: `vast_api.py spec model ViewPolicy` on the user's cluster *(names below checked
on the 5.5.3 spec; descriptions from KB "Create View Policy", API 5.5 and "Managing View
Policies", 5.5: https://kb.vastdata.com/documentation/docs/managing-view-policies-55.md)*.
Re-check on other releases; fields appear and change between versions.

## Security flavor (`flavor`)

Values *(KB API 5.5; values seen live on 5.5.3: NFS, MIXED_LAST_WINS, S3_NATIVE, BLOCK)*:
`NFS`, `SMB`, `MIXED_LAST_WINS`, `S3_NATIVE`, `BLOCK`. The swagger types it as a plain string,
so a typo isn't caught by the spec: read the policy back after creating it.

| Behaviour | NFS | SMB | MIXED_LAST_WINS | S3_NATIVE |
|---|---|---|---|---|
| Permissions settable via NFS | yes (mode bits; POSIX ACLs via NFSv3 if `nfs_posix_acl`) | ignored | yes, incl. NFSv4 ACLs | silently ignored |
| via SMB | fails | yes | yes | silently ignored |
| via S3 | ACL calls ignored | denied | yes | yes (ACLs, identity and bucket policies) |
| Initial permissions for "foreign" protocols | `smb_file_mode` / `smb_directory_mode` (or inherit from parent) | NTFS inheritance | per protocol | ACE giving owner FULL CONTROL |
| Traverse permission needed on parents | yes | no | depends on `access_flavor` | no |
| Identity/bucket policies evaluated | no | no | no | yes |

- `access_flavor` (NFS4 | SMB | ALL) applies only to MIXED_LAST_WINS: which of NFSv4/SMB may
  set permissions (NFSv3 and S3 are unaffected). KB warns not to change it on a view in use.
- S3 Native: versioned objects are read-only over NFS/SMB; SMB privileged users aren't honoured;
  NFSv3 `SETATTR` isn't allowed. Mapping of NFSv3/NFSv4/SMB calls to S3 actions (e.g.
  READDIR → ListObjects, CREATE → PutObject): KB "Controlling File and Directory Permissions
  Across Protocols" (https://kb.vastdata.com/documentation/docs/security-flavors.md).
- BLOCK: for block subsystems only; no POSIX/ACL checks; access is VIP pool + tenant + host NQN
  mapping; blocks NFS/SMB/S3 *(KB "Views and View Policies", 5.5)*.
- DATABASE / KAFKA views require S3_NATIVE *(error seen on 5.5.3)*.

## Host-based access (per protocol)

| Field | Meaning |
|---|---|
| `nfs_read_write`, `nfs_read_only` | NFSv3 + NFSv4 hosts allowed RW / RO. Default `["*"]` RW. Hosts in neither list are refused. `~host` in RW is a deny rule. |
| `nfs_root_squash` | root → nobody (default `["*"]`). NFSv3; not meaningful for NFSv4 + Kerberos. |
| `nfs_all_squash` | every user → nobody. |
| `nfs_no_squash` | no mapping (trusted admin hosts only). |
| `trash_access` | hosts allowed into the trash folder (cluster feature "trash folder access"). |
| `smb_read_write`, `smb_read_only` | SMB client hosts. |
| `s3_read_write`, `s3_read_only` | S3 client hosts. |

Host syntax *(KB API 5.5)*: IP, CIDR, `*` wildcard per octet (`<a.b.c>.*`), netgroup `@name`
(NFS/SMB RW), FQDN (KB "Host-Based Access Rules"). Netgroups are cached; refresh with
`PATCH /viewpolicies/{id}/refresh_netgroups/`. Practical limit ~4096 policies; each policy's
constraints use tables of 50 (KB "NFS & SMB Share and Policy Limits and Constraints").

The KB request schema also has `vip_pools` (restrict the policy to VIP pools) and `read_write`
/ `read_only` aliases; `vip_pools` is **not** in the 5.5.3 cluster spec's ViewPolicy model
(the spec has `permission_per_vip_pool`). Check `spec model ViewPolicy` and the KB on the
user's release, dry-run, then read back.

## Identity and NFS options

| Field | Values / meaning |
|---|---|
| `auth_source` | RPC (trust client GIDs), PROVIDERS (groups from AD/LDAP), RPC_AND_PROVIDERS |
| `nfs_minimal_protection_level` | NONE, SYSTEM, KRB_AUTH_ONLY, KRB_INTEGRITY, KRB_PRIVACY (NFSv4 Kerberos minimum) |
| `nfs_enforce_tls`, `nfs_enforce_tls_relaxed`, `nfs_enforce_mtls` | NFS over TLS / mTLS (5.5) |
| `nfs_posix_acl` | POSIX ACLs for NFSv3 (NFS flavor only; not with NFSv4 ACLs) |
| `nfs_case_insensitive` | NFSv4 case-insensitive names |
| `gid_inheritance` | LINUX or BSD |
| `use_32bit_fileid`, `expose_id_in_fsid` | client compatibility |
| `path_length`, `allowed_characters` | LCD (lowest common denominator, default) or NPL (native protocol limit) |
| `atime_frequency` | atime update interval (default 3600 s) |
| snapshot dir: `enable_snapshot_lookup`, `enable_listing_of_snapshot_dir`, `enable_visibility_of_snapshot_dir`, `enable_access_to_snapshot_dir_in_subdirs` | `.snapshot` visibility |

## SMB options

`smb_is_ca` (continuously available shares, SMB3), `disable_read_lease`,
`disable_write_lease`, `disable_handle_lease`, `smb_recursive_change_notify`,
`smb_file_mode` / `smb_directory_mode` (NFS flavor: mode bits for files/dirs made by SMB/S3,
three octal digits), `apple_sid`.

## S3 options

| Field | Meaning |
|---|---|
| `s3_visibility`, `s3_visibility_groups` | users / groups who may *list* buckets created with this policy without access to them |
| `is_s3_default_policy` | policy used for buckets created via the S3 API without an endpoint view |
| `s3_special_chars_support` | allow keys with `//` or `/../` (incompatible with file protocols) |
| `s3_flavor_allow_free_listing` | S3 Native: NFS/SMB clients may list bucket directories regardless of object permissions |
| `s3_flavor_detect_full_pathname` | S3 Native: match identity-policy resources on full paths for NFS/SMB (otherwise bucket name only) |

## Auditing

`protocols_audit` and the audit operation lists (`read`, `change`, `full` ...); see KB
"Configuring Auditing with View Policies" (5.5) and `references/monitoring.md`.

## Deleting a policy

A policy can be deleted only when no view uses it (KB). List users of it with
`get views policy=<name>` and check the result client-side.
