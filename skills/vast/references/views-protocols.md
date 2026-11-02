# VAST views, view policies and client protocols

Builds on `SKILL.md` (connecting, the helper `scripts/vast_api.py`, the
read → plan → ask → apply → verify loop). Read that first; this file doesn't repeat it.
Below, `vast_api.py` means `scripts/vast_api.py`.

## Mental model

```
tenant ──< view policy  (who/how: security flavor, host rules, squash, SMB/S3 settings)
   │            │ 1
   │            ▼ n
   └────< view  (what/where: path + protocols + per-protocol names) ──> directory in the Element Store
                 │                     │
                 ├─ qos policy (VIEW)  ├─ quota on the same path (directory/user/group limits)
                 └─ BLOCK view = NVMe subsystem ──< volume ──< mapping >── block host (NQN)
```

- A **view** exposes one Element Store path to one or more protocols. Every view has exactly
  one **view policy**; one policy can serve many views. A view belongs to a tenant.
- Deleting a view **does not delete the directory** (KB "Views and View Policies").
- The **security flavor** of the policy decides whose permission model rules the data:
  pick it from the protocols the view will serve, *before* clients write data.
- Quotas attach to a **path**, not to a view. QoS policies attach to a view, a volume or users.
- Block subsystems are views whose **only** protocol is BLOCK, on a new, empty, non-nested path.
- Network access (VIP pools, DNS) and identities (AD/LDAP, S3 keys, bucket policies) are
  prerequisites from `references/tenants-network.md` and `references/identity-access.md`.

Order of creation: tenant and VIP pool → providers/users → view policy → view (with
`create_dir`) → quota / QoS → client mount. For block: policy → BLOCK view → volume →
block host → mapping → client connect.

## Check the API on this cluster first

```bash
vast_api.py version
vast_api.py spec show /views/ post          # view fields, protocols enum
vast_api.py spec model ViewPolicy           # policy fields (flavor is a free string here)
vast_api.py spec model View | grep -i deleg # allowed_delegations enum
vast_api.py spec paths 'quota|qos|volume|block'
vast_api.py kb search 'Managing Views|Managing View Policies' --version <X.Y>
```

What the 5.5.3 spec says *(5.5 API, checked on 5.5.3)*:

| Object | Endpoint | Required on create | Key fields |
|---|---|---|---|
| View | `/views/` | `path`, `policy_id` | `protocols` (NFS, NFS4, SMB, S3, ENDPOINT, DATABASE, KAFKA, BLOCK), `alias`, `share`, `bucket`, `bucket_owner`, `tenant_id`, `qos_policy_id`, `allowed_delegations`, `name` (block subsystem) |
| View policy | `/viewpolicies/` | `name` | `flavor`, `nfs_read_write`, `nfs_read_only`, `nfs_root_squash`, `nfs_all_squash`, `nfs_no_squash`, `smb_read_write`, `smb_read_only`, `s3_read_write`, `s3_read_only`, `auth_source`, `access_flavor`, `s3_visibility`, `s3_visibility_groups`, `tenant_id` |
| Quota | `/quotas/` | `name`, `path` | `soft_limit`, `hard_limit`, `soft_limit_inodes`, `hard_limit_inodes`, `grace_period`, `is_user_quota`, `default_user_quota`, `user_quotas`, `group_quotas`, `tenant_id` |
| QoS policy | `/qospolicies/` | `name` | `policy_type` VIEW/USER/VOLUME, `mode` STATIC/USED_CAPACITY/PROVISIONED_CAPACITY, `limit_by` BW/IOPS/BW_IOPS, `static_limits`, `capacity_limits` |
| Volume | `/volumes/` | `name`, `size`, `view_id` | `qos_policy_id`; map with `/volumes/{id}/set_hosts/` |
| Block host | `/blockhosts/` | `name`, `nqn` | `tenant_id`; map with `/blockhosts/{id}/set_volumes/` |

**Gaps in the cluster's own spec** *(seen on 5.5.3)*: `create_dir` (and `create_dir_mode`,
`inherit_acl`) are accepted on `POST /views/` and `POST /quotas/` but are **not in the
swagger**; they are in the KB API reference ("Create View", "Create a Quota", API 5.5) and
used by vastpy, Terraform and vast-csi. The policy `flavor` is a plain string in the swagger;
the KB API reference ("Create View Policy", API 5.5) lists `NFS`, `SMB`, `MIXED_LAST_WINS`,
`S3_NATIVE`, `BLOCK`. The bodies of `set_hosts`/`set_volumes` are shown as the whole object
in the swagger; the KB gives the real body (`{"ids": [...]}`). When spec and KB disagree,
prefer the KB API reference for *request shape*, then dry-run and read back.

