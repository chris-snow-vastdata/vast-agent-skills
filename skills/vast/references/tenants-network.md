# VAST tenants and network access

Builds on `SKILL.md` (connecting, the helper `scripts/vast_api.py`,
reading the cluster's own spec, the KB, safe changes). Read it first; this file does not repeat it.
All commands below are that helper, run as `vast_api.py ...`.

## Mental model

```
Cluster
 ├─ Tenant (the "default" tenant always exists and can't be deleted)
 │   ├─ own Element Store path (isolated namespace); views, view policies, quotas, users live in a tenant
 │   ├─ client IP ranges (optional)   ── which client source IPs belong to this tenant
 │   ├─ providers (AD/LDAP/NIS/local) ── who its users are  (see vast-identity-access)
 │   ├─ defaults inherited by its views: NFSv4 delegations, SMB signing/encryption,
 │   │   default share-level perm, NFSv4.2, trash GID, max views
 │   ├─ encryption group (EKM only; fixed at creation)
 │   └─ tenant limits: capacity rules + static performance limits (tenant-wide QoS)
 ├─ VIP pool ── a set of virtual IPs spread over CNodes (all, or a CNode group)
 │   ├─ role: client protocols, replication, catalog/query (values differ per release)
 │   ├─ tenant: one tenant only, or "serves all tenants"
 │   ├─ subnet CIDR, gateway, VLAN tag, port membership (ALL/LEFT/RIGHT), L3/BGP
 │   └─ domain name ─┐
 └─ VAST DNS service (one per cluster): a DNS VIP + a domain suffix
                     └─ <pool domain name>.<suffix> resolves to one VIP of that pool per query
```

How the cluster decides which tenant a client is in (KB "Overview of Tenants", 5.5):

- VIP belongs to a **tenant-bound pool** → that tenant. If the tenant has client IP ranges,
  the client source IP must be inside them, or it is rejected.
- VIP belongs to a pool that **serves all tenants** → the tenant whose **client IP ranges**
  contain the source IP. No match → rejected. (So with shared pools, every non-default
  tenant needs client IP ranges, and ranges must not overlap between tenants.)
- NFS over mTLS (cluster-wide mode) → the tenant whose mTLS identifier matches the cert.

Then access to a view needs **both**: the view is in that tenant, and the view policy's
host rules (and optional VIP-pool list) allow the client. Exports, shares and buckets of
other tenants are never listed.

What depends on what (create in this order):
1. Tenant → 2. VIP pool for it (and DNS name) → 3. view policy in the tenant (optionally
limited to its pools) → 4. views / S3 buckets / databases in the tenant. VAST Event Broker
(Kafka) views need **their own dedicated PROTOCOLS VIP pool** in the same tenant (KB
"Publishing Events to VAST Event Broker", 5.5). DataEngine is enabled per tenant and needs a
compute cluster attached to that tenant (KB "Enabling DataEngine on a VAST Cluster Tenant").
See `references/views-protocols.md`, `references/database.md`, `references/event-broker.md`, `references/dataengine.md`.

## Check this release first

```bash
vast_api.py version                                   # e.g. 5.5.x -> use --version 5.5
vast_api.py kb search 'Tenants|Virtual IP Pools|DNS Service|VLAN' --version 5.5
vast_api.py spec paths 'tenant|vippool|^/vips|/dns|qospolic|bgpconfig'
vast_api.py spec show /tenants/ post                  # tenant fields + enums
vast_api.py spec show /vippools/ post                 # VIP pool fields + enums
vast_api.py spec show /dns/ post
```

The spec is generated: request bodies list read-only fields too (`id`, `guid`, `sync`,
`vippool_names`, ...). Send only what you mean to set; the KB page and Terraform/CLI docs
tell you which fields are settable. Some enums are **not** in the spec: on 5.5 the VIP pool
`role` is a free string *(5.5 API)*; read the allowed values from the KB `vippool create`
page for the release and from existing pools (`get vippools fields=name,role`).
Field tables: [references/tenants-network/fields.md]()).

