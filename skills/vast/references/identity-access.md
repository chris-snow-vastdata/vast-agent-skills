# VAST identity and access: users, providers, keys, policies, admins, audit

Builds on `SKILL.md` (connecting, logins, API tokens, tenant context, the helper, safe
changes). Read it first; this file does not repeat it. Below, `vast_api.py` means
`python3 scripts/vast_api.py` (the shared helper, relative to this folder).

## Mental model: three kinds of identity

VAST keeps three separate identity planes. Most mistakes come from mixing them up.

| Plane | Who | Objects (5.5 API path) | Used for |
|---|---|---|---|
| **Data-access users** | people and services reading/writing data over NFS, SMB, S3, VAST DB | users `/users/`, groups `/groups/`, *VAST providers* (local) `/localproviders/`, external providers `/activedirectory/`, `/ldaps/`, `/nis/`, plus Kerberos and OIDC | file/object ownership, UID/GID/SID, S3 keys, identity policies |
| **S3 credentials and policy** | a data-access user (or IAM role) | access keys `/users/{id}/access_keys/`, `/users/non_local_keys/`, self-service `/s3keys/`; identity policies `/s3policies/`; bucket policies (S3 API); IAM roles `/iamroles/` | who may do which S3 action on which bucket/object |
| **VMS management** | admins and automation using the Web UI/REST API | managers `/managers/`, roles `/roles/`, permissions `/permissions/`, realms `/realms/`, API tokens `/apitokens/` | who may configure the cluster or a tenant |

How they connect:

- A **tenant** picks its providers: one VAST provider (`local_provider_id`) plus optionally
  AD (`ad_provider_id`), LDAP (`ldap_provider_id`), NIS (`nis_provider_id`), Kerberos and OIDC
  (`krb_provider_id`, `oidc_provider_id`), and which one wins POSIX conflicts
  (`posix_primary_provider`: `NONE|LDAP|NIS|AD|LOCAL|KEYSTONE`) *(5.5 API, Tenant)*.
  Users are looked up only in the providers of the tenant they access.
- **Local (VAST provider) users** are created on the cluster with a name and UID; the cluster
  generates the SID. Local attributes **override** conflicting POSIX attributes from external
  providers (KB "VAST Providers"). External users are not created; they are *queried*, and
  VMS keeps their extra attributes (S3 keys, identity policies, bucket flags).
- **S3 keys belong to a user in one tenant** ("The key pair allows access to a single tenant",
  KB "Managing S3 User Permissions"). S3 permissions come from identity policies on the user
  or their groups, bucket policies on the bucket, the user flags `allow_create_bucket`,
  `allow_delete_bucket`, `s3_superuser`, and bucket ownership/ACLs.
- **Managers** have a `user_type` (`SUPER_ADMIN` = cluster admin, `TENANT_ADMIN`, `TENANT_USER`)
  *(5.5 API)* and get rights from **roles** (sets of permissions = action x realm). AD/LDAP
  groups can be attached to roles so directory users log into VMS without a manager account.
- Cluster-wide security settings sit beside these: **encryption at rest** (encryption groups,
  EKM), **certificates/mTLS** for VMS, and **auditing** (protocol audit and VMS events).

Order of creation for a fresh tenant: provider(s) -> tenant (references the providers;
encryption group must be chosen here) -> groups -> users -> identity policies -> attach
policies -> S3 keys -> roles -> managers / directory groups on roles.

## Check on this cluster before you act

1. `vast_api.py version`, then KB for that release:
   `vast_api.py kb search 'VAST Providers|Active Directory|Identity Polic' --version 5.5`.
2. Endpoints and fields: `vast_api.py spec paths 'users|groups|localproviders|s3policies'`,
   `vast_api.py spec show /users/ post`, `vast_api.py spec model Tenant`.
3. **The Swagger spec is incomplete for some write calls** *(seen on 5.5.3)*: the bodies of
   `/users/{id}/access_keys/`, `/users/non_local_keys/`, `/roles/` and the AD join show the
   object's generic fields, not the parameters the call really takes. For those, this file gives
   the parameters used by VAST's public tools (Terraform provider `vast-data/vastdata`,
   Ansible collection `vastdata.vms`, `vast-csi`) and the KB CLI page; dry-run first
   (`vast_api.py call ...` without `--yes`) and read the object back afterwards.
