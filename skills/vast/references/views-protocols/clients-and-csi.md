# Client side: NFS, SMB, NVMe/TCP and Kubernetes (vast-csi)

Use a VIP (or the VIP pool's DNS name) of the view's **tenant**, never the VMS management
address. For Kerberos (NFSv4 krb5*, SMB) always use a DNS name that has the right SPN
(KB "Workflow for Enabling Client Protocol Access", 5.5).

## NFS

Standard Linux `mount` syntax; the export path is the view `path`, or its `alias` for NFSv3.

```bash
# NFSv3 (alias or full path)
sudo mount -t nfs -o vers=3 <vip-or-dns>:/projects /mnt/projects
# NFSv4.1 / 4.2: path in the NFSv4 pseudo file system = the view path
sudo mount -t nfs -o vers=4.1 <vip-or-dns>:/exports/projects /mnt/projects
sudo mount -t nfs -o vers=4.2,sec=krb5 <dns-name>:/exports/projects /mnt/projects
# fstab
<vip-or-dns>:/exports/projects  /mnt/projects  nfs  vers=4.1,_netdev  0 0
```

- A view with `NFS4` accepts 4.1 and 4.2, not 4.0 (KB "NFS Overview", 5.5). `NFS` = NFSv3.
- NFSv4 walks the pseudo file system from `/`; see the root-access pitfall in SKILL.md and KB
  "Limiting Access to / (root) for NFSv4" (https://kb.vastdata.com/docs/limiting-access-to-root-for-nfsv4.md).
- Performance: one TCP connection per mount is the usual bottleneck; more mounts, `nconnect`
  or VAST-NFS (multipath) help. KB "NFS Tuning" (https://kb.vastdata.com/docs/nfs-tuning.md),
  e.g. `lookupcache=positive` when files appear from other hosts.
- `showmount -e` output can be suppressed by the cluster (KB "Suppressing showmount Command
  Output on NFSv3 Clients", 5.5): an empty list isn't proof the export is missing.
- Quota usage: `quota`/`rquota` works for NFSv3 (GETQUOTA only); `df` shows the directory quota.

| Client symptom | Likely cause |
|---|---|
| `access denied by server while mounting` | host not in the policy's RW/RO lists; wrong path/alias; VIP of another tenant |
| `mount(2): Operation not permitted` on NFSv4 | NFSv3-only parent view, or no traverse on a parent |
| `Permission denied` as root | root squash |
| `Stale file handle` | view deleted/recreated or path moved; remount |
| `nfs4_setfacl` / `setfacl` fail | flavor doesn't allow it (SKILL.md, flavors) |

## SMB

```powershell
net use Z: \\<dns-name>\finance
```
```bash
sudo mount -t cifs //<dns-name>/finance /mnt/finance -o sec=krb5,vers=3.1.1
```
Kerberos is the default; NTLMv2 is the fallback (KB "Authentication for SMB Access", 5.5).
Multichannel: KB "SMB3 Multichannel Best Practices". Open handles:
`GET /views/list_open_smb_handles/`; connections: `GET /clusters/list_smb_client_connections/`.

## NVMe/TCP block (Linux)

From KB "Configuring an NVMe/TCP Client on Linux for VAST Cluster Block Storage" (5.5,
https://kb.vastdata.com/documentation/docs/configuring-an-nvme-tcp-client-on-linux-for-vast-cluster-block-storage-55.md):

```bash
sudo yum install nvme-cli            # or apt install nvme-cli
cat /etc/nvme/hostnqn                # give this NQN to POST /blockhosts/
cat /sys/module/nvme_core/parameters/max_retries   # check per KB for HA
sudo modprobe nvme-tcp
sudo nvme discover -t tcp -a <vip> -s 8009
sudo nvme connect -t tcp -n <subsystem nqn> -a <vip>      # or:
sudo nvme connect-all -t tcp -a <vip> -s 8009
sudo nvme list-subsys                # one path per VIP, up to 16
sudo nvme list
```
Persist with `/etc/nvme/discovery.conf` (`-t tcp -a <vip> -s 8009`) and the KB's transport
(udev) rules; see also KB "Persisting NVMe-oF over TCP Across Reboots" and "NVMe/TCP and
LACP host guidance". Supported clients (KB 5.5): RHEL 8.8/9.4, Ubuntu 24.04, VMware ESXi 7.0U3+.

## Kubernetes: vast-csi

Public repo https://github.com/vast-data/vast-csi; KB "CSI Driver Administrator's Guide"
(https://kb.vastdata.com/documentation/docs/csi-driver-administrator-s-guide.md). Driver 2.7.x
supports Kubernetes 1.25–1.36 and VAST 4.1+ (some features need newer: tenant selection 5.3.3,
NFS mTLS 5.5.0) per KB "Deploy VAST CSI Driver".

Cluster-side prerequisites (create with SKILL.md workflows, after asking):
- A VIP pool and a view policy **in the same tenant** (NFS: the policy's host rules must
  admit every Kubernetes node; squash settings decide what root in pods can do, so choose
  them with the user). Block: a subsystem (BLOCK view).
- A VMS user or API token for the driver, stored in a Kubernetes Secret.

```bash
kubectl create secret generic vast-mgmt -n vast-csi \
  --from-literal=endpoint=<vms address> --from-literal=token=<api token>
# (or username/password; add tenant=<name> only for a tenant-admin user/password login)
helm repo add vast https://vast-data.github.io/vast-csi
helm install csi-driver vast/vastcsi -f values.yaml -n vast-csi --create-namespace
helm install csi-block  vast/vastblock -f values-block.yaml -n vast-block --create-namespace
```

`values.yaml` (NFS, chart `vastcsi`; keys from its `values.yaml`, 2.7.x):
```yaml
storageClassDefaults:
  secretName: vast-mgmt
  secretNamespace: vast-csi
storageClasses:
  vastdata-filesystem:
    storagePath: /k8s/volumes        # base path; one view per PV under it
    vipPool: <vip pool name>         # or vipPoolFQDN: <pool dns name>
    viewPolicy: <view policy name>
    qosPolicy: ""                    # optional VIEW QoS policy name
    mountOptions: ["nfsvers=4"]      # or vers=3; xprtsec=tls for NFS TLS
    reclaimPolicy: Delete
    allowVolumeExpansion: true
```
`values-block.yaml` (chart `vastblock`):
```yaml
storageClassDefaults:
  secretName: vast-mgmt
storageClasses:
  vastdata-block:
    subsystem: <subsystem name>      # the BLOCK view's name
    vipPool: <vip pool name>
    fsType: ext4                     # for volumeMode: Filesystem
```
PVC: `storageClassName: vastdata-filesystem` (RWX works over NFS) or `vastdata-block` with
`volumeMode: Block`, `accessModes: [ReadWriteOnce]`. Block nodes need host `nvme-cli` and the
`nvme-tcp` module (chart README). Check the chart's own `values.yaml` for the version you
install (`helm show values vast/vastcsi --version <v>`); options change between releases.

| CSI symptom | Cause / fix |
|---|---|
| PVC Pending, controller log VMS 400 | API token **and** `tenant` in the secret: drop `tenant` (chart docs) |
| PVC Pending, 403 | VMS user lacks rights on views/quotas/QoS realms |
| Mount fails on nodes | node IPs not in the view policy RW list; VIP pool not reachable; pool and policy in different tenants |
| Deletions slow / fail on old clusters | without Trash Folder Access (VAST < 4.7.0-SP6 or disabled) set `deletionVipPool` and `deletionViewPolicy` (same flavor and tenant, no root squash) |
| Block pods `ContainerCreating` | `nvme-tcp`/`nvme-cli` missing on node; node DaemonSet on control-plane nodes |
