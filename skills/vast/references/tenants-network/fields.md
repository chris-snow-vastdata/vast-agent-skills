# Field reference: tenants, VIP pools, VIPs, DNS, QoS

All names and enums below were read from the VAST **5.5.3** VMS spec *(5.5 API)* unless
tagged otherwise. Meanings come from the KB 5.5 pages ("Creating Tenants", "tenant create",
"Managing Virtual IP Pools", "vippool create", "Configuring the VAST Cluster DNS Service")
and the public Terraform provider docs. Re-check on any other release:

```bash
vast_api.py spec model Tenant      # or: spec show /tenants/ post
vast_api.py spec model VIPPool
vast_api.py spec model DNS         # or: spec show /dns/ post
vast_api.py spec show /qospolicies/ post
```

The generated spec lists read-only fields in request bodies too; those are marked *ro* here.

## Tenant (`/tenants/`)

| Field | Type / values | Meaning |
|---|---|---|
| `name` | string, required | Letters, digits, `-`, `.`; no `_` (KB) |
| `domain_name` | string | Used in the tenant's VMS login URL `https://<VMS>/#/login/<domain>`; default = name. Not DNS. |
| `client_ip_ranges` | list of `[start, end]` | Client source IPs served by the tenant; must not overlap other tenants. Required for tenant routing on shared VIP pools. |
| `access_ip_ranges` | list of strings | Source IPs allowed for tenant-admin VMS logins (single IP, `a - b` range, or CIDR per Terraform docs) |
| `vippool_names`, `vippools` | *ro* | Pools bound to the tenant (`[{id, name}]`) |
| `dir` | *ro* | The tenant's root path in the Element Store |
| `allowed_delegations` | `DISABLED\|READ\|WRITE\|READ_WRITE\|NONE` | Tenant NFSv4 delegation default; `NONE` = per view; `DISABLED` = none anywhere in the tenant |
| `grant_unrequested_delegations_by_default` | bool | Grant allowed delegations even if not requested (default true per KB) |
| `is_nfsv42_supported` | bool | Enable NFSv4.2 |
| `trash_gid` | int | GID allowed to use the NFSv3 trash folder |
| `max_views` | int 0-153600 | 0 = system limit |
| `encryption_group` | string (CRN, ≤128 per KB) | EKM encryption group; set at creation only |
| `encryption_group_id`, `encryption_group_state`, `encryption_crn` | *ro* | Encryption status |
| `mtls_identifier` | string ≤100 | Tenant ID for NFS/Event Broker mTLS; unique per cluster |
| `ad_provider_id`, `ldap_provider_id`, `nis_provider_id`, `local_provider_id`, `krb_provider_id`, `oidc_provider_id` | int | Identity providers attached to the tenant (see `references/identity-access.md`) |
| `posix_primary_provider`, `login_name_primary_provider` | `NONE\|LDAP\|NIS\|AD\|LOCAL\|KEYSTONE` | Which provider wins on conflicts |
| `tenant_admins_group_name` | string | Provider group whose members log in as tenant admins |
| `application_users_group_name` | string | Provider group of application users (e.g. DataEngine access) |
| `smb_encryption_state` | `OFF\|AVAILABLE\|DESIRED\|REQUIRED` (default OFF) | SMB in-flight encryption |
| `require_smb_signing`, `use_smb_native` | bool | SMB signing; Kerberos/NTLM-native authorization |
| `default_others_share_level_perm` | `READ\|CHANGE\|FULL` | Default "Everyone" share-level permission |
| `use_smb_privileged_user`, `smb_privileged_user_name`, `use_smb_privileged_group`, `smb_privileged_group_sid`, `smb_privileged_group_full_access`, `smb_administrators_group_name` | | SMB backup/restore privileged identities |
| `allow_disabled_users`, `allow_locked_users` | bool | Allow IO by AD-disabled / locked-out users |
| `preferred_owning_group` | `PROTOCOL_BASED\|POSIX_GID` | Owning group on SMB / mixed-last-wins views |
| `capacity_rules` | object: `soft_limit`, `hard_limit`, `soft_limit_inodes`, `hard_limit_inodes`, `grace_period`, `notify_soft_limit`, `notify_hard_limit`, `enable_alarms` | Tenant capacity limits |
| `qos` | object `{static_limits: {...}}` | Tenant performance limits; keys per KB `tenant create`: `max_reads_bw_mbps`, `max_writes_bw_mbps`, `max_reads_iops`, `max_writes_iops`, `burst_reads_bw_mb`, `burst_reads_iops`, `burst_reads_loan_mb`, `burst_reads_loan_iops`, `burst_writes_bw_mb`, `burst_writes_iops`, `burst_writes_loan_mb`, `burst_writes_loan_iops` (0 = unlimited) |
| `data_engine_enabled` | *ro* | DataEngine enabled on the tenant (enable via the DataEngine flow: `references/dataengine.md`) |
| `status` | `ENABLED\|DISABLED\|DELETED` | |
| `sync` | `CREATING\|MODIFYING\|DELETING\|SYNCING\|SYNCED\|DONT_SYNC\|OUT_OF_SYNC` *ro* | Wait for `SYNCED` |

