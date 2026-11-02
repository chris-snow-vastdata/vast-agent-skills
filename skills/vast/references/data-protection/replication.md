# Replication in depth (5.5)

KB section "Replication" (5.5): start at "Overview of VAST Replication"
(`https://kb.vastdata.com/documentation/docs/overview-of-vast-replication-55.md`) and
"Replication Glossary of Terms". Search other releases with
`vast_api.py kb search 'replication' --version X.Y`.

## Kinds

| Kind | What it is | Protocols (5.5 KB) | Peers | RPO |
|---|---|---|---|---|
| Async replication | Scheduled snapshots of a protected path copied to one or more VAST peers; destination read-only | NFS, SMB, S3, block, VAST Database | 1..n (replication group) | snapshot interval + transfer time |
| S3 synchronous replication | Every write replicated; both sides read-write while connected ("active-active" for buckets) | S3 buckets only | exactly 1 | 0 while connected |
| Global access | Destination path served from the source with local caching (lease) | see KB "Global Access" | 1..n | n/a (not a backup) |
| Backup to S3 | Snapshots copied to an AWS / S3-compatible bucket (S3 replication peer) | all paths | S3 target | ≥ 6 h period |

Limits (KB "Data Protection Overview" 5.5): a path can't be sync-replicated to one peer and
async to another; sync can't be used on paths exposed by non-S3 protocols; async→sync conversion
needs at most one peer and S3-only paths. Indestructible object mode is not supported with any
replication or global access.

## Prerequisites checklist (both clusters)

1. Releases compatible (KB release notes / interoperability).
2. VIP pool with role `REPLICATION` on each cluster, reachable both ways; no domain name.
   (Remote VIP changes are learned only if the new range overlaps the old one; otherwise edit
   the peer's `leading_vip`.)
3. For `secure_mode: SECURE`: RSA certificate + key per cluster and the **same** root CA on both,
   installed under Settings → Certificates → *replication* (CLI `cluster modify
   --cluster-certificate --cluster-private-key --root-certificate`). KB "Encrypting Replication with mTLS".
4. Destination tenant exists (cross-tenant rule: tenant A can replicate to only one tenant per
   remote cluster).
5. Capacity on the destination (`space_left` on the peer).
6. If the clusters see each other on the management network, *DataSpace* in the Web UI offers a
   simpler setup flow (KB "Configuring Asynchronous Replication from DataSpace").

## Replication groups (more than two clusters)

KB "Async Replication Configuration Workflows" → *Multiple Destinations*: create a peer and a
policy from the source to each destination, one protected path with a stream per destination,
then on each destination a peer + policy to every other destination and add them to the same
protected path as **standby streams** (used after failover). Align policy start times; the
protected path's `sync_interval` (sync point guarantee) forces a common restore point at least
that often. Ungraceful failover in a group: `protectedpath force-failover`; on conflicts, choose a
source and *reattach* the others (KB "Reattaching Replication Streams to Protected Paths").

## Monitoring

| What | Where |
|---|---|
| Path state, role, health, RPO | `get protectedpaths` (`state`, `role`, `health`, `last_restore_point_time`) |
| Per-snapshot transfer | `get replicationrestorepoints` (`state`, `progress_promil`, `physical_backlog`, `network_bw_per_sec`) |
| Streams per destination | `get replicationstreams` |
| Peer link | `get nativereplicationremotetargets` (`state`, `last_heart_beat`, `space_left`) |
| Over time | Web UI *Protected Path Analytics*; `/prometheusmetrics/replications` |
| Bandwidth control | KB "Replication QoS" (5.5); stream priority: `replicationstream modify --priority-score` |
| Alarms | `get alarms` / events (see `references/monitoring.md`) |

A scheduled snapshot is skipped if the previous transfer is still running: if RPO keeps growing,
lengthen the period or raise bandwidth. Only one restore point per destination runs at a time;
an on-demand *Replicate Now* replaces a queued one.

## Failover decision table (async)

| Situation | Action | Data loss | Client impact |
|---|---|---|---|
| Planned move / DR test, peers connected | Graceful failover from destination | none | read-only on all peers during delta sync, then redirect |
| Source down, may come back | Ungraceful failover from destination (role Standalone) | writes since last restore point | redirect; old source may still accept writes if it is alive: fence it |
| Group, source unreachable | `force-failover` on the cluster to become source | as above | as above |
| After graceful | Graceful failover back | none | read-only window again |
| After ungraceful, primary back | Resume from survivor (becomes Source), wait for COMPLETE restore point, graceful failover from primary | primary's writes after last replicated snapshot are discarded | read-only window |
| After ungraceful, primary destroyed | Remove the peer configuration; protect the survivor to a new peer | - | - |

Before a planned failover: replicate now twice to minimise the delta (KB "Failover Capabilities
and Scenarios"). Abort is only possible during the read-only phase of a graceful failover.

## Sync replication turnover (S3)

KB "Turnover Scenarios for Synchronous Replication" (5.5): graceful turnover is run on the
secondary (`protectedpath modify --id ID --modify-replication-state --graceful`); both sides stay
read-write. If the peers lose contact for `sync_disconnect_time` (default 45 s), the secondary
**blocks access** and the primary becomes standalone read-write; after the link returns, rerun
the state change on the intended primary to resync. Combining sync + async: KB "Combining
Synchronous and Asynchronous Replication", "Recovery Scenarios for Combined Sync and Async Replication".

## Making the DR cluster usable

KB "Deploying a Failed-Over Replication Peer as a Working Cluster": configuration is **not** all
replicated. Download *VMS Data* from the peer (Web UI, or `GET
/nativereplicationremotetargets/{id}/download_vms_objects/`) and recreate as needed: views (nested
under the remote path if it differs), view policies (client host rules), AD/LDAP/NIS, local users
and groups, quotas (recreate after failover), VIP pools (no IP conflicts), DNS VIP, call home
(must stay unique), VMS roles. Replicated S3 access keys and identity policies arrive as *remote*
and must be **enabled** on the DR side; keys of local users are not replicated. For NFSv3 clients,
views with *global sync* on both sides keep file handles valid (KB "Preparing for Seamless
Replication Failover (NFSv3)"); the clients still need their mount VIP/DNS redirected.

## S3 bucket specifics

KB "S3 Access to Replicated Data" (5.5): with *bucket replication* on, buckets on/under the
protected path are recreated on each destination with the source's versioning, object-lock state,
ownership rule, anonymous access, has-db and bucket policy, provided the source bucket view uses
the tenant's *S3 default* view policy and the destination tenant has one. It's chosen at protected
path creation and can't be changed; on fresh 5.5 installs the default is off. KB articles "S3
Asynchronous Replication with Local Users and Identity Policy" (and the AD / bucket-policy
variants) walk through identity mapping for S3 replication on 5.2+.
