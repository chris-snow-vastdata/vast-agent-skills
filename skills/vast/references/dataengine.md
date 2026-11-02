# VAST DataEngine

DataEngine runs your containerised functions when things happen in the VAST cluster (an S3
object or an NFSv4 file is created or deleted, a tag changes) or on a schedule. It lives inside a
**tenant**, runs functions on a **Kubernetes compute cluster**, pulls their images from a
**container registry**, and moves events through an **event broker**. Read `SKILL.md`
first: it covers logging in, versions and checking every call against the cluster's spec.

## The objects and how they fit

```
tenant ─┬─ DataEngine enablement ── event broker (VAST Event Broker view, or a third-party Kafka)
        │                          default topic + dead-letter topic
        ├─ compute: a VAST compute cluster attached to the tenant, or an external Kubernetes
        │           cluster with the DataEngine services installed (one namespace per tenant)
        ├─ container registry (HTTPS, valid CA) linked to a Kubernetes cluster + namespace
        ├─ users: tenant admins, or application users (a group + the DataEngine identity policy)
        └─ source views for element triggers
trigger (element: source view + events + filters | schedule) ─► topic
function = an image in the registry (revisions = new image tags)
pipeline = triggers + function deployments (env, secrets, resources) + links (who calls whom)
           ─► deployed to a Kubernetes cluster/namespace (Knative services + Kafka dispatchers)
```

Order matters: **broker views and topics → enable DataEngine → compute → registry → users and
source views → triggers and functions → pipeline → deploy**.

## Three ways in

| Interface | Best for |
|---|---|
| Web UI, Data Engine pages | Enablement wizard, the visual pipeline builder, showing results. |
| `vastde` CLI ([releases](https://github.com/vast-data/dataengine-cli/releases)) | Developers: `functions init/build/localrun/create`, `triggers`, `pipelines create/deploy`, `logs`, `traces`, `metrics`, and `install`/`upgrade` of the services on an external Kubernetes cluster. Use the CLI release that matches the cluster (`vastde version`), and check each command with `vastde <cmd> --help`. |
| DataEngine REST API `https://VMS/api/<v>/dataengine/...` | Automation. **Tenant-scoped**: send a JWT plus `X-Tenant-Name` (see `SKILL.md`). Its own OpenAPI spec is served at `/api/<v>/dataengine/openapi.json`: `vast_api.py spec ... --dataengine`. |

For writing function code and manifests with `vastde`, VAST's own skills are in
[vast-data/data-engine-skills](https://github.com/vast-data/data-engine-skills); use them
alongside this one.

## Workflow: enable DataEngine on a tenant

KB: "Enabling DataEngine on a VAST Cluster Tenant" (`vast_api.py kb search 'Enabling DataEngine' --version X.Y`).

1. **Take stock**: the tenant and its VIP pools, any views with the `KAFKA` protocol, compute
   clusters (`get computeclusters/`), and whether DataEngine is already on
   (`de-get data-engine`: `setup.status`).
2. **Event broker**: to use the VAST Event Broker, the tenant needs a view with the `KAFKA`
   protocol and a VIP pool for it, plus a default topic and a dead-letter topic (see
   `references/event-broker.md`). For a third-party Kafka: its address, and its CA if it uses TLS.
3. **Compute**: either a VAST compute cluster attached to the tenant (needs a *cluster admin*;
   it takes CNode resources from the storage cluster: KB "Managing VAST Compute Clusters"), or
   an external Kubernetes cluster where `vastde install` (or the Helm chart, or the Zarf
   package for air-gapped sites) has installed the DataEngine services, with a namespace for
   the tenant.
4. **Container registry**: HTTPS with a valid CA certificate, reachable from the compute
   cluster's nodes; username and password, or a pull secret (`auth_type` password|secret|none
   *(5.5 API)*).
5. **Enable**: the wizard, `vastde setup-dataengine`, or `POST dataengine/data-engine` with the
   broker and the two topic names; wait until `setup.status` is `completed`. Then link
   the compute cluster and register the registry. The exact calls are in
   [references/dataengine/api-flow.md]()).
6. **Users**: tenant admins can use everything (they need the *Logical* realm for source views
   and *Security* for provisioning). Application users get access through a group on a provider
   connected to the tenant, assigned to the DataEngine role and the `data-engine-<tenant>`
   identity policy. See KB "Provisioning User Access and Permissions for DataEngine".

## Workflow: provision a source view for element triggers

KB: "Provisioning Source Views for Element Type Triggers". Only a manager (tenant or cluster
admin) can do this; application users can't.

| Source type | Protocols on the view | View policy flavor | Also |
|---|---|---|---|
| S3 (objects) | S3 bucket | S3 Native | |
| NFS (NFSv4 files) | S3 bucket **and** NFSv4 | Mixed Last Wins, S3 Native or NFS | **NFSv4 delegations off on the view** (the tenant may turn them on by default) |

Give the view a bucket name and a bucket owner, and add the application users' group to the
policy's bucket listing permission. The function reads NFS-written files through the same
bucket, so the policy must let the function's S3 user read files that NFS clients write.

## Workflow: a pipeline

1. **Function image**: `vastde functions init python-pip <name>`, write `init(ctx)` and
   `handler(ctx, event)`, `vastde functions build <name> --target <dir> --image-tag <tag>`, test
   with `vastde functions localrun` / `invoke`, push to the registry, note the image digest.
   Read the Runtime SDK guide for the cluster's release: what `ctx` offers differs between releases.
2. **Function resource**: `vastde functions create`, or `POST dataengine/functions` with the
   registry, repository and tag. New code is a new revision of the same function.
3. **Trigger**: element (source type, source view's bucket, events such as `ObjectCreated:*`,
   prefix/suffix filters, optional tag filters, the broker and topic) or schedule (Quartz cron).
4. **Secrets and environment variables**: create Kubernetes secrets through DataEngine (UI, or
   `POST dataengine/kubernetes-secrets`) and reference them by name in the deployment; keep
   keys and passwords out of environment variables. KB "Working with Secrets and Environment
   Variables" lists conventional names for functions that use VAST Database.
5. **Pipeline**: triggers, function deployments (function + revision + config: env, secrets,
   log level, batching, resources) and links (source → destination, over a topic). Create it,
   deploy it (`vastde pipelines deploy` or `POST dataengine/pipeline/<guid>/deploy`), and wait
   until its status is `Ready`.
6. **Prove it end to end**: cause the event (upload an object, write a file, wait for the
   schedule), then check the function ran: `vastde logs`, `vastde traces`, or the pipeline's
   logs and traces in the UI. Check the effect too (the object, row or message the function makes).

## Pitfalls

Symptom or exact error → cause → fix. More in [references/dataengine/troubleshooting.md]()).

