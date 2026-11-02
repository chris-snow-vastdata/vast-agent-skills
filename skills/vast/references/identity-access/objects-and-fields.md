# Identity objects: endpoints and fields (checked on VAST 5.5.3)

Every path and field here was read from the 5.5.3 cluster spec (`vast_api.py spec show|model`),
unless marked *(public tools)* = taken from the Terraform provider `vast-data/vastdata`, the
Ansible collection `vastdata.vms` or `vast-csi`, because the Swagger body is generic for that
call. On another release, re-check with:

```bash
vast_api.py spec paths 'users|groups|localproviders|activedirectory|ldaps|nis|s3policies|s3keys|managers|roles|realms|permissions|iamroles|oidcs'
vast_api.py spec show <path> <method>
vast_api.py spec model <Name>       # e.g. Tenant, User, Ldap, ActiveDirectory, Manager, Role
```

## Tenant fields that decide identity

| Field | Meaning |
|---|---|
| `local_provider_id` | the tenant's VAST provider (one per tenant) |
| `ad_provider_id`, `ldap_provider_id`, `nis_provider_id`, `krb_provider_id`, `oidc_provider_id` | external providers enabled for the tenant |
| `posix_primary_provider` | `NONE|LDAP|NIS|AD|LOCAL|KEYSTONE`: wins POSIX attribute conflicts between two external providers |
| `login_name_primary_provider` | same enum: provider used for login-name lookups |
| `tenant_admins_group_name` | directory group whose members may log in as tenant admins (still need a role) |
| `application_users_group_name` | directory group whose members log in as application users |
| `allow_disabled_users`, `allow_locked_users` | allow IO from AD accounts that are disabled / locked out |
| `encryption_group` (+ `_id`, `_state`) | EKM encryption group; set at tenant creation, cannot be changed after (KB) |
| `mtls_identifier` | tenant identifier used with mTLS (NFS/Kafka mTLS) |

## VAST (local) providers, users, groups

| Object | Path | Key fields |
|---|---|---|
| VAST provider | `/localproviders/` | `name` (required, max 64), `description`, `managed_by` array of `TENANT_ADMIN|SUPER_ADMIN|APP_USER` (which manager types may manage its users). A cluster has a provider named `default` (id 1, seen). |
| Local user | `/users/` | `name`, `uid` (1..2147483647), `local_provider_id` (default 1), `leading_gid`, `gids`, `groups`, `password` (VMS login for app users), `is_temporary_password`, `allow_create_bucket`, `allow_delete_bucket`, `s3_superuser`, `s3_policies_ids`; read-only `sid`, `vid`, `access_keys` |
| Per-tenant user data | `/users/{id}/tenant_data/` GET/PATCH | tenant-specific attributes (bucket flags, policies, keys); usable by tenant admins even when they do not manage the user's provider (spec description) |
| Copy users | `/users/copy/` POST | copy users from one VAST provider to another (CLI `user copy`) |
| Local group | `/groups/` | `name`, `gid` (both required), `local_provider_id`, `s3_policies_ids`; read-only `sid` |
| Any user (local or external) | `/users/query/` GET/PATCH | GET params seen working on 5.5.3: `username`, `tenant_id`, `context` (`aggregated` default, `local`, `udb`, or a provider type); also `uid`, `sid`, `login_name` *(public tools)*. Returns merged view incl. `uid`, `sid`, `vid`, `groups`, `access_keys`, `s3_policies`, `s3_remote_policies`, `origins`. PATCH sets `s3_policies_ids`, `allow_create_bucket`, `allow_delete_bucket`, `s3_superuser` for external users *(public tools)* |
| Any group | `/groups/query/` GET/PATCH | same pattern for groups |
| Which contexts | `/users/available_contexts/` | e.g. `["Local"]` with no external provider (seen) |
| Refresh cached users | `/users/refresh/` PATCH | re-query providers |

Rules (KB "VAST Providers"): local attributes override external POSIX attributes; groups with
the same name across providers are merged by name and the local group's GID/SID wins; a
provider can be deleted only when attached to no tenant and holding no users or groups.

## S3 access keys

| Call | Body | Source |
|---|---|---|
| `POST /users/{id}/access_keys/` | `{"tenant_id": T}`; optional `access_key` + `secret_key` (both or neither; UI limits 21 / 41 chars), optional `pgp_public_key` (then `encrypted_secret_key` is returned) | `{"tenant_id": T}` worked on 5.5.3; the rest *(public tools)*, KB |
| `PATCH /users/{id}/access_keys/` | `{"access_key": AK, "enabled": true|false, "tenant_id": T}` | *(public tools)*, KB CLI `user modify-key` |
| `DELETE /users/{id}/access_keys/` | `{"access_key": AK, "tenant_id": T}` | *(public tools)* |
| `POST /users/non_local_keys/` | `{"username"|"uid"|"sid"|"login_name": ..., "tenant_id": T, "context": "AGGREGATED"}` | *(public tools)* |
| `PATCH` / `DELETE /users/non_local_keys/` | identifiers + `access_key` (+ `enabled` for PATCH) | *(public tools)* |
| `GET` / `POST /s3keys/`, `DELETE /s3keys/delete/` | self-service by the logged-in provider user; delete body `{"access_key": AK}` | 5.5 spec paths; KB shows `DELETE /s3keys/` |
| `GET /locals3keys/` | list local S3 keys (Security realm) | 5.5 spec path |

