# Cluster health, hardware state and capacity

Checked on VAST 5.5.3 (spec + live read-only GETs). Field names vary by release and by hardware
generation: confirm with `scripts/vast_api.py spec model Cluster` (and `CNode`,
`DNode`, `SSD`, ...) and print only the fields that exist.

## Contents
- [Health objects](#health-objects)
- [Cluster object fields](#cluster-object-fields)
- [Hardware states](#hardware-states)
- [Capacity: what the numbers mean](#capacity-what-the-numbers-mean)
- [Where capacity is used](#where-capacity-is-used)
- [Pitfalls](#pitfalls)

## Health objects

| Object | Endpoint (5.5.3) | State fields |
|---|---|---|
| Cluster | `GET /clusters/` | `state` (e.g. `ONLINE`), RAID and health fields below |
| VMS | `GET /vms/` | `state` (`CLUSTERED` = healthy; Prometheus `vms_state` 0 = `DEGRADED`) |
| CNodes | `GET /cnodes/` | `state`, `display_state`, `enabled`, `bmc_state`, `os_version`, `sync` |
| DNodes | `GET /dnodes/` | `state`, `enabled`, `bmc_state`, `os_version` |
| Boxes | `GET /cboxes/`, `/dboxes/`, `/eboxes/` (EBox systems), `/dtrays/` | `state` |
| Drives | `GET /ssds/`, `/nvrams/` | `state`, `enabled` |
| NICs | `GET /nics/`, `/nicports/` | `state`, `link_state` |
| PSUs, fans | `GET /psus/`, `/fans/` | `state` |
| Switches | `GET /switches/` (when switch monitoring is set up) | see KB **Ethernet Network Monitoring** |
| Licenses | `GET /licenses/` | expiry raises `LICENSE_REMAINING_DAYS_*` alarms |
| Load balancer probe | `GET /api/health/` (no login needed) | `{"status": "ok", "db": ..., "cache": ...}`: VMS service health only, not the cluster |

Which lists are populated depends on the hardware model (e.g. no EBoxes on CBox/DBox clusters,
and some systems don't report PSUs/fans through these lists). An empty list is not an error.

## Cluster object fields

Seen on the 5.5.3 cluster object; read them with
`vast_api.py get clusters fields=name,state,ssd_raid_state,...`:

| Group | Fields |
|---|---|
| Identity | `name`, `sw_version`, `build`, `psnt`, `uptime`, `leader_cnode`, `leader_state` |
| Data protection | `ssd_raid_state`, `nvram_raid_state`, `memory_raid_state` (`HEALTHY` when good), `raid_rebuild_progress` (text), `ssd_raid_rebuild_progress`, `nvram_raid_rebuild_progress`, `raid_drives_can_fail`, `remaining_stripes_health`, `md_usage_health` |
| Activity | `iops`, `rd_iops`, `wr_iops`, `md_iops`, `bw_mb`, `rd_bw_mb`, `wr_bw_mb`, `latency_ms`, `rd_latency_ms`, `wr_latency_ms` (current values) |
| Physical | `physical_space`, `physical_space_in_use`, `free_physical_space`, `physical_space_in_use_percent` (+ `_tb` variants) |
| Usable | `usable_capacity_bytes`, `free_usable_capacity`, `usable_capacity_tb`, `free_usable_capacity_tb` |
| Logical | `logical_space`, `logical_space_in_use`, `free_logical_space`, `logical_space_in_use_percent` |
| Data reduction | `drr` (ratio), `drr_text` (e.g. `3.1:1`), `logical_drr_percent`, `physical_drr_percent` |
| Other limits | `used_handles_count`, `max_handles_count`, `used_handles_percent`, `logical_inodes_in_use_num`, `quotas_used_capacity`, `quotas_allocated_capacity` |
| Changes in progress | `upgrade_state`, `upgrade_phase`, `upgrade_progress` (`cnodes`/`dnodes` done/total), `available_upgrade_version`, `expansion_state`, `dbox_migration_state`, `burst_mode_state` (`NONE|BURST|POST_BURST|...`) |

`/clusters/dboxes_total_capacity/` needs ids (`ids must be provided` otherwise).

## Hardware states

Drive, NIC, PSU and fan `state` enum *(5.5.3 spec)*: `UNKNOWN`, `HEALTHY`, `ACTIVE`, `FAILED`,
`FAILING`, `LOGIN_FAILED`, `ACTIVATING`, `INACTIVE`, `DEACTIVATING`, `PHASING_OUT`,
`ENTER_PHASING_OUT`, `EXIT_PHASING_OUT`. CNode/DNode/box `state` is a free string
(`ACTIVE` when good, seen on 5.5.3). Treat anything other than `ACTIVE`/`HEALTHY`, or
`enabled: false`, as worth a closer look, then read the alarms for that object
(`vast_api.py get alarms object_type=SSD`). `UNKNOWN` means VMS has no current reading for that
component; check its alarms and the Web UI Infrastructure page before calling it failed.

Activating/deactivating nodes, power cycling and LED control (`/cnodes/{id}/control_led/` ...)
are changes; KB **Managing Hardware** (5.5) covers them. Hardware replacement goes through VAST Support.

## Capacity: what the numbers mean

KB **Understanding VAST Capacity**:

- **Physical**: raw space the drives report (after an initial reservation at install).
- **Usable**: what can be written with no data reduction, after data protection and reserve overheads.
- **Logical**: what applications wrote (before reduction) and a prediction of how much more fits
  at the current reduction ratio. Logical free = logical space − logical used; it moves when the DRR changes.
- **DRR** (data reduction ratio) = logical used ÷ usable used, roughly. Quotas count **logical** usage.
- Capacity alarms are on `Capacity,physical_space_in_use_percent` (5.5.3 defaults 85/90/95 %);
  KB **Cluster Available Capacity Alerts** explains what happens near full and what to do.

## Where capacity is used

| Question | Call (5.5.3) |
|---|---|
| Biggest views | `vast_api.py get views fields=id,path,tenant_name,logical_capacity,physical_capacity ordering=-logical_capacity page_size=20` |
| Per tenant | `vast_api.py get tenants fields=id,name` then ad hoc `object_type=tenant` with `TenantMetrics,logical_capacity`, `TenantMetrics,drr`, `TenantMetrics,snapshot_aggregated_usage`; or `GET /tenants/top_tenants/` |
| Quotas near limit | `vast_api.py get quotas fields=id,name,path,tenant_id,state,pretty_state,used_capacity,hard_limit,soft_limit,percent_capacity` (sort client-side) |
| Directory breakdown | `GET /capacity/?path=/some/dir&type=usable|logical|unique&tenant_id=<id>` (path and its direct children; `unique` = what deleting it would free) |
| Several paths' estimates | `GET /capacity/capacity_estimation/?path=/a,/b&separator=,` |
| Block volume | `GET /volumes/{id}/fetch_capacity/` |
| Snapshots | `vast_api.py get snapshots fields=id,name,path,created` (space reclaim depends on protection policies: see `references/data-protection.md`) |
| Capacity trend | ad hoc `object_type=cluster` `prop_list=Capacity,physical_space_in_use` `time_frame=30D granularity=days aggregation=max` |

`/capacity/` is the Web UI's Analytics → Capacity page (KB **Capacity Overview**, **Viewing
Capacity Analytics**): estimates from a periodic scan, so `time` in the response says how fresh it
is, small directories are folded into `small_folders`, and a new cluster can return zeros until
the first scan. KB **Capacity Analysis with vastpy-cli** shows deeper per-directory analysis
(VAST Catalog / big-catalog queries) for large trees.

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Logical free shrank though nothing was written | DRR dropped (new data reduces less), so the prediction fell | Explain logical vs usable; watch `physical_space_in_use_percent` |
| Deleting a big directory freed little | Its data dedupes against other data, or snapshots hold it | Check `type=unique` in `/capacity/`; check snapshots |
| `/capacity/` shows zeros or old `time` | Capacity estimation hasn't scanned yet | Wait for the next scan; use view `logical_capacity` meanwhile |
| Quota usage ≠ `du` on a client | Quotas count logical bytes (1-byte accounting, KB) | Expected |
| `ids must be provided` | `/clusters/dboxes_total_capacity/` needs `ids` | Pass DBox ids |