Tenant sub-endpoints *(5.5 API)*:

| Path | Method | Use |
|---|---|---|
| `/tenants/{id}/vippool_ip_ranges/` | GET | VIP ranges usable by the tenant |
| `/tenants/{id}/views_count/` | GET | `current_views_count`, `max_views` |
| `/tenants/{id}/client_ip_ranges/` | PATCH | Change client IP ranges (body not described in the spec; check `https://<VMS>/docs/`) |
| `/tenants/{id}/nfs4_delegs/` | GET | Granted NFSv4 delegations |
| `/tenants/{id}/nfs4_deleg/` | DELETE | Revoke a delegation (Terraform sends `file_path`) |
| `/tenants/{id}/same_encryption_group_tenants/` | GET | Tenants sharing the encryption key |
| `/tenants/{id}/revoke_encryption_group/`, `reinstate_encryption_group/`, `deactivate_encryption_group/`, `rotate_encryption_group_key/` | POST | EKM key control: **disruptive** |
| `/tenants/{id}/client_metrics/` | GET, PATCH | Per-tenant client metrics settings (`references/monitoring.md`) |
| `/tenants/metric_labels/`, `/tenants/{tenant_pk}/metric_label_values/` | | Metric labels (`references/monitoring.md`) |
| `/tenants/top_tenants/`, `/prometheusmetrics/tenants` | GET | Usage/metrics |

## VIP pool (`/vippools/`)

| Field | Type / values | Meaning |
|---|---|---|
| `name` | string | |
| `role` | string ≤64 (no enum in the spec) | KB 5.5 CLI: `PROTOCOLS` (client data access, all protocols), `REPLICATION` (async replication). Catalog/query-engine roles exist and are named differently across releases: check the KB `vippool create` page for the release |
| `ip_ranges` | list of `[start, end]` | The VIPs; IPv4 or IPv6. `start_ip`/`end_ip` are legacy (Terraform docs: "use ip_ranges") |
| `subnet_cidr`, `subnet_cidr_ipv6` | int | Prefix length, e.g. 24 (not a mask, not `a.b.c.d/24`) |
| `gw_ip`, `gw_ipv6` | string | Gateway when clients are on other subnets |
| `vlan` | int | VLAN tag; 0 = untagged (KB: 0-4096) |
| `tenant_id` | int, spec default 1 | Tenant served exclusively. CLI `--serve-all-tenants` detaches the tenant; check how your release expresses "all tenants" in the API (dry-run a PATCH and read back `tenant_id`) |
| `tenant_name` | *ro* | |
| `cnode_ids` | list of int | Dedicated CNode group; empty = all active CNodes |
| `cnodes`, `active_cnode_ids`, `active_interfaces` | *ro* | Where VIPs currently run |
| `port_membership` | `ALL\|RIGHT\|LEFT` | Which CNode ports carry the pool |
| `domain_name` | string ≤256 | Short name; FQDN = `domain_name` + `.` + DNS `domain_suffix` |
| `enabled` | bool | |
| `vms_preferred` | bool | CNodes of this pool preferred for VMS failover |
| `enable_weighted_balancing` | bool | More VIPs on newer CNode generations |
| `enable_l3`, `bgp_config_id` (`bgp_config_name`, `bgp_config_guid` *ro*), `vast_asn`, `peer_asn` | | L3/BGP; `bgp_config_id` required with `enable_l3` (KB) |
| `client_monitoring_ips` | list of `[start, end]` | External IPs for pool connectivity monitoring (Terraform docs) |
| `kafka_view_id` | *ro* | The Event Broker view using this pool, if any *(seen on 5.5.3)* |
| `vip_allocation` | *ro* | e.g. `CUSTOMER_PROVIDED` *(seen on 5.5.3)*; cloud pools come from `/vippools/allocate/` |
| `managed_application_id` | | Pools used by managed applications |
| `sync` | *ro* | Wait for `SYNCED` |

