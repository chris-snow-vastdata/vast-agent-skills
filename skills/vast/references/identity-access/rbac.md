# VMS RBAC: managers, roles, permissions, realms

KB (5.5): "Provisioning VMS Access" https://kb.vastdata.com/documentation/docs/provisioning-vms-access-55-1.md,
"Managing Managers" https://kb.vastdata.com/documentation/docs/managing-managers-55.md,
"Managing Administrative Roles" https://kb.vastdata.com/documentation/docs/managing-administrative-roles-55.md,
"Managing User-Defined Permission Realms" https://kb.vastdata.com/documentation/docs/managing-user-defined-permission-realms-55.md,
"Cluster and Tenant Admins" https://kb.vastdata.com/docs/3-cluster-and-tenant-admins.md

## Model

- A **permission** = action (`create`, `view`, `edit`, `delete`) on a **realm** (a category of
  object types). Codename `<action>_<realm>`, e.g. `edit_logical` (`GET /permissions/`).
- A **role** = a set of permissions, optionally tied to tenant(s) and directory groups.
- A **manager** = a VMS login with a `user_type` and roles; inherits all its roles' permissions.
  Permissions can also be assigned to a manager directly (CLI `manager assign`).
- **Directory groups on a role** (`ldap_groups`, entered as `group@domain`): members log into VMS
  with their AD/LDAP password and get the role's rights. Needs connectivity to the provider at
  login. For cluster admins, the provider's `super_admin_groups` lets members log in (with a
  read-only role by default, KB); for tenant admins, the tenant's `tenant_admins_group_name`.

## Built-in realms (5.5.3: `GET /realms/objects/` and `/permissions/`)

| Realm | Covers (summary from KB) |
|---|---|
| `logical` | views, view policies, quotas, VIPs/VIP pools, DNS, snapshots, protection/replication, QoS, lifecycle rules, volumes/block hosts, Kafka brokers, compute clusters |
| `security` | users, groups, VAST/AD/LDAP/NIS/Kerberos/OIDC providers, managers, roles, realms, permissions, tenants, identity policies, S3 keys, IAM roles, encryption groups/encrypted paths, indestructibility, TLS certificates; API tokens (KB) |
| `database` | VAST DB schemas/tables/columns, Catalog, audit-log tables, Event Broker topics |
| `events` | alarms, events, event definitions, webhooks |
| `monitoring` | analytics, capacity, data-flow, monitors |
| `hardware` | the cluster object and all hardware |
| `settings` | VMS settings |
| `support` | call home, support bundles, licenses, challenge tokens |
| `applications` | CNode groups, managed applications (DataEngine) |

36 permissions on 5.5.3 = 4 actions x 9 realms. Some realms do not apply to tenant admins (KB).

## Default roles (seen on 5.5.3)

`administrators` (all, `is_admin`), `read_only` (view on most realms), `configuration` (logical
CRUD + views), `csi` (logical CRUD, for the CSI driver), `debug_metrics`. KB: do not modify
default roles; copy and edit the copy. The default manager cannot be deleted and its
permissions cannot be reduced.

## Least-privilege recipes (adapt; verify codenames with `get permissions`)

| Persona | Permissions |
|---|---|
| Storage operator for one tenant | `view_logical, create_logical, edit_logical, delete_logical, view_events, view_monitoring` with `tenant_id` |
| Tenant identity admin (users, keys, policies) | `view_security, create_security, edit_security` (+ `delete_security` if they rotate keys) with `tenant_id` |
| Read-only auditor | `view_*` on the needed realms + `view_database` for audit tables |
| Automation for CSI | copy of `csi` |
| Monitoring/exporter | `view_monitoring, view_events` (+ `view_hardware` for cluster-level), API token |
| DataEngine operator | `*_applications` plus what `references/dataengine.md` lists for the release |

`security` is broad (it includes managers, roles and tenants): granting `edit_security` lets a
user grant themselves more rights within their scope. Narrow it with a **custom realm**:

```json
POST /realms/  {"name": "<tenant>-s3-identity", "object_types": ["User", "Group", "S3Policy", "S3Key"], "tenant_id": <t>}
```

then give a role the permission on that realm (UI: role -> permissions on the realm; CLI
`role assign --id <role> --realm <realm name> --permissions edit`; Terraform
`vastdata_administrator_role` with `realm` + `permissions`, or `permissions_list`). Object-level
grants: CLI `role assign --object-type view --object-id <id>` (KB "role assign").

## Creating via the API (5.5)

```bash
# role tied to a tenant: dry run, then --yes after the user agrees
vast_api.py call POST /roles/ --data '{"name":"<tenant>-ops","tenant_id":<t>,"permissions_list":["view_logical","edit_logical"]}'
vast_api.py get roles name=<tenant>-ops fields=id,name,tenant_id,permissions

# tenant admin manager
vast_api.py call POST /managers/ --data '{"username":"<name>","password":"<temp>","is_temporary_password":true,"user_type":"TENANT_ADMIN","tenant_id":<t>,"roles":[<role id>]}'
vast_api.py get managers username=<name> fields=id,username,user_type,tenant_id,roles
```

`permissions_list` and `roles` as a list of ids are what the Terraform provider sends, and both
worked through the REST API on 5.5.3; the 5.5.3
Swagger lists `permissions` (string) and `roles` (array of objects). If the dry-run shape is
refused, check `spec show /roles/ post` and the KB "API Reference" for roles on that release.

Operations: `PATCH /managers/{id}/unlock/` (locked after failed logins or expiry),
`{"is_active": false}` to suspend instead of deleting. Lockout thresholds, password length and
expiry are VMS settings (KB "VMS Settings and Preferences").

## Auditing of RBAC

Changes to RBAC configuration and all login attempts (time, user, result) are recorded as VMS
events (KB "Provisioning VMS Access"); see `references/monitoring.md` and syslog forwarding in
`references/security-settings.md`.
