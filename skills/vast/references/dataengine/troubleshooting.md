# Troubleshooting DataEngine

Work from the event outwards: did the event happen, did the trigger publish it, did the
pipeline consume it, did the function run, did it succeed?

## 1. Is DataEngine itself healthy?

- `de-get data-engine`: `setup.status` should be `completed`.
- Compute: `de-get kubernetes-clusters`; for a VAST compute cluster also `get computeclusters/`
  (`state`) and the tenant link (`get computeclusters/<id>/tenants/`). `GET /vtasks/` shows
  attachment progress and errors.
- External Kubernetes: `vastde status`, and `kubectl get pods -A` for the DataEngine services.

## 2. Did the trigger see the event?

- The trigger's `status` (`de-get triggers/all`).
- The event really matched: source type (S3 vs NFS4), the bucket, the event type, the prefix and
  suffix filters (on the object key for S3, the file path for NFS).
- NFS: NFS-type triggers watch **NFSv4** files (KB "Creating a Trigger"); check that the client
  mounted with NFSv4 (`vers=4.x`) and wrote into the view the trigger watches.
- Messages on the topic: the topic is a table in the broker view (`references/event-broker.md`);
  any Kafka client on the broker VIP can consume it.

## 3. Did the pipeline consume it?

- `de-get pipelines/<guid>`: `status` `Ready`. Anything else: read the full object (it carries
  the deployment error).
- In the pipeline's namespace: `kubectl -n <namespace> get pods,ksvc` (Knative services, one per
  function deployment) and the Kafka dispatcher pods. `Pending` + `Insufficient cpu`: the compute
  cluster is too small. `ImagePullBackOff`: the nodes can't pull the image (registry address,
  certificate, credentials, or a bare tag where a digest is needed).
- Functions run as Knative services, which can scale with load (possibly to zero when idle,
  depending on the deployment's settings): a missing pod is not by itself an error.

## 4. Did the function run, and succeed?

- `vastde logs` / `vastde traces` (or the UI's pipeline logs and traces).
- `kubectl -n <namespace> logs <function pod> -c user-container`: the runtime logs `Init Handler
  Completed` at start-up *(seen on 5.5.3)* and your handler's own log lines per event.
- Exceptions in `init` keep the function from becoming ready; exceptions in `handler` fail that
  event. Failed events are meant for the tenant's dead-letter topic: check it, and the KB
  ("Managing Pipelines", the Runtime SDK guide) for your release's retry behaviour.
- The function's credentials: the secret exists in the namespace and has the keys the code reads;
  its S3 user can read the source bucket and write the target.

## 5. Common errors

| Where | Error | Fix |
|---|---|---|
| Trigger create (NFS) | `nfs_triggers_delegations_conflict` | Turn off NFSv4 delegations on the source view. |
| View create | `...only have a view policy where the security flavor is S3 native.` | S3 Native policy for every view with DATABASE in its protocols. |
| Any DataEngine call | `No tenant was provided in request` | Add `X-Tenant-Name` (JWT auth). |
| Function create | image validation failure | Make the registry reachable from VMS, or skip validation where the API allows it. |
| Pipeline deploy | stays not Ready, revision can't resolve image | Reference the image by digest. |
| Function pod | `Insufficient cpu` | Bigger compute cluster or smaller resource requests. |

## 6. Is it DataEngine or my pipeline?

Run VAST's own minimal sample (KB "Run a 'Hello World' Pipeline" or the CLI's sample function)
on the same tenant. If that works, the problem is in your trigger, function or configuration.