| Symptom | Cause | Fix |
|---|---|---|
| Creating an NFS trigger: `View cannot have both NFSv4 Triggers and NFSv4 delegations enabled at the same time.` (`nfs_triggers_delegations_conflict`) *(5.5.3)* | Delegations are on for the source view, often inherited from the tenant | Turn them off on that view (on 5.5: view `allowed_delegations: NONE`), then retry. Check what the tenant allows: tenant `allowed_delegations`. |
| `A view where the Database is in the list of protocols can only have a view policy where the security flavor is S3 native.` *(5.5.3)* | A view with DATABASE in its protocols (a DB view, or a broker view that also has DATABASE) has a non-S3-native policy | Use an S3 Native policy for those views. |
| NFS-triggered function reads an empty or partial file | The producer's file was picked up before it finished writing | Producers write under a name the trigger's filter excludes (e.g. `*.part`), then rename to the final name. |
| Function creation fails validating the image | VMS can't reach the registry or authenticate to it | Fix reachability or credentials; where the API offers it, `skip_image_validation` *(5.5 API)* skips the check (the nodes must still be able to pull). |
| Pipeline revision never gets Ready; Knative reports it can't resolve the image | Knative resolves a tag to a digest from its controller, which may not reach or authenticate to the registry | Give the function its image by digest (`<tag>@sha256:...`) |
| Function or dispatcher pods stay Pending: `Insufficient cpu` | The compute cluster is too small for the pipeline's pods | Add capacity, or lower the deployment's resource requests. |
| DataEngine REST: `No tenant was provided in request` or `Invalid username/password` | Missing tenant scope, or basic auth with `X-Tenant-Name` | JWT plus `X-Tenant-Name` (the `SKILL.md` helper does this). |
| The spec lists required `x-vast-s3-access-key-id`, `x-tenant-guid`, `Authorization` headers | They are added by VMS when you call through `https://VMS/api/<v>/dataengine/` | Don't send them yourself. |

## Before changing a running pipeline

A pipeline update creates a new revision and redeploys it; a broken revision stops processing
(check how your release handles events that arrive during a redeploy in the KB "Managing Pipelines"). Show the user the new manifest, deploy, and check
`Ready` and a test event before calling it done. Deleting a trigger used by a deployed pipeline,
or disabling DataEngine on a tenant, stops processing for every pipeline that uses it.

Verified: VAST 5.5.3: a pipeline with an NFSv4 element trigger, the VAST Event Broker, a Python
function and VAST Database was built and run end to end through the VMS and DataEngine REST APIs;
the pitfalls above were hit there. Specs and KB 5.5 read; `vastde` commands from its v5.5.0-sp2 docs.