## Security flavors and protocols

From KB "Controlling File and Directory Permissions Across Protocols"
(https://kb.vastdata.com/documentation/docs/security-flavors.md) and "Managing View Policies" (5.5):

| Flavor (API value) | Who may set permissions | Checking algorithm | Use it for |
|---|---|---|---|
| NFS (`NFS`) | NFS mode bits (and POSIX ACLs via NFSv3 if enabled); SMB set-permission fails; S3 ACL changes ignored | NFS (first matching entry) | Linux/NFS-first data. Set `smb_file_mode`/`smb_directory_mode` for files made by SMB/S3. |
| SMB (`SMB`) | SMB (NTFS ACLs) only | SMB (union of matching ACEs) | Windows-first shares |
| Mixed Last Wins (`MIXED_LAST_WINS`) | all protocols, incl. NFSv4 ACLs; narrow with `access_flavor` NFS4/SMB/ALL | similar to SMB | true NFS+SMB multi-protocol; required for NFSv4 ACLs |
| S3 Native (`S3_NATIVE`) | S3 ACLs and identity/bucket policies; NFS/SMB permission changes silently ignored | S3 (policies, then ACLs) | buckets; **required for DATABASE (and so KAFKA) views** |
| Block (`BLOCK`) | n/a | none (VIP pool, tenant, host NQN mapping) | block subsystems |

Protocol support per flavor (KB table): NFSv3, SMB and S3 work with every file flavor.
NFSv4 works with NFS and S3 Native **without NFSv4 ACLs**, and with Mixed Last Wins with ACLs.
The KB's security-flavors table says NFSv4 is **not** supported with the SMB flavor, while
"Managing View Policies" (5.5) says SMB flavor supports NFSv4: check on the cluster (dry run,
then read back) before relying on SMB flavor + NFS4. More detail, the S3-native NFS/SMB
action mappings and every policy field: `references/views-protocols/view-policies.md`.

## Workflows

Each follows the loop in `SKILL.md`. Take stock first:

```bash
vast_api.py get tenants fields=id,name,allowed_delegations
vast_api.py get vippools fields=id,name,role,tenant_id,domain_name
vast_api.py get viewpolicies fields=id,name,flavor,tenant_id,nfs_read_write,nfs_root_squash
vast_api.py get views fields=id,path,protocols,policy,alias,share,bucket,tenant_id
vast_api.py get quotas path=/exports/projects
```

Show the user what exists and the exact requests (dry runs) below; ask once; then apply
with `--yes`, reading each object back before the next. Placeholders: `<tenant_id>`,
`<policy_id>`, client hosts in `<client-subnet/cidr>`.

### 1. NFS export for a host range (NFSv3 and/or NFSv4.1)

KB: "Managing Views", "Managing View Policies", "Host-Based Access Rules" (5.5).

1. Policy limiting access to one subnet, root squashed:
   ```bash
   vast_api.py call POST /viewpolicies/ --data '{"name": "nfs-lab-subnet", "tenant_id": <tenant_id>,
     "flavor": "NFS", "nfs_read_write": ["<client-subnet/cidr>"], "nfs_read_only": [],
     "nfs_root_squash": ["<client-subnet/cidr>"]}'
   ```
   Hosts can be an IP, CIDR, a range with `*` per octet (`<a.b.c>.*`), an FQDN or a netgroup
   (`@group`); prefix `~` in read/write to deny. Hosts in neither read/write nor read-only
   lists have **no** access. Squash rules apply to NFSv3 (and not to NFSv4 with Kerberos).
2. View, creating the directory:
   ```bash
   vast_api.py call POST /views/ --data '{"path": "/exports/projects", "create_dir": true,
     "protocols": ["NFS", "NFS4"], "policy_id": <policy_id>, "tenant_id": <tenant_id>,
     "alias": "/projects"}'
   ```
   `alias` is an NFSv3-only shorter mount path, unique in the tenant, starting with `/`.
3. Read back: `vast_api.py get views path=/exports/projects`. Mount: see
   `references/views-protocols/clients-and-csi.md` (`mount -o vers=3 <vip-or-dns>:/projects /mnt/projects`,
   `mount -o vers=4.1 <vip-or-dns>:/exports/projects /mnt/projects`).

NFSv4 specifics (KB "NFSv4 File Delegations" 5.5, "Limiting Access to / (root) for NFSv4"):
- NFSv4 mounts traverse a **pseudo file system from `/`**: every directory above the export
  must be traversable by the client. If a view higher in the tree is NFS-enabled it must also
  have NFSv4, otherwise mounts fail with `mount(2): Operation not permitted`.
- **Delegations**: tenant field `allowed_delegations` (DISABLED|READ|WRITE|READ_WRITE|NONE;
  READ_WRITE on the tenants seen on 5.5.3) sets the default; view field `allowed_delegations`
  (NONE|READ|WRITE|READ_WRITE|USE_TENANT_ALLOWED_DELEG, default USE_TENANT_ALLOWED_DELEG)
  overrides it; read the result in the view's `effective_allowed_delegations` *(5.5 API,
  seen on 5.5.3)*. If the tenant is DISABLED, no view can enable them. Delegations need
  NFS ≥ 4.1 clients, NTP, and a backchannel; set `NONE` on views shared live with
  NFSv3/SMB/S3 writers if clients need to see others' changes at once (close-to-open
  consistency is kept only between NFSv4 clients). List/revoke: `GET /tenants/{id}/nfs4_delegs/`,
  `DELETE /tenants/{id}/nfs4_deleg/`.

