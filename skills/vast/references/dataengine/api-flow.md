# DataEngine through the REST API

The sequence of calls to set up DataEngine and a pipeline without the UI. Bodies are what VAST
**5.5.3** accepted. Before using any of them on another release, check each with
`vast_api.py spec show <path> post` (VMS) or `vast_api.py spec show <path> post --dataengine`.
VMS paths are under `/api/<v>/`; DataEngine paths are under `/api/<v>/dataengine/` and need a
JWT plus `X-Tenant-Name` (the helper's `--dataengine` / `de-get` does this).

Placeholders: `<tenant>`, `<tid>` (tenant id), `<pool-id>`, `<policy-id>`, `<broker-view>`,
`<source-view>`, `<owner>`, `<topic>`, `<k8s-vrn>`, `<namespace>`.

## 1. Event broker (VMS)

A broker view, in the tenant, with a VIP pool for Kafka clients:

```
POST /views/  {"path": "/<broker-view>", "bucket": "<broker-view>", "bucket_owner": "<owner>",
               "policy_id": <S3-native policy id>, "tenant_id": <tid>,
               "protocols": ["KAFKA", "S3", "DATABASE"], "kafka_vip_pools": [<pool-id>], "create_dir": true}
```

Topics (the default and dead-letter topics DataEngine needs, plus one per trigger if you like):

```
POST /topics/  {"database_name": "<broker-view>", "schema_name": "kafka_topics", "name": "<topic>",
                "topic_partitions": 8, "retention_ms": 604800000, "tenant_id": <tid>}
GET  /topics/?database_name=<broker-view>&tenant_id=<tid>
```

## 2. Enable DataEngine (DataEngine API)

```
POST data-engine  {"kafka_broker": {"type": "Internal", "name": "<broker-view>"},
                   "default_topic_name": "<default topic>", "dead_letter_topic_name": "<dead-letter topic>"}
GET  data-engine  → wait for setup.status == "completed" ("error" carries a message)
```

`kafka_broker.type` is `Internal` (VAST Event Broker) or `External`; an external broker over TLS
needs `kafka_ca_certificate` (base64) *(5.5 API)*.

## 3. Compute

VAST compute cluster (VMS, cluster admin):

```
GET  /computeclusters/
POST /computeclusters/<id>/tenants/bulk/  {"tenants_to_add": [<tid>]}
GET  /computeclusters/<id>/tenants/       → wait for the tenant's status DE_ATTACHED (see GET /vtasks/ for progress)
```

Either way, the DataEngine side then lists it:

```
GET kubernetes-clusters  → name, vrn (vast:dataengine:kubernetes-clusters:<name>), namespaces
```

An external cluster is linked with `POST kubernetes-clusters` (or the UI / `vastde compute-clusters link`)
after the DataEngine services are installed on it.

## 4. Container registry (DataEngine API)

```
POST container-registries  {"name": "<name>", "url": "<registry host[:port]>", "auth_type": "password",
                            "username": "...", "password": "...",
                            "primary_kubernetes_cluster": {"kubernetes_cluster_vrn": "<k8s-vrn>", "namespace": "<namespace>"}}
```

`auth_type`: `password`, `secret` (name of an existing pull secret) or `none`.
`is_accessible_to_data_engine: false` stops DataEngine validating a registry it can't reach *(5.5 API)*.

## 5. Secrets (DataEngine API)

```
POST kubernetes-secrets  {"kubernetes_cluster_vrn": "<k8s-vrn>", "namespace": "<namespace>", "secret_name": "<secret>",
                          "entries": [{"key": "<KEY>", "value": "<value>"}, ...]}
```

Functions read them with the runtime SDK (`ctx.secrets`); reference the secret by name in the
function deployment.

## 6. Trigger (DataEngine API)

Element trigger:

```
POST triggers/element  {"name": "<trigger>", "broker": {"type": "Internal", "name": "<broker-view>"},
                        "topic_name": "<topic>", "source_types": ["S3"],   // or ["NFS4"]
                        "config": {"events": ["ObjectCreated:*"], "source_bucket_name": "<source-view bucket>",
                                   "name_filters": {"prefixes": ["<prefix>"], "suffixes": ["<suffix>"]}}}
```

Events *(5.5 API)*: `ObjectCreated:*`, `ObjectRemoved:*`, `ObjectTagging:Put`, `ObjectTagging:Delete`.
Check the filter field names with `spec model TriggerFilters --dataengine`.
Schedule trigger: `POST triggers/schedule` (see `spec show /triggers/schedule post --dataengine`).
List all: `GET triggers/all` (the response includes the trigger's `vrn`, `topic` vrn and `status`).

## 7. Function (DataEngine API)

```
POST functions  {"name": "<function>", "artifact_type": "image", "artifact_source": "<repository path in the registry>",
                 "image_tag": "<tag>@sha256:<digest>", "container_registry_vrn": "<registry vrn>",
                 "runtime": "python-3.11", "architecture": "x86"}
GET  functions/<guid>/revisions   → revision_number of each image
PUT  functions/<guid>             (same body, new image_tag) → a new revision
```

## 8. Pipeline (DataEngine API)

```
POST pipelines  {"name": "<pipeline>", "kubernetes_cluster_vrn": "<k8s-vrn>", "namespace": "<namespace>",
  "manifest": {
    "triggers": [{"name": "t1", "vrn": "<trigger vrn>"}],
    "function_deployments": [{"name": "f1", "function_vrn": "<function vrn>", "revision": <n>,
       "config": {"environment_variables": [{"name": "KEY", "value": "value"}],
                  "secrets": ["<secret>"], "log_level": "INFO"}}],
    "links": [{"source": ["t1"], "destination": ["f1"], "topic": "<trigger's topic vrn>"}]}}
POST pipeline/<guid>/deploy
GET  pipelines/<guid>           → wait for status "Ready"
PUT  pipelines/<guid>           (new manifest) → a new pipeline revision; deploy again
```

Check the manifest's shape with `spec model Manifest-Input --dataengine` and
`spec model FunctionDeployment-Input --dataengine` (resources, batching and conditional links live there).

## 9. Removing it, in reverse

Pipelines → functions → triggers → registries (`DELETE <path>/<guid>`), then detach the compute
cluster (`POST /computeclusters/<id>/tenants/bulk/ {"tenants_to_remove": [<tid>]}`), then
`DELETE remove-data-engine` (see its body in the spec), then the views and topics. Each of these
stops whatever depends on it: confirm with the user first.