## Take stock (read-only, always first)

```bash
vast_api.py get tenants fields=id,name,vippool_names,client_ip_ranges,allowed_delegations,encryption_group,max_views
vast_api.py get vippools fields=id,name,role,tenant_id,tenant_name,ip_ranges,subnet_cidr,gw_ip,vlan,port_membership,cnode_ids,domain_name,enabled
vast_api.py get vips                      # each VIP: ip, vippool, cnode, tenant_name
vast_api.py get dns                       # VAST DNS service (empty list = not configured)
vast_api.py get viewpolicies fields=id,name,tenant_id,permission_per_vip_pool
vast_api.py get managers fields=id,username,user_type,tenant,roles
vast_api.py get tenants/<id>/vippool_ip_ranges     # the VIP ranges this tenant can use
vast_api.py get tenants/<id>/views_count           # current vs max views
vast_api.py get cnodes fields=id,name,state,enabled
```

All of these paths are in the 5.5 spec *(5.5 API)*. List filters vary: `spec show <path> get`
(on 5.5 `/vippools/` and `/vips/` document only paging), so filter client-side by `tenant_id`.

## Workflow 1: onboard an app team as a tenant with its own VIPs and DNS name

KB: "Creating Tenants" https://kb.vastdata.com/documentation/docs/creating-tenants-55.md ·
"Managing Virtual IP Pools" https://kb.vastdata.com/documentation/docs/managing-virtual-ip-pools-55.md ·
"DNS-Based Virtual IP Distribution" https://kb.vastdata.com/documentation/docs/dns-based-virtual-ip-distribution-55.md

Ask the user for: tenant name; the client subnet(s) the team uses; free IPs on the data
network for VIPs (recommend 2+, ideally 4, per CNode serving the pool, a multiple of the
CNode count: KB "Configuring Network Access"); subnet CIDR, gateway (if clients are on other
subnets), VLAN (if tagged); short DNS name; identity provider(s); any limits.

1. **Check for clashes**: tenant name unused; VIP range not inside any existing pool
   (`get vippools`), not in other tenants' client IP ranges, not in use on the network.
2. **Plan and ask once**: show the exact requests, e.g.

   ```bash
   vast_api.py call POST /tenants/ --data '{
     "name": "<team>",
     "client_ip_ranges": [["<client-start-ip>", "<client-end-ip>"]],
     "allowed_delegations": "READ_WRITE"
   }'
   ```
   Tenant names: letters, digits, `-` and `.`; no underscores (KB "Creating Tenants", 5.5).