### 2. SMB share

KB: "SMB File Sharing Protocol" (https://kb.vastdata.com/documentation/docs/smb-file-sharing-protocol-55.md),
"Share-Level ACLs", "Authentication for SMB Access" (5.5).

Prerequisite: the tenant is joined to Active Directory (SMB requires it; see `references/identity-access.md`).
```bash
vast_api.py call POST /viewpolicies/ --data '{"name": "smb-share", "tenant_id": <tenant_id>, "flavor": "SMB"}'
vast_api.py call POST /views/ --data '{"path": "/shares/finance", "create_dir": true,
  "protocols": ["SMB"], "share": "finance", "policy_id": <policy_id>, "tenant_id": <tenant_id>}'
```
- Share name: unique in the tenant, none of `/\:|<>*?"`, and **cannot be changed later**.
- Optional per view: `share_acl` (share-level ACL), `smb_encryption_state`
  (AVAILABLE|DESIRED|REQUIRED|OFF, at least the tenant's), ABE (`abe_protocols`, `abe_max_depth`).
- Per policy: `smb_is_ca` (continuous availability), `disable_read_lease` / `disable_write_lease`
  / `disable_handle_lease`, `smb_read_write` / `smb_read_only` host lists.
- Clients connect to `\\<dns-name>\finance` with Kerberos (use a DNS name, not an IP).

### 3. Multi-protocol view (NFS + SMB, optionally S3)

Use `MIXED_LAST_WINS` (any protocol can set permissions; NFSv4 ACLs supported):
```bash
vast_api.py call POST /viewpolicies/ --data '{"name": "mixed", "tenant_id": <tenant_id>,
  "flavor": "MIXED_LAST_WINS", "access_flavor": "ALL", "auth_source": "PROVIDERS",
  "nfs_read_write": ["<client-subnet/cidr>"]}'
vast_api.py call POST /views/ --data '{"path": "/shared/eng", "create_dir": true,
  "protocols": ["NFS", "NFS4", "SMB"], "share": "eng", "policy_id": <policy_id>, "tenant_id": <tenant_id>}'
```
- Users must resolve to the same identity on every protocol: uidNumber/gidNumber on the AD
  or LDAP entries (KB "Workflow for Enabling Client Protocol Access"). `auth_source`
  RPC | PROVIDERS | RPC_AND_PROVIDERS decides where NFS group memberships come from.
- Choose NFS flavor instead if Linux owns the data and SMB is occasional; SMB flavor if
  Windows owns it. **Changing the flavor of a policy in use changes who can access existing
  files**: warn the user and prefer a new view/policy on a test path first.
- Add `"S3"` with `bucket` and `bucket_owner` to also serve S3 (S3 then follows the flavor's
  rules: under Mixed Last Wins identity and bucket policies are ignored).

### 4. S3 bucket view (basics)

KB: "Creating S3 Buckets via VMS" (https://kb.vastdata.com/documentation/docs/creating-s3-buckets-via-vms-55.md),
"Managing S3 Request-Initiated Bucket Creation" (5.5). Keys, identity and bucket policies: `references/identity-access.md`.
```bash
vast_api.py call POST /views/ --data '{"path": "/buckets/media", "create_dir": true,
  "protocols": ["S3"], "bucket": "media", "bucket_owner": "<s3 user name>",
  "policy_id": <S3_NATIVE policy id>, "tenant_id": <tenant_id>}'
```
- `bucket` is unique across **all tenants**; `bucket_owner` must be an existing user (local or
  provider) *(KB)*. Versioning (`s3_versioning`) and object lock (`locking`) cannot be turned
  off after creation and need an S3 Native policy.
- `s3_object_ownership_rule` (None|BucketOwnerPreferred|ObjectWriter|BucketOwnerEnforced) sets
  ACLs enabled/disabled for S3 Native views.
- Bucket **listing**: policy `s3_visibility` / `s3_visibility_groups` let users/groups list
  buckets made with the policy without access to them. For NFS/SMB on an S3 Native bucket:
  `s3_flavor_allow_free_listing` (list regardless of object permissions) and
  `s3_flavor_detect_full_pathname` (match identity-policy resources on full paths).
- A policy with `is_s3_default_policy: true` is used for buckets created through the S3 API.
  `ENDPOINT` views are templates for S3-API bucket creation (KB: default tenant only; may be
  combined with NFS/NFS4).
- **Tabular/event data**: `DATABASE` (with `S3`) and `KAFKA` (adds DATABASE and S3) views need
  an S3 Native policy; see `references/database.md`, `references/event-broker.md`.

### 5. Quotas

KB: "Overview of Quotas", "Managing Quotas", "Managing Quota Groups", "Resetting Quota Grace Period" (5.5),
e.g. https://kb.vastdata.com/documentation/docs/managing-quotas-55.md.
```bash
vast_api.py call POST /quotas/ --data '{"name": "projects", "path": "/exports/projects", "tenant_id": <tenant_id>,
  "soft_limit": 900000000000, "hard_limit": 1000000000000, "grace_period": "7d",
  "soft_limit_inodes": 9000000, "hard_limit_inodes": 10000000}'
```
- Limits are bytes / file+directory counts. Soft → `SOFT_EXCEEDED` alarm only; with a
  `grace_period`, writes are blocked after it expires (`GRACE_EXPIRED`); hard → writes blocked.
  Without a grace period, only the hard limit blocks. Grace syntax: `10d`, `10h`, `90m`
  (lower case) or `[DD] [HH:[MM:]]ss` *(KB)*.
- User/group quotas: `is_user_quota: true` (**cannot be disabled later**), then
  `default_user_quota` / `default_group_quota` `{soft_limit, hard_limit, grace_period, ...}`
  and per-entity `user_quotas` / `group_quotas` `[{"entity": {"identifier": "<name|uid>",
  "identifier_type": "<type>", "is_group": false}, "hard_limit": ...}]`. Check the
  identifier types in the KB "Create a Quota" API page before use.
- Usable- vs logical-capacity limits (`is_physical_quota`) are fixed at creation.
- Max nesting 16 quota levels; the most restrictive applies. Quota groups
  (`/quotagroups/`) cap a set of quotas together (a quota in ≤4 groups; membership is replaced
  as a whole). Reset grace: `PATCH /quotas/{id}/reset_grace_period/`.

### 6. QoS on a view or volume

KB: "QoS Overview", "Creating a QoS Policy" (5.5), https://kb.vastdata.com/documentation/docs/qos-overview-55.md.
```bash
vast_api.py call POST /qospolicies/ --data '{"name": "projects-qos", "policy_type": "VIEW", "mode": "STATIC",
  "limit_by": "BW_IOPS", "tenant_id": <tenant_id>,
  "static_limits": {"max_reads_bw_mbps": 2000, "max_writes_bw_mbps": 1000, "max_reads_iops": 20000, "max_writes_iops": 10000}}'
vast_api.py call PATCH /views/<view_id>/ --data '{"qos_policy_id": <qos_id>}'
```
- `static_limits` keys are not in the cluster swagger (an untyped object); the names above are
  from the KB "Create QoS Policy" API page (5.5) and the Terraform provider. 0 = unlimited.
  Credits default to 4× the max limit.
- Capacity-based modes (`USED_CAPACITY`, `PROVISIONED_CAPACITY`) use `capacity_limits`
  (`max_reads_bw_mbps_per_gb_capacity` ...); on a view without a quota, VMS creates one.
- Several applicable policies (user + view) → the strictest wins. Replication and snapshot
  traffic is not governed by view/user QoS.

### 7. Block volume for a host (NVMe/TCP)

KB: "Provisioning Block Storage with VMS" (https://kb.vastdata.com/documentation/docs/provisioning-block-storage-with-vms-55.md),
"Configuring an NVMe/TCP Client on Linux for VAST Cluster Block Storage" (5.5).
1. Subsystem = BLOCK-only view on a **new** path, not under another subsystem, with a
   subsystem `name` (unique in the tenant, part of the generated `nqn`). Use a policy with
   flavor `BLOCK` (look for `is_block_default_policy: true`) or one the KB allows:
   ```bash
   vast_api.py call POST /views/ --data '{"path": "/block/db01", "create_dir": true, "protocols": ["BLOCK"],
     "name": "db01", "policy_id": <block policy id>, "tenant_id": <tenant_id>}'
   ```
   Read back its `nqn`.
2. Volume (size in **bytes** per the KB API page; UI range 1 GB–1000 TB; `name` is a path
   relative to the subsystem, no leading `/`):
   `vast_api.py call POST /volumes/ --data '{"view_id": <subsystem view id>, "name": "vol1", "size": 107374182400}'`
3. Host (NQN from the client's `/etc/nvme/hostnqn`):
   `vast_api.py call POST /blockhosts/ --data '{"name": "dbhost1", "nqn": "nqn.2014-08.org.nvmexpress:uuid:<uuid>", "tenant_id": <tenant_id>}'`
4. Map: `PATCH /volumes/<vol_id>/set_hosts/ {"ids": [<host_id>]}` **replaces** the volume's host
   list; `PATCH /volumes/<vol_id>/update_hosts/ {"ids_to_add": [...], "ids_to_remove": [...]}`
   changes it incrementally (KB API 5.5). Both return an `async_task`: follow it, then
   `vast_api.py get blockmappings`. Unmapping cuts the host's I/O: warn first.
5. Client: `nvme discover -t tcp -a <vip> -s 8009`, `nvme connect-all ...`, `nvme list-subsys`
   (`references/views-protocols/clients-and-csi.md`).

`/volumes/` and `/blockhosts/` lists are paginated (`count`, `results`) even without
`page_size` *(seen on 5.5.3)*.

### 8. Kubernetes: vast-csi storage classes

Public driver: https://github.com/vast-data/vast-csi (Helm repo `https://vast-data.github.io/vast-csi`,
charts `vastcsi` for NFS, driver `csi.vastdata.com`; `vastblock` for NVMe/TCP block,
driver `block.csi.vastdata.com`). KB: "Deploy VAST CSI Driver"
(https://kb.vastdata.com/documentation/docs/deploy-vast-csi-driver-27.md), "Provision Volumes with VAST CSI Driver".
- Cluster side, before installing: a VIP pool and a view policy **in the same tenant**, a VMS
  user (or API token) for the driver, and a base `storagePath` (NFS) or subsystem view (block).
  The driver creates one view per PV with that policy and deletes it with the PV.
- Values and a StorageClass example: `references/views-protocols/clients-and-csi.md`. Check `values.yaml` of the
  chart version you install; options change between driver releases.

## Pitfalls

| Symptom / exact error | Cause | Fix |
|---|---|---|
| `A view where the Database is in the list of protocols can only have a view policy where the security flavor is S3 native.` *(seen on 5.5.3)* | DATABASE (or KAFKA) view with an NFS/SMB/Mixed policy | Create/choose a policy with `"flavor": "S3_NATIVE"` and use its id. |
| View create rejected because the path doesn't exist (exact text varies by release) | Directory missing and `create_dir` not sent | Add `"create_dir": true` (missing from the swagger, documented in the KB API reference). |
| NFS client `access denied by server` / mount refused | Client IP not in `nfs_read_write` or `nfs_read_only`, or matches a `~` deny, or the VIP pool isn't allowed for the policy/tenant | Read the policy; add the host/CIDR; check the client reaches a VIP of the view's tenant. |
| NFSv4 mount: `mount(2): Operation not permitted` while NFSv3 works | A parent view on the path is NFSv3-only, or a directory above isn't traversable | Give parent NFS views NFSv4 too, or mount a path with no NFS view above it; keep `x` on parents (KB "Limiting Access to / (root) for NFSv4"). |
| root on the client gets `Permission denied` | Root squash (default for `*`) | Add only admin hosts to `nfs_no_squash`; don't broaden it. |
| SMB: setting ACLs from Windows fails | Policy flavor NFS (or S3 Native) | Use SMB or MIXED_LAST_WINS flavor (plan migration; existing permissions change meaning). |
| `setfacl` blocked on NFSv3 | `nfs_posix_acl` off, or flavor not NFS | Enable POSIX ACL in an NFS-flavor policy. |
| NFSv4 `nfs4_setfacl` fails | NFSv4 ACLs need MIXED_LAST_WINS | Switch flavor (or accept mode bits). |
| S3 user can't read a file written over NFS (or vice versa) | Flavor rules: S3 Native default ACL gives only the owner access; NFS flavor needs traverse on every parent | Grant via identity/bucket policy (S3 Native) or fix mode bits (NFS). |
| SMB share name rejected / can't rename | Forbidden character, duplicate in tenant, or rename after creation | Pick a valid unique name; to rename, create a new view on the same path. |
| Bucket name rejected | Bucket names are cluster-wide unique | Choose another name. |
| View-level delegations ignored; `effective_allowed_delegations` not what you set | Tenant `allowed_delegations` is DISABLED | Enable at tenant level first (changes behaviour for all its views: ask). |
| NFSv4 client doesn't see a change made over NFSv3/SMB/S3 | Client holds a delegation | Set view `allowed_delegations` to `NONE` for shared multi-protocol data. |
| Writes blocked below the hard limit | Soft limit exceeded for longer than `grace_period` | Free space or raise the limit; `PATCH /quotas/{id}/reset_grace_period/`. |
| Can't turn off user quotas / switch logical↔usable | Both fixed at creation | Recreate the quota (removing a quota removes its enforcement: ask). |
| BLOCK view rejected | Other protocols listed, path exists or is under another subsystem, or no `name` | BLOCK alone, new path, unique subsystem name. |
| Host sees no namespaces after `nvme connect` | Volume not mapped to that host's NQN, or NQN typo, or wrong tenant VIP | Check `get blockmappings`; compare NQN with `/etc/nvme/hostnqn`; use a VIP of the subsystem's tenant. |
| CSI PVC stuck Pending; driver log shows VMS 400 with a token | Secret has both an API token and `tenant` | Omit `tenant` with tokens / cluster admins (vast-csi `values.yaml`). |
| CSI mount fails cross-tenant | `vipPool` and `viewPolicy` in different tenants | Use a pool and policy from the same tenant. |

More cases and client-side errors: `references/views-protocols/clients-and-csi.md`.

## Destructive operations (warn before each)

- **Deleting a view** cuts every client of it (mounts go stale, shares and buckets vanish);
  data stays. **Changing `protocols` or `policy_id` on a live view** can lock clients out.
- **Changing a policy's flavor or host lists** affects every view using it: list them
  (`get views policy=<policy name> fields=id,path,policy`) and show the user. On 5.5.3
  `views?policy_id=<id>` is silently ignored (returns all views); `policy=<name>` filters.
  Re-check client-side either way.
- Deleting a quota removes enforcement; deleting a volume destroys its data; unmapping a
  volume stops host I/O.

## Related areas

`SKILL.md` (foundation), `references/tenants-network.md` (VIP pools, DNS, tenants),
`references/identity-access.md` (AD/LDAP, users, S3 keys, bucket/identity policies),
`references/database.md`, `references/event-broker.md`, `references/data-protection.md` (snapshots, replication),
`references/monitoring.md` (view/QoS metrics).

Verified: VAST 5.5.3 — spec read (views, viewpolicies, quotas, qospolicies, volumes,
blockhosts, tenants), KB 5.5 product and API pages read, live read-only listings of views,
policies, tenants and block objects; vast-csi 2.7.x chart values read. No objects were created.