4. Take stock read-only (no secrets in any of these):

```bash
vast_api.py get tenants fields=id,name,local_provider_id,ad_provider_id,ldap_provider_id,nis_provider_id,posix_primary_provider,tenant_admins_group_name,application_users_group_name
vast_api.py get localproviders            # managed_by: SUPER_ADMIN|TENANT_ADMIN|APP_USER
vast_api.py get activedirectory ; vast_api.py get ldaps ; vast_api.py get nis
vast_api.py get users fields=id,name,uid,local_provider_id,s3_policies_ids,allow_create_bucket,s3_superuser
vast_api.py get groups fields=id,name,gid,local_provider_id,s3_policies_ids
vast_api.py get s3policies fields=id,name,tenant_id,enabled,users,groups
vast_api.py get managers fields=id,username,user_type,tenant_id,roles,is_active
vast_api.py get roles fields=id,name,tenant_id,tenants,ldap_groups,is_default,permissions
vast_api.py get users/available_contexts  # which providers user queries can search
```

Per-object field tables: `references/identity-access/objects-and-fields.md`.

## Workflows

Each workflow: take stock, show the user the exact requests, get a yes, apply one object at
a time and read it back (`SKILL.md`, "How to do any VAST task").

### 1. Local user with an S3 access key

KB: "VAST Providers" https://kb.vastdata.com/documentation/docs/vast-providers-55.md,
"Managing S3 User Permissions" https://kb.vastdata.com/documentation/docs/managing-s3-user-permissions-55.md

1. Find the tenant's VAST provider: `get tenants name=<tenant> fields=id,local_provider_id`.
2. Pick a free UID/GID (`get users uid=<n>`; also check your directory if one is attached, as
   a local user with the same name or UID overrides the external one).
3. Create the group if needed: `POST /groups/` `{"name":"<group>","gid":<gid>,"local_provider_id":<lp>}`
   (`name`, `gid` required, 5.5 API).
4. Create the user: `POST /users/` `{"name":"<user>","uid":<uid>,"local_provider_id":<lp>,...}`.
   Group membership and leading group: check `spec show /users/ post` (5.5 lists `leading_gid`,
   `gids`, `groups`); the Web UI picks groups by name. Read back with `get users name=<user>`.
5. Generate the key pair, for the tenant the user will use:
   `POST /users/<id>/access_keys/` `{"tenant_id": <tenant id>}` -> `{"access_key": ..., "secret_key": ...}` *(worked on 5.5.3)*.
   **The secret key is returned once and cannot be retrieved again.** Give it to the user
   directly; do not echo it into logs, files or chat beyond what they asked for.
6. Grant S3 rights (workflow 5), then test with an S3 client against a VIP of that tenant.

vastpy-cli equivalent: `vastpy-cli post users name=<user> uid=<uid> local_provider_id=<lp>`
(check `vastpy-cli --help`). Terraform: `vastdata_user`, `vastdata_group`, `vastdata_user_key`.

### 2. S3 key for an AD/LDAP/NIS user (non-local)

1. Look the user up in the tenant: `vast_api.py get users/query username=<name> tenant_id=<t> context=aggregated`
   (works on 5.5.3; `context` can also restrict to `local`, `ad`, `ldap`, `nis`; a miss returns
   `404 {"detail": "User not found."}`).
2. Generate: `POST /users/non_local_keys/` `{"username":"<name>","tenant_id":<t>}` (or `uid`, `sid`,
   `login_name`; optional `context`) -> access and secret key, once.
3. Disable: `PATCH /users/non_local_keys/` `{"access_key":"<AK>","enabled":false,"tenant_id":<t>,"uid":<uid>}`;
   delete: `DELETE` with the same identifiers plus `access_key`. Keys are listed in the
   `access_keys` of the `users/query` result.
