# Cluster security settings: certificates, mTLS, encryption at rest, auditing

All paths and fields from the VAST 5.5.3 spec; re-check on another release with
`vast_api.py spec paths 'certificate|encryption|ekm|audit'` and `spec show <path> <method>`.
None of these were changed during verification.

## VMS certificate and TLS

KB: "Installing an SSL Certificate for VMS" https://kb.vastdata.com/documentation/docs/installing-an-ssl-certificate-for-vms-55.md,
"Managing Certificates" https://kb.vastdata.com/documentation/docs/managing-certificates-55.md

- VMS ships with a self-signed certificate. Install a CA-signed one (PEM certificate + key):
  `PATCH /vms/<id>/set_certificate/` (fields `ssl_certificate`, `ssl_keyfile` on `/vms/`), or Web UI
  Settings -> Certificates -> "VMS". `PATCH /vms/<id>/reset_certificate/` returns to self-signed.
  Read current info: `get vms fields=id,ssl_certificate_info,min_tls_version` (no key material).
- Minimum TLS: `min_tls_version` `1.2|1.3` (5.5 API; default 1.2). Ciphers: CLI
  `vms set_ssl_ciphers` (KB). **Impact:** old clients/tools that cannot do TLS 1.3 lose access.
- Other certificates on the same page (KB): S3 HTTPS, NFS TLS, replication mTLS, Kafka,
  NFS/Kafka mTLS, call home. API objects: `/certificates/` (`cert_type`
  `WEBHOOK|KAFKA|KAFKA_MTLS|SMTP|EKM`) and `/tlscertificates/`; see the `references/views-protocols.md`
  and `references/event-broker.md`s for their use.

## VMS client certificates (mTLS for the UI and REST API)

KB: "Enabling Client Certificate Validation for VMS Clients" https://kb.vastdata.com/documentation/docs/enabling-client-certificate-validation-for-vms-clients-55.md

- Upload a CA certificate + key as the "VMS mTLS Auth" certificate:
  `PATCH /vms/<id>/set_client_certificate/` (fields `ssl_client_certificate`, `ssl_client_keyfile`);
  remove with `PATCH /vms/<id>/remove_client_certificate/`. `ssl_client_certificate_info` shows
  whether one is set (null when not, seen on 5.5.3).
- After upload, **every** REST API and Web UI client must present that certificate or one signed
  by it. **Impact:** automation (Terraform, CSI, exporters, this helper) breaks unless configured
  with a client cert (`curl --cert/--key`). Before enabling: issue client certs, test one, and keep a
  path to remove it (CLI on a CNode: `vms remove_client_certificate`).

## Encryption at rest and EKM

KB: "Overview of Encryption of Data at Rest" https://kb.vastdata.com/documentation/docs/overview-of-encryption-of-data-at-rest-55.md,
"Enabling Encryption After Installation" https://kb.vastdata.com/documentation/docs/enabling-encryption-after-installation-55.md,
"Managing Encryption Groups and Keys" https://kb.vastdata.com/documentation/docs/managing-encryption-groups-and-keys-55.md,
"Modifying EKM Configuration" https://kb.vastdata.com/documentation/docs/modifying-ekm-configuration-55.md,
"Avoiding Accidential Data Loss through Encryption Key Expiration" https://kb.vastdata.com/documentation/docs/avoiding-accidential-data-loss-through-encryption-key-expiration-55.md

Facts (KB 5.5): AES-256-XTS; disabled by default; can be enabled at install (internal keys or
EKM) or later with internal keys, and an EKM added afterwards. Supported EKMs listed in the KB
(e.g. Thales CipherTrust, Fortanix, HashiCorp Vault Enterprise KMIP, Entrust, Utimaco, Akeyless).
With an EKM, keys are per **encryption group** (per cluster, tenant, group of tenants, or
*encrypted path*). The default tenant uses the internal group `INTERNAL_ENCRYPTION_GROUP_CRN`
and never EKM keys: use another tenant or encrypted paths. A tenant's encryption group is set at
tenant creation and cannot be changed later.

| Read | Path / field (5.5 API) |
|---|---|
| Cluster encryption | `get clusters fields=id,enable_encryption,encryption_type,ekm_servers` (`encryption_type` `INTERNAL` seen) |
| Groups | `get encryptiongroups` (`crn`, `state`: `INIT|ACTIVE|REVOKE_IN_PROGRESS|...|REVOKED|REINSTATE_IN_PROGRESS|...|EKM_REVOKED|...`) |
| Tenants sharing a group | `get tenants/<id>/same_encryption_group_tenants` |