There is no GET on `/users/{id}/access_keys/`: list keys from `GET /users/{id}` or
`GET /users/query/` (`access_keys`). The KB CLI page `user generate-key` says `--tenant-id`
is used only to look the user up and the pair "enables access to the default tenant only",
while the S3 permissions page says a pair gives access to a single tenant and the public tools
pass `tenant_id` to scope the key: after generating, test the key against the intended tenant.

## External providers

| Object | Path | Notable fields (5.5 API) |
|---|---|---|
| Active Directory | `/activedirectory/` | `domain_name`, `machine_account_name` (max 15), `organizational_unit`, `enabled` (join/leave), `ldap`/`ldap_id` (its LDAP side), `ntlm_enabled`, `smb_allowed`, `preferred_dc_list`, `scheduled_ma_pwd_change_enabled`, `ma_pwd_change_frequency`, `state`, `tenant_id`. Join credentials `admin_username`/`admin_passwd` *(public tools)*. Actions: `{id}/refresh/` PATCH, `{id}/change_machine_account_password/` POST, `{id}/is_operation_healthy/` POST, `{id}/domains/`, `{id}/dcs/`, `{id}/gcs/`, `{id}/current_gc/` GET |
| LDAP | `/ldaps/` | `urls`, `port`, `method` (`anonymous|simple|sasl|krbv4|krbv41|krbv42`), `binddn`, `bindpw`, `searchbase`, `group_searchbase`, `netgroup_searchbase`, `use_tls`, `use_ldaps`, `tls_certificate`, `use_auto_discovery`, `use_multi_forest`, mapping (`uid`, `uid_number`, `gid_number`, `uid_member`, `posix_account`, `posix_group`, `match_user`, `username_property_name`, `user_login_name`, `group_login_name`, `mail_property_name`), `query_groups_mode`, `posix_attributes_source` (`JOINED_DOMAIN|ALL_DOMAINS|SPECIFIC_DOMAINS|GC`), `domains_with_posix_attributes`, `super_admin_groups`, `is_vms_auth_provider`, `monitor_action` (`PING|BIND`), `advanced_filter`, `reverse_lookup`, `{id}/set_posix_primary/` PATCH |
| NIS | `/nis/` | `domain_name`, `servers`, `hosts`, `ips`, `{id}/set_posix_primary/`, `/nis/refresh/` |
| Kerberos | `/kerberos/`, `/kerberos/{id}/keytab/` | see KB "Kerberos" for the release |
| OIDC | `/oidcs/` | `name`, `discovery_url` (required), `user_jwt_attribute`, `verify_peer`, `certificate`; `{id}/refresh_keys/`. Used for S3 STS with temporary keys (KB) |
| SAML (VMS login) | `/vms/{id}/saml_config/` | SSO for VMS managers; KB for the release |
| IAM roles (STS) | `/iamroles/` | `name`, `trust_policy`, `s3_policies`, `max_session_duration` (default 129600 s), `groups_claim_name`, `tenant_id`; `{id}/credentials/` GET, `{id}/revoke_access_keys/` PATCH |

AD attribute mapping defaults for AD (KB "Active Directory"): UID `sAMAccountName`, UID number
`uidNumber`, GID number `gidNumber`, member `member`, POSIX account `user`, POSIX group `group`,
match user `sAMAccountName`. Query group mode `COMPATIBLE` (default), `RFC2307BIS_ONLY`,
`RFC2307_ONLY`, `NONE` (Terraform docs).

Protocol/provider support (KB "Authorization Providers in VAST Cluster", per tenant): SMB needs
AD; NFSv3, NFSv4 and S3 work with any combination incl. the VAST provider; NFSv4 uses Kerberos
when a Kerberos provider is attached; OIDC gives S3 temporary keys.

## VMS management

| Object | Path | Key fields |
|---|---|---|
| Manager | `/managers/` | `username` (required, max 150, letters/digits/`@.+-_`), `password` (required on create), `user_type` (`TENANT_USER|TENANT_ADMIN|SUPER_ADMIN`), `tenant_id`, `roles`, `first_name`, `last_name`, `is_active` (deactivate instead of deleting), `password_expiration_disabled`, `is_temporary_password`, `failed_logins`; `{id}/unlock/` PATCH, `/managers/password/` PATCH (own password), `/managers/authorized_status/` GET |
| Role | `/roles/` | `name` (required, max 80), `tenant_id` (tenant-admin role), `tenants`, `ldap_groups`, `os_ssh_login`, `permissions` (read: codename list), `is_default`, `is_admin`, `managers`. Write helpers `permissions_list`, `realm`, `permissions` (types), `tenant_ids`, `object_type` + `object_id` *(public tools)* |
| Permission | `/permissions/` GET | `codename` `<create|view|edit|delete>_<realm>`, `realm`, `permission_type`, `resources` |
| Realm (custom) | `/realms/` | `name` (max 128), `object_types`, `tenant_id`; `{id}/assign/`, `{id}/unassign/`; built-in realms and their object types: `GET /realms/objects/` |
| API token | `/apitokens/` | see `SKILL.md`; per-user limit `max_api_tokens_per_user` on `/vms/` (5 seen), set via `/vms/{id}/set_max_api_tokens_per_user/` |
| VMS login settings | `/vms/` | `min_pwd_length`, `access_token_lifetime` / `refresh_token_lifetime` (JWT; `01:00:00` / `1 00:00:00` seen), `auto_logout_timeout`, `gui_idle_timeout`, `enable_idle_timeout`, `login_banner`, `min_tls_version` |