4. Self-service alternative: directory users can manage their own pair with their own login:
   `POST /s3keys/`, `GET /s3keys/`, delete with the access key in the body (KB "Enabling Active
   Directory/LDAP Users to Create S3 Access Key Pairs"; on 5.5.3 the spec lists the delete as
   `DELETE /s3keys/delete/`, the KB page shows `DELETE /s3keys/`: check `spec paths s3keys`).

### 3. Rotate (or revoke) an S3 key

**Impact:** disabling or deleting a key immediately breaks every client using it. Revoking is
instant; there is no grace period. Rotate with overlap:

1. List the user's current keys (`get users/<id>` -> `access_keys`; external users via `users/query`).
2. Create a second key (workflow 1 step 5 or 2 step 2). The UI shows status per key; check the
   limit of keys per user on your release in the KB if creation fails.
3. The user switches every client to the new key; confirm (protocol audit with S3 enabled, or
   the user's word).
4. Disable the old key: `PATCH /users/<id>/access_keys/` `{"access_key":"<old AK>","enabled":false,"tenant_id":<t>}`.
   Wait for a quiet period; re-enable (`"enabled": true`) if something breaks.
5. Delete it: `DELETE /users/<id>/access_keys/` `{"access_key":"<old AK>","tenant_id":<t>}`.

For a **suspected leak**, skip the overlap: disable first, then issue a new key. Temporary
(STS) credentials of IAM roles have their own revoke: `PATCH /iamroles/<id>/revoke_access_keys/`.
CLI equivalents: `user generate-key`, `user modify-key --disable` (KB 5.5 CLI pages).

### 4. Join Active Directory and use it in a tenant

KB: "Active Directory" https://kb.vastdata.com/documentation/docs/active-directory-55.md,
"Authorization Providers in VAST Cluster" https://kb.vastdata.com/documentation/docs/authorization-providers-in-vast-cluster-55.md

Prerequisites (KB): DNS on the cluster resolves the AD domain; an AD account allowed to create
machine accounts in the target OU; a bind account with read access. SMB **requires** a joined
AD; NFS/S3 can use AD for authorization without joining.

1. Create the configuration: `POST /activedirectory/` with `domain_name`,
   `machine_account_name` (max 15 characters, 5.5 API), `organizational_unit` (DN), and the LDAP
   side: `binddn`, `bindpw`, `method` (`simple`/`sasl`/`anonymous`...), `port` (389, or 636 for
   LDAPS), `use_tls`/`use_ldaps`, attribute mapping. Check `spec show /activedirectory/ post` and
   `spec show /ldaps/ post`. For AD the KB recommends `posix_account=user`, `posix_group=group`,
   `uid=sAMAccountName`.
2. Join: `PATCH /activedirectory/<id>/` `{"enabled": true, "admin_username": "<join user>", "admin_passwd": "<pw>"}`
   (fields from the Terraform provider; not in the 5.5.3 Swagger body; the KB says the join
   credentials are used once and not stored). Poll `get activedirectory/<id>` until `state` is
   joined; then `get activedirectory/<id>/domains`, `.../dcs`, `.../current_gc` to see discovery.
3. Attach it to the tenant: `PATCH /tenants/<t>/` `{"ad_provider_id": <id>}` and, if another
   external provider is attached, choose `posix_primary_provider` (KB "Setting the Primary POSIX Provider").
4. Verify: `get users/query username=<a known AD user> tenant_id=<t> context=ad` returns UID/SID/groups.

**Impact / pitfalls:** changing `ntlm_enabled` needs leave -> change -> rejoin (KB). Leaving
deletes the machine account; if DCs are unreachable, leave fails and deleting the configuration
leaves the machine account behind (KB). Changing providers or `posix_primary_provider` on a
live tenant changes UID/GID resolution, and therefore file access, for every client.

LDAP and NIS are the same pattern without a join: `POST /ldaps/` (`urls`, `searchbase`,
`binddn`/`bindpw`, mapping) or `POST /nis/` (`domain_name`, `servers`), then set
`ldap_provider_id` / `nis_provider_id` on the tenant. KB: "LDAP"
https://kb.vastdata.com/documentation/docs/ldap-55.md, "NIS" https://kb.vastdata.com/documentation/docs/nis-55.md.

### 5. Grant S3 bucket access with an identity policy

KB: "Managing Identity Policies" https://kb.vastdata.com/documentation/docs/managing-identity-policies-55.md,
"Identity and Bucket Policy Reference" https://kb.vastdata.com/documentation/docs/identity-and-bucket-policy-reference-55.md

1. Write the policy (AWS IAM JSON subset); see `references/identity-access/s3-keys-and-policies.md` for
   read-only, read-write, per-user-prefix examples and what is supported.
2. Create it in the bucket's tenant: `POST /s3policies/`
   `{"name":"<team>-<bucket>-rw","tenant_id":<t>,"policy":"<JSON as a string>","enabled":true}`
   (`name` and `policy` required; `policy` is a **string**, max 6145 characters on 5.5).
3. Attach: local user/group `PATCH /users/<id>/` or `/groups/<id>/` `{"s3_policies_ids":[<pid>,...]}`
   (the list **replaces** the current one: read it first and append). External user/group:
   `PATCH /users/query/` / `PATCH /groups/query/` with the identifiers plus `s3_policies_ids`
   (Terraform `vastdata_nonlocal_user`); check `spec show /users/query/ patch`.
4. Verify: `get s3policies/<pid>` shows `users`/`groups`; test with the user's key.

Prefer **groups** over per-user attachments. A bucket policy (per bucket, via the S3 API
`PutBucketPolicy`, only on views with the S3 Native security flavor, max 20 KB) is the other
way, best for "who may use *this* bucket" (KB "Managing Bucket Policies").

### 6. A tenant admin with a least-privilege role

KB: "Provisioning VMS Access" https://kb.vastdata.com/documentation/docs/provisioning-vms-access-55-1.md,
"Managing Managers" https://kb.vastdata.com/documentation/docs/managing-managers-55.md,
"Managing Administrative Roles" https://kb.vastdata.com/documentation/docs/managing-administrative-roles-55.md

1. Decide the rights as `<action>_<realm>` codenames from `get permissions` (actions
   create/view/edit/delete; realms on 5.5.3: applications, database, events, hardware, logical,
   monitoring, security, settings, support). Example "manage views and quotas, read the rest":
   `create_logical, edit_logical, delete_logical, view_logical, view_events, view_monitoring`.
   Tighter still: a custom realm of a few object types (`POST /realms/` `{"name":..., "object_types":["View","ViewPolicy","Quota"]}`,
   object types from `get realms/objects`). Details: `references/identity-access/rbac.md`.
2. Create a role tied to the tenant: `POST /roles/` `{"name":"<tenant>-ops","tenant_id":<t>,"permissions_list":[...]}`
   (`tenant_id` makes it a tenant-admin role; `permissions_list` takes codenames of the form
   `<create|view|edit|delete>_<realm>`, e.g. `view_logical` *(worked on 5.5.3)*, though the 5.5.3
   Swagger body doesn't list it: dry-run, then read the role back and compare `permissions`).
3. Create the manager: `POST /managers/` `{"username":"<name>","password":"<temp>","user_type":"TENANT_ADMIN","tenant_id":<t>,"roles":[<role id>],"is_temporary_password":true}` *(this shape worked on 5.5.3)*.
   The user logs in to the tenant's Web UI login (per KB `https://<VMS>/#/login/<tenant>`) or
   calls the API with `X-Tenant-Name: <tenant>` (`SKILL.md`).
4. Directory-based alternative (no local password): add `"ldap_groups":["<group>@<domain>"]` to the
   role, and set the tenant's `tenant_admins_group_name` to that group (Terraform tenant docs:
   members need both). For cluster admins from AD/LDAP use the provider's `super_admin_groups`.
5. Verify by logging in as the new admin and running a read and a write the role should and
   should not allow (expect 403 for the latter).

**Impact:** editing a role changes the rights of every manager and directory group on it
immediately. Never edit the default roles (`administrators`, `read_only`, `configuration`,
`csi`, ... seen on 5.5.3): copy them (KB). `os_ssh_login: true` on a role gives its directory
groups SSH to the CNodes with the `vastdata` user's rights (KB): only on explicit request.

### 7. Application users (DataEngine, VAST Database, S3 apps)

Application users are data-access users (local or directory) that log in to a tenant's VMS for
app work (DataEngine UI/`vastde`, their own S3 keys), not managers. On 5.5: a VAST provider has
`managed_by` (`SUPER_ADMIN|TENANT_ADMIN|APP_USER`), the tenant has
`application_users_group_name`, and a local user can have a `password` (VMS login; the user
must change a temporary one at first login, KB "VAST Providers"). A user can be on the tenant
admins group or the app users group, not both (KB "Cluster and Tenant Admins"
https://kb.vastdata.com/docs/3-cluster-and-tenant-admins.md). The exact combination required
varies by release: read the KB for the release and `references/dataengine.md`, and confirm by
logging in as the user. App users manage their own keys (Web UI avatar -> Manage Access Keys;
KB "Managing Your Access Keys").

### 8. Turn on protocol auditing

KB: "Configuring Global Auditing Settings" https://kb.vastdata.com/documentation/docs/configuring-global-auditing-settings-55.md,
"Viewing Protocol Audit Logs" https://kb.vastdata.com/documentation/docs/viewing-protocol-audit-logs-55.md

1. Read current settings: `vast_api.py get clusters/<id>/auditing` (`id` from `get clusters fields=id`).
2. `PATCH /clusters/<id>/auditing/` with: `protocols` (which protocols; values: check a setting
   made in the Web UI and read back, the CLI uses `NFSv3,SMB,...`), `protocols_audit` (object of
   booleans: `create_delete_files_dirs_objects`, `modify_data`, `modify_data_md`, `read_data`,
   `read_data_md`, `session_create_close`, `log_full_path`, `log_username`,
   `log_deleted_files_dirs`, `log_extended_error_information`), and where to write:
   `enable_vast_db_audit` (queryable table) and/or `enable_json_audit` + `audit_dir_name`,
   `read_access_users`, `read_access_users_groups`, `max_retention_period` + `max_retention_timeunit`,
   `max_audit_dir_size` *(all seen on 5.5.3)*.
3. Per-view extra auditing: the view policy's `protocols` and `protocols_audit` (only adds to the global baseline).
4. Read records: `vastauditlog/query_data`, `vastauditlog/columns` (Database realm), or the JSON
   files via a view on the audit directory.

**Impact:** read auditing on busy views produces a lot of records and some CPU cost; start
with create/delete + modify, add `read_data` only where required; set retention and a size limit.
VMS-side audit: RBAC changes and login attempts are recorded as events (KB "Provisioning VMS
Access"); forward them to syslog with `/eventdefinitionconfigs/<id>/` (`syslog_host`,
`syslog_port`, `syslog_protocol`, `syslog_vms_audit`, 5.5 API).

### 9. VMS certificate, mTLS, encryption

See `references/identity-access/security-settings.md`: installing a CA-signed VMS certificate
(`/vms/<id>/set_certificate/`), requiring client certificates (`set_client_certificate`: every UI
and API client then needs a certificate, so a mistake locks everyone out), minimum TLS version,
encryption at rest and EKM, encryption-group key rotation/deactivation/revocation
(**revocation destroys keys: data is unrecoverable**).

## Security-sensitive operations (warn the user before each)

| Operation | Impact |
|---|---|
| Disable/delete an S3 key, `iamroles/<id>/revoke_access_keys` | clients using it fail at once |
| Change tenant providers, `posix_primary_provider`, attribute mapping, local user UID | file ownership/permission resolution changes for all clients; S3 keys of affected external users can be lost (pitfall 3) |
| AD leave/rejoin, NTLM change, delete AD/LDAP config | SMB and directory lookups stop for the tenant until rejoined |
| Edit/delete a role, change `ldap_groups`, `super_admin_groups`, `tenant_admins_group_name` | admins gain or lose rights immediately |
| `os_ssh_login` on a role | shell access to cluster nodes |
| Detach/disable an identity policy, `s3_superuser`, bucket policy changes | S3 access granted or broken immediately |
| VMS client certificate (mTLS), minimum TLS 1.3, VMS certificate replace | can lock out UI/API clients and tools |
| Enable encryption on a running cluster, deactivate/revoke encryption group, rotate master key | full rewrite; data inaccessible; revoke is permanent |

## Pitfalls (symptom or error -> cause -> fix)

1. `GET /users/query/` -> `404 {"detail": "User not found."}` *(seen on 5.5.3)* -> the user is not
   in any provider of that tenant, wrong `tenant_id`, or `context` limited to another provider ->
   check `get tenants/<t>` providers and `users/available_contexts`; retry with `context=aggregated`.
2. `GET /s3keys/` as a VMS manager -> `400 "User with identifier='login_name', value='<you>', tenant_guid=... not found"`
   *(seen on 5.5.3)* -> `/s3keys/` is self-service for provider users, not managers -> as an
   admin use `/users/<id>/access_keys/` or `/users/non_local_keys/`.
3. S3 `403 InvalidAccessKeyId: The AWS access key Id you provided does not exist in our records`
   after it used to work -> the user's UID was changed/added in AD; VAST merged user records and
   dropped the old one holding the keys (KB article of that title) -> generate a new key.
   The same error right away -> wrong tenant (keys are per tenant) or the key was deleted.
4. S3 `AccessDenied` with a valid key -> no identity policy/bucket policy allows the action, the
   policy is in another tenant or disabled (replicated policies arrive disabled), or a `Deny`
   wins -> `get users/query ...` shows effective `s3_policies`; check the bucket's policy and owner.
5. Bucket policy rejected or ignored -> the view is not S3 Native flavor, resource does not name
   the bucket, `CreateBucket` in a bucket policy, or > 20 KB (KB "Managing Bucket Policies").
6. `POST /s3policies/` 400 on `policy` -> sent a JSON object instead of a string, or longer than
   the max length (6145 on 5.5) -> `json.dumps` the document; split large policies.
7. Attaching a policy removed the others -> `s3_policies_ids` replaces the list -> read, merge, write.
8. VMS call 403 / missing menus for a new admin -> role lacks the realm permission, or the role
   is cluster-scoped while the manager is a tenant admin (roles shown only per user type, KB) ->
   `get roles/<id>` and compare with `get permissions`.
9. Directory user cannot log in to VMS -> the group is not on any role's `ldap_groups`
   (`<group>@<domain>` form), the provider is not the VMS auth provider (`is_vms_auth_provider`),
   or, for a tenant, the group is not the tenant's `tenant_admins_group_name`.
10. Local and AD user disagree on UID -> the local entry overrides (KB) -> remove/fix the local
    entry if AD should be authoritative.
11. AD create fails on `machine_account_name` -> longer than 15 characters (5.5 API maxLength).
12. Cannot delete a VAST provider -> it is still attached to a tenant or has users/groups (KB).
13. Tenant admin cannot add an identity provider or see VIP pools -> by design (KB "Cluster and
    Tenant Admins"): a cluster admin does it.
14. Lost secret key -> cannot be shown again (KB) -> create a new pair, delete the old one.
15. `POST /users/` -> `400 {"local_provider_id": ["This field is required."]}` *(seen on 5.4.6, `/api/latest`)*
    -> the versioned API needs the provider, which an unversioned `/api/` call did not ->
    read it from `get tenants/<t> fields=local_provider_id` and send it (workflow 1, step 4).

## Related areas

`SKILL.md` (logins, API tokens: create/revoke/limit, tenant header), `references/tenants-network.md`
(tenants, VIP pools, DNS), `references/views-protocols.md` (views, view policies, security flavors,
SMB/NFS/S3 settings), `references/database.md` (row/column security, audit table queries),
`references/dataengine.md` (application users, DataEngine keys), `references/monitoring.md` (events, syslog).

Verified: VAST 5.5.3 (spec read for every endpoint/field named; live read-only GETs of tenants,
providers, users, users/query, managers, roles, permissions, realms/objects, auditing, vms,
encryptiongroups; KB 5.5 pages cited). Not run end to end: no object was created or changed.
Write bodies marked as coming from public tools are unverified against the 5.5.3 Swagger.