Related: `POST /vippools/allocate/` and `PATCH /vippools/{id}/reallocate/` (cloud IP
allocation; Terraform uses them when `ips_count` is set). `GET /vips/` lists each VIP:
`ip`, `vippool`, `vippool_id`, `cnode`, `tenant_id`, `tenant_name`. `GET /monitoredvippools/`.
`/bgpconfigs/` holds BGP configurations. `/vipmappings/` exists on 5.5 (fields `vippool_id`,
`ip_ranges`, `naming_scheme` `NONE|VIPPOOL_DOMAIN_NAME|USER_PROVIDED_DOMAIN_NAME`) but no 5.5 KB
page describes it: don't use it without docs.

Views and policies that reference pools *(5.5 API)*: `ViewPolicy.permission_per_vip_pool`
(map pool id → `RW`|`RO`; empty = all pools allowed), `View.kafka_vip_pools` (list with the one
Event Broker pool).

## VAST DNS service (`/dns/`)

| Field | Type / values | Meaning |
|---|---|---|
| `name` | string ≤64 | |
| `vip`, `vip_subnet_cidr`, `vip_gateway`, `vip_vlan` (0-4094 in spec; KB says 1-4094) | | The DNS service's own IP |
| `vip_ipv6`, `vip_ipv6_subnet_cidr`, `vip_ipv6_gateway` | | IPv6 equivalent |
| `domain_suffix` | string ≤64 | Delegated suffix appended to pools' `domain_name` |
| `net_type` | `NORTH_PORT\|SOUTH_PORT\|EXTERNAL_PORT\|BOND\|COUNT` | Interface that listens (KB: EXTERNAL_PORT default = onboard management; NORTH_PORT = client-facing; SOUTH_PORT = internal) |
| `port`, `ttl` | int | DNS port (53 per KB), TTL of answers |
| `cnode_ids` | list | CNodes that serve DNS (empty = all) |
| `enabled` | bool | |
| `enable_l3`, `bgp_config_id` | | L3 access to DNS CNodes |
| `invalid_name_response`, `invalid_type_response` | `NXDOMAIN\|REFUSED\|SERVFAIL\|NOERROR` | Answers for unknown names / record types |

Only one DNS service per cluster (KB). `POST /dns/allocate/` for cloud IP allocation.

## QoS policy (`/qospolicies/`)

| Field | Values |
|---|---|
| `name` | required |
| `policy_type` | `VIEW\|USER\|VOLUME` |
| `mode` | `STATIC\|USED_CAPACITY\|PROVISIONED_CAPACITY` |
| `limit_by` | `BW\|IOPS\|BW_IOPS` |
| `static_limits`, `static_total_limits`, `capacity_limits`, `capacity_total_limits`, `use_total_limits` | objects/bool; key names per KB "Creating a QoS Policy" for the release |
| `tenant_id` | the tenant the policy belongs to |
| `attached_users` | users/IAM roles for USER policies |
| `s3_connections_limit`, `s3_conns_limit_per_env_pct` | S3 connection limits |
| `is_gold` | priority (KB "Prioritizing Workloads") |

## Managers and roles (tenant admins)

| Object | Fields *(5.5 API)* |
|---|---|
| `/managers/` | `username` (required), `password` (required), `user_type` `TENANT_USER\|TENANT_ADMIN\|SUPER_ADMIN`, `tenant_id`, `roles` (list of `{id}` / `PartialRole`), `first_name`, `last_name`, `is_temporary_password`, `password_expiration_disabled`, `is_active` |
| `/roles/` | `name` (required), `tenant_id`, `tenants`, `permissions` (typed string in the spec; Terraform/Ansible send `permissions_list` and `tenant_ids`), `ldap_groups`, `os_ssh_login` |
| `/realms/` | custom realms (sets of object types) |

Permission names are `<action>_<realm>` with actions create/view/edit/delete and realms such as
logical, security, database, events, monitoring, hardware, settings, applications (seen on the
built-in `administrators` role, 5.5.3).