| Change | Path | Impact |
|---|---|---|
| Enable encryption (internal keys) | cluster setting (`enable_encryption`; follow the KB procedure) | **rewrites all data on the cluster**, scrubs and restripes; plan capacity and time |
| Add EKM | `POST /clusters/<id>/add_ekm/` (`ekm_servers`, `ekm_proxy_address`, `ekm_auth_domain`, ...) | key availability now depends on the EKM |
| Rotate key-encryption key | `POST /encryptiongroups/<id>/rotate_encryption_group_key/` or `POST /tenants/<id>/rotate_encryption_group_key/` | none to clients; prefer rotating on the cluster, not the EKM (KB) |
| Rotate master key | `POST /clusters/rotate_master_encryption_group_key/` | cluster-wide; follow KB |
| Deactivate / reinstate | `.../deactivate_encryption_group/`, `.../reinstate_encryption_group/` (encryption group or tenant) | data of the group (all paths of the tenant) **inaccessible until reinstated** |
| Revoke | `.../revoke_encryption_group/` | **keys destroyed, data permanently unrecoverable** |

The 5.5 KB uses the words inconsistently between pages (the "Deactivating" section points to the
CLI `revoke-encryption-group` command and the "Revoking" section to `deactivate-encryption-group`).
Before any of these calls, read the per-command KB page for the release and confirm with the
user, in writing, which outcome they want. Avoid expiry dates on EKM keys: expiry on the EKM
revokes the keys on the cluster (KB); the cluster alarms 7, 2 and 1 days before.

## Protocol auditing

KB: "Protocol Auditing Overview" https://kb.vastdata.com/documentation/docs/protocol-auditing-overview-55.md,
"Configuring Global Auditing Settings" https://kb.vastdata.com/documentation/docs/configuring-global-auditing-settings-55.md,
"Configuring Auditing with View Policies" https://kb.vastdata.com/documentation/docs/configuring-auditing-with-view-policies-55.md,
"Audited Protocol Operations" https://kb.vastdata.com/documentation/docs/audited-protocol-operations-55.md,
"Audit Log Record Attributes" https://kb.vastdata.com/documentation/docs/audit-log-record-fields-55.md,
"Viewing Protocol Audit Logs" https://kb.vastdata.com/documentation/docs/viewing-protocol-audit-logs-55.md

Audits SMB, NFSv3, NFSv4, S3 and VAST DB operations. Global baseline: `GET|PATCH /clusters/<id>/auditing/`;
fields seen on 5.5.3 (all off on a new cluster):

```json
{"audit_dir_name": ".vast_audit_dir", "read_access_users": [], "read_access_users_groups": [],
 "max_retention_period": 1, "max_retention_timeunit": "h", "max_audit_dir_size": null,
 "protocols": [], "enable_vast_db_audit": false, "enable_json_audit": false,
 "protocols_audit": {"create_delete_files_dirs_objects": false, "modify_data": false,
   "modify_data_md": false, "read_data": false, "read_data_md": false,
   "session_create_close": false, "log_full_path": false, "log_username": false,
   "log_deleted_files_dirs": false, "log_extended_error_information": false}}
```

- KB defaults: audit dir `.vast_audit_dir` under the default tenant's root; file roll-over 1 GB;
  directory size unlimited; retention one hour unless changed ("Keep forever" is an option).
- `protocols` values are not enumerated in the 5.5.3 spec; the CLI uses `NFSv3,SMB,...`
  (`cluster modify --audit-protocols`). Set one in the Web UI and read it back to learn the exact strings.
- Destinations: VAST DB table (`enable_vast_db_audit`, query via `/vastauditlog/query_data/`,
  `/vastauditlog/columns/`, `/vastauditlog/stats/`, Database realm) and/or JSON files
  (`enable_json_audit`) readable through a view on the audit directory by `read_access_users`/groups.
- Per view: the view policy's `protocols` + `protocols_audit` add auditing on top of the global
  baseline (they cannot turn off what is on globally).
- Volume and cost scale with the operations chosen; read auditing is the heaviest.

## VMS auditing and syslog

- RBAC changes and login attempts are VMS events (KB "Provisioning VMS Access").
- Forward to syslog: `GET|PATCH /eventdefinitionconfigs/<id>/` fields `syslog_host`, `syslog_port`,
  `syslog_protocol` (`udp|tcp`), `syslog_vms_audit`, `syslog_shell_audit`, `syslog_secure_audit`,
  `syslog_ipmi_audit`, `audit_logs_retention`; test with `PATCH /eventdefinitionconfigs/<id>/test/`
  (5.5 API). See `references/monitoring.md`.