3. **Create the tenant** (`--yes` after the user agrees), read it back (`get tenants name=<team>`),
   note its `id` and `dir` (the tenant's root path).
4. **Create the VIP pool bound to it**:

   ```bash
   vast_api.py call POST /vippools/ --data '{
     "name": "<team>-protocols", "role": "PROTOCOLS", "tenant_id": <tenant id>,
     "ip_ranges": [["<vip-start>", "<vip-end>"]], "subnet_cidr": 24,
     "gw_ip": "<gateway or omit>", "vlan": <vlan or omit>,
     "port_membership": "ALL", "domain_name": "<team>"
   }'
   ```
   Fields *(5.5 API)*: `ip_ranges` is a list of `[start, end]` pairs; `port_membership` one of
   `ALL|RIGHT|LEFT`; `cnode_ids` limits the pool to a CNode group (omit = all active CNodes);
   `enable_l3` + `bgp_config_id` for L3/BGP (see `/bgpconfigs/`). In cloud deployments,
   `POST /vippools/allocate/` gets IPs from the provider instead (KB `vippool allocate`).
5. **Check it**: `get vippools/<id>` shows `sync` settle to `SYNCED`; `get vips` lists one entry per
   IP with the `cnode` that holds it; `get tenants/<id>` now has the pool in `vippool_names`.
   Ping a VIP from a client in the team's subnet.
6. **DNS name** (optional): if the VAST DNS service exists (`get dns`), the pool's FQDN is
   `<domain_name>.<domain_suffix>`. If not, see Workflow 3. Test: `dig +short <fqdn>` from a client
   returns one VIP per query, rotating.
7. **Hand over**: the team (or its tenant admin, Workflow 2) creates view policies and views in
   the tenant (`references/views-protocols.md`). To pin a view policy to this pool, set its VIP pool
   permissions (on 5.5 `permission_per_vip_pool`, a map of pool id → `RW`/`RO`; KB "Managing
   View Policies"; CLI `--permission-per-vip-pool 1=RW,2=RO`). A policy can only list pools that
   serve its own tenant (KB "Overview of Tenants").
8. **Report** what was created (tenant id, pool id, IPs, FQDN) so it can be torn down.

Optional tenant settings at create or later via `PATCH /tenants/<id>/` (KB "Creating Tenants";
field names in [references/tenants-network/fields.md]())): providers (`ad_provider_id`,
`ldap_provider_id`, `nis_provider_id`, `local_provider_id`), `domain_name` (only changes the
tenant's VMS login URL `https://<VMS>/#/login/<domain>`, not DNS), `max_views`, `trash_gid`,
`is_nfsv42_supported`, `smb_encryption_state`, `require_smb_signing`,
`default_others_share_level_perm`, `mtls_identifier`, `access_ip_ranges` (source IPs allowed
for the tenant admin's VMS login), `capacity_rules`, `qos.static_limits` (tenant-wide limits).

## Workflow 2: delegate a tenant admin

KB: "3. Cluster and Tenant Admins" https://kb.vastdata.com/docs/3-cluster-and-tenant-admins.md ·
"Provisioning VMS Access" https://kb.vastdata.com/documentation/docs/provisioning-vms-access-55-1.md ·
"Managing Managers via VAST Web UI" https://kb.vastdata.com/documentation/docs/managing-managers-via-vast-web-ui-55.md

A tenant admin is a VMS **manager** scoped to one tenant. It can manage views, view policies,
quotas, lifecycle rules, identity policies, the tenant's local provider and S3 keys; it
**cannot** see or change VIP pools, add identity providers, see hardware, or use the VAST CLI
(KB "3. Cluster and Tenant Admins"). So the cluster admin does Workflows 1 and 3.

Two ways, per the KB:

- **Local manager**: `POST /managers/` with `username`, `password`, `user_type: "TENANT_ADMIN"`,
  `tenant_id`, and `roles` *(5.5 API: `user_type` one of `TENANT_USER|TENANT_ADMIN|SUPER_ADMIN`)*.
  The role must be one scoped to that tenant: such a role has `tenant_id` set to the tenant
  *(seen on 5.5.3)* (`get roles fields=id,name,tenant_id,tenants,permissions`; create one with
  `POST /roles/`, `name`, `tenant_id`, permissions). Read back with `get managers/<id>`:
  `user_type: TENANT_ADMIN`, `tenant: {id, name}`, `roles` *(seen on 5.5.3)*. On 5.5 the spec types role
  `permissions` as a plain string; the Terraform provider and Ansible collection send
  `permissions_list` and `tenant_ids`. Dry-run first, and read the role back to confirm the
  permissions stuck. Permission names look like `create_logical`, `view_security`
  (`get roles` on the built-in roles shows the full set; realms: KB "Provisioning VMS Access").
- **Provider group**: set the tenant's `tenant_admins_group_name` to an AD/LDAP group (the
  provider must be attached to the tenant) and give that group a tenant role via the role's
  `ldap_groups`. A user may be in the tenant-admins list or the application-users list
  (`application_users_group_name`), not both.

Give the admin the tenant login: Web UI `https://<VMS>/#/login/<tenant domain or name>`; API
calls add `X-Tenant-Name: <tenant>` (helper: `VMS_TENANT_NAME`). New managers are asked to
change their password on first login. Never print the password back beyond handing it over.

Don't use `POST /users/` for this: `/users/` are data-access users (NFS/SMB/S3 identities).
One KB example creates a "tenant admin" that way; on 5.5 the manager route above is what
the spec and the "Managing Managers" page describe.

## Workflow 3: VAST DNS service

KB: "Configuring the VAST Cluster DNS Service" https://kb.vastdata.com/documentation/docs/configuring-the-vast-cluster-dns-service-55.md

One DNS service per cluster: listens on port 53 on its own VIP, answers for one domain suffix,
and returns one VIP from the pool whose `domain_name` matches the first label.

1. Ask for: a free IP on the network the corporate DNS can reach, its subnet CIDR, gateway (if
   the corporate DNS is on another subnet), optional VLAN, the suffix (e.g. `vast.corp.example`).
2. `vast_api.py call POST /dns/ --data '{"name":"vast-dns","vip":"<dns-ip>","vip_subnet_cidr":24,
   "vip_gateway":"<gw>","domain_suffix":"<suffix>","net_type":"EXTERNAL_PORT","enabled":true}'`
   *(5.5 API: `net_type` one of `NORTH_PORT|SOUTH_PORT|EXTERNAL_PORT|BOND|COUNT`; KB: EXTERNAL_PORT
   is the onboard management interface (default), NORTH_PORT the client-facing one; also `ttl`,
   `port`, `cnode_ids`, `vip_vlan`, `invalid_name_response`)*. Cloud: `POST /dns/allocate/`.
3. Set `domain_name` on each VIP pool (`PATCH /vippools/<id>/`).
4. The **customer's** DNS needs one delegation (NS/forward) of the suffix to the DNS service IP.
   VAST can't do that part; tell the user what to ask their DNS team for.
5. Test: `dig @<dns-ip> <pool-name>.<suffix>` (direct), then `dig <pool-name>.<suffix>` (through
   the corporate DNS).

Without VAST DNS, the alternative is round-robin A records on the customer DNS listing all of
a pool's VIPs; they must be updated by hand whenever pool ranges change (KB "DNS-Based Virtual
IP Distribution").

## Workflow 4: VLANs, gateways, port membership, CNode groups

KB: "Tagging Virtual IP Pools with VLANs" https://kb.vastdata.com/documentation/docs/tagging-virtual-ip-pools-with-vlans-55.md ·
"Configuring Network Access" https://kb.vastdata.com/documentation/docs/configuring-network-access-55.md

- **VLAN** is per VIP pool (`vlan`, 0 = untagged). Tagging the pool is not enough: the VLAN must
  be created on every cluster data switch and allowed on the uplinks (hybrid/trunk) to the
  client network. That is switch work the user (or VAST support) does; VMS doesn't do it.
- **Gateway** (`gw_ip`/`gw_ipv6`) is needed when clients are on other subnets and traffic is routed.
- **Port membership** `LEFT`/`RIGHT` puts a pool on one port of each CNode (e.g. two networks,
  one per port); default `ALL`.
- **CNode group** (`cnode_ids`) dedicates CNodes to a pool. On 16+ CNode clusters the VMS
  CNode carries no VIPs, so a small CNode group loses a node while VMS runs on it.
- **L3/BGP**: `enable_l3` + `bgp_config_id` (`get bgpconfigs`; KB "Configuring Layer 3 BGP
  Connections"). Moving a live cluster from L2 to L3 is a KB procedure of its own ("Migrating a
  Live VAST Cluster from L2 to L3 External Network") and makes clients remount.
- VIP failover needs **gratuitous ARP** accepted by the client-side switches (off by default
  on Arista and Juniper: KB "Configuring Network Access").
- Cluster-level network configuration (`/vms/<id>/network_settings/`, CNode data/management
  IPs) is an installation-time / support procedure (KB "Changing Network Configuration"); don't
  change it from here.

## Workflow 5: tenant settings that views inherit

- **NFSv4 delegations** (KB "NFSv4 File Delegations", https://kb.vastdata.com/documentation/docs/nfsv4-file-delegations-55.md):
  tenant `allowed_delegations` *(5.5 API: `DISABLED|READ|WRITE|READ_WRITE|NONE`)*; `NONE` means
  "no tenant default, set per view"; `DISABLED` blocks delegations in every view of the tenant
  and can't be overridden. Views use `allowed_delegations` with `USE_TENANT_ALLOWED_DELEG` to
  inherit *(5.5 API)*. `grant_unrequested_delegations_by_default` controls unrequested grants.
  List granted delegations: `get tenants/<id>/nfs4_delegs`; revoke one: `DELETE
  /tenants/<id>/nfs4_deleg/` (check the body with `spec show` and the KB `tenant
  nfs4-delegs-remove` page). Revoke delegations before restoring a snapshot on such a tenant (KB).
- **Encryption group** (EKM only; KB "Managing Encryption Groups and Keys"): set
  `encryption_group` at creation; it can't be changed later. `revoke_encryption_group`
  **makes all the tenant's data unreadable** until reinstated, and the key is shared by every
  tenant in the same group (`get tenants/<id>/same_encryption_group_tenants`). Treat
  revoke/rotate/deactivate as disruptive: warn, name every affected tenant, get an explicit yes.
- **Client IP ranges**: `client_ip_ranges` (list of `[start, end]`), via `PATCH /tenants/<id>/`
  with the full new list, or the dedicated `PATCH /tenants/<id>/client_ip_ranges/`
  *(5.5 API; its body isn't described by the spec: the CLI equivalent `tenant
  alter-client-ip-ranges` adds/removes ranges; check https://<VMS>/docs/ before using it)*.
  Removing a range cuts off those clients immediately. On a tenant with an AD provider, client
  IP ranges need that provider configured as "SMB allowed" (KB "Overview of Tenants").
- **SMB / NFS defaults**, `max_views`, `trash_gid`: plain tenant fields; see fields.md.

## Workflow 6: QoS

KB: "QoS Overview" https://kb.vastdata.com/documentation/docs/qos-overview-55.md ·
"Creating a QoS Policy" https://kb.vastdata.com/documentation/docs/creating-a-qos-policy-55.md

- **Tenant-wide limits** live on the tenant itself (`qos.static_limits`, `capacity_rules`), no
  policy object needed (KB "QoS Overview: Tenant Limits"). Static limit keys (KB `tenant create`):
  `max_reads_bw_mbps`, `max_writes_bw_mbps`, `max_reads_iops`, `max_writes_iops`, plus
  `burst_*` and `burst_*_loan_*`; 0 = unlimited.
- **QoS policies** (`/qospolicies/`) are per view, block volume or user: `policy_type`
  `VIEW|USER|VOLUME`, `mode` `STATIC|USED_CAPACITY|PROVISIONED_CAPACITY`, `limit_by`
  `BW|IOPS|BW_IOPS`, `tenant_id` *(5.5 API)*. A user gets at most one user policy per tenant.
  Capacity-based view limits need a quota on the path (VMS creates one if missing).
- Limits combine (the lowest applies); they don't apply to replication or snapshot traffic.

## Workflow 7: troubleshoot "client can't reach / mount / sees nothing"

Work top-down; each step is read-only.

1. **Is the VIP up and where?** `get vips` → is the IP listed, which `vippool`, `cnode`,
   `tenant_name`? `get vippools/<id>`: `enabled`, `sync`, `active_interfaces`. `get cnodes`: are
   CNodes `ACTIVE`? (`get monitoredvippools` also exists on 5.5, and pools have
   `client_monitoring_ips`, "external client monitoring IP ranges for VIP pool connectivity
   monitoring" per the Terraform docs; the KB doesn't describe them, so treat as informational.)
2. **Network path**: from the client, `ping <vip>`; check subnet/gateway/VLAN of the pool match
   the client's network; after a failover with no reachability, suspect gratuitous ARP on the
   switches.
3. **DNS**: `dig <fqdn>` vs `dig @<vast-dns-ip> <fqdn>`; the pool's `domain_name` and the DNS
   service's `domain_suffix` must form the FQDN the client uses; the corporate DNS must delegate.
4. **Right tenant?** Pool bound to a tenant → that tenant; check the client source IP is in
   that tenant's `client_ip_ranges` (if any). Shared pool → the source IP must be in some
   tenant's ranges, and that is the tenant the client lands in. NAT or proxies change the source
   IP (KB "Using Original Client IPs in Access Checks and Logs").
5. **View side**: the view must be in that tenant (`get views fields=path,tenant_id,protocols,policy_id`);
   its policy's host rules must include the client, and if the policy lists VIP pools
   (`permission_per_vip_pool`), the pool used must be in it (RO there means read-only).
6. **Protocol specifics** (exports, SMB shares, S3 endpoints): `references/views-protocols.md`.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Clients of a new tenant are rejected on a shared ("all tenants") pool | No tenant's client IP ranges contain their source IP | Add `client_ip_ranges` to the tenant, or give it its own tenant-bound pool |
| A client lands in the wrong tenant / sees another team's exports missing | Overlapping or wrong client IP ranges; or pool bound to another tenant | Ranges must not overlap between tenants; check `tenant_id` of the pool |
| A view policy's VIP pool list doesn't work as expected (or the change is refused) | A policy dedicated to a pool must use a pool serving the policy's own tenant | Use a pool of the same tenant (KB "Overview of Tenants"); read the `detail` of any 400 |
| Event Broker view can't use an existing pool | Each Kafka view needs a dedicated PROTOCOLS pool in its tenant, and it can't be swapped after creation | Create a new pool for the broker first (KB "Publishing Events to VAST Event Broker") |
| Tenant create fails on the name | Underscore or other character not allowed | Letters, digits, `-`, `.` only |
| VLAN-tagged pool unreachable | VLAN not created/allowed on cluster switches and uplinks | Switch configuration per KB "Tagging Virtual IP Pools with VLANs" |
| FQDN doesn't resolve | No DNS service, pool `domain_name` empty, or corporate DNS has no delegation | Workflow 3 |
| Tenant admin can't see VIP pools | By design: tenant admins have no VIP pool access | Cluster admin manages pools |
| Role values from older docs rejected | VIP pool roles vary by release (KB 5.5 CLI: `PROTOCOLS`, `REPLICATION`; older pages: `VAST_CATALOG`; Terraform docs: `BIG_CATALOG`; UI 5.5: "Query Engine") | Use the KB `vippool create` page for the cluster's release and existing pools |

## Destructive operations (warn first, next to the call)

- `DELETE /tenants/<id>/`: **deletes the tenant's data and directory and its views, quotas,
  identity policies...** (KB "Deleting Tenants"). The CLI needs `--force` if data exists.
  List `views_count`, views and VIP pools first; get the user to confirm the tenant name.
- `DELETE /vippools/<id>/` or changing its `ip_ranges`, `vlan`, `subnet_cidr`, `tenant_id`,
  `port_membership`, `cnode_ids`: **clients on removed/moved VIPs lose their mounts**. Check
  which views/brokers use it (view policies' `permission_per_vip_pool`, views' `kafka_vip_pools`).
- Removing client IP ranges, setting `allowed_delegations: DISABLED` (recalls delegations),
  encryption group revoke/rotate/deactivate, changing DNS `vip`/`domain_suffix`.

## Tools

- `vastpy-cli get tenants`, `vastpy-cli post vippools ...` (same paths and fields as above).
- Terraform `vast-data/vastdata`: `vastdata_tenant`, `vastdata_vip_pool`, `vastdata_dns`,
  `vastdata_qos_policy`, `vastdata_administrator_manager`, `vastdata_administrator_role`
  (check the provider docs for your provider version).
- VAST CLI on a CNode: `tenant create|modify|alter-client-ip-ranges`, `vippool create|modify`,
  `dns create`, `qospolicy create` (KB pages of the same names; `--help` is authoritative).

Verified: VAST 5.5.3 — endpoints, fields and enums checked in the cluster's spec; live
read-only GETs of tenants, VIP pools, VIPs, DNS, view policies, managers, roles; procedures
from KB 5.5 pages cited above; role values compared with older-release KB pages and the
Terraform provider docs. No create/modify calls were run.
