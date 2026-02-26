# gVisor isolated node workflow

This repo now includes an isolated node pool intended for sandboxed workloads:

- Terraform resource: `google_container_node_pool.gvisor_pool`
- Labels: `workload-isolation=gvisor`, `purpose=isolated-sandbox`
- GKE-managed taint: `sandbox.gke.io/runtime=gvisor:NoSchedule`
- Autoscaling defaults: min `0`, max `5`

The pool scales from zero, so sandbox workloads can be started on demand and drained back to zero when idle.

Important for GKE Standard: `runtimeClassName: gvisor` requires a node pool with GKE Sandbox enabled. In this repo, Terraform now configures that directly with `node_config.sandbox_config`.

## 1) Create and update the pool

Apply the full stack, or only the pool resource:

```bash
terraform apply -var-file=terraform.v3.tfvars -target=google_container_node_pool.gvisor_pool
```

Tune behavior with variables:

```hcl
enable_gvisor_pool       = true
gvisor_pool_machine_type = "e2-medium"
gvisor_pool_min_nodes    = 0
gvisor_pool_max_nodes    = 5
gvisor_pool_is_spot      = true
```

To disable and de-provision with Terraform:

1. Set `enable_gvisor_pool = false`
2. Run `terraform apply -var-file=terraform.v3.tfvars`

### 1b) Optional: create/delete on demand with gcloud

```bash
gcloud container node-pools create gvisor-sandbox-pool \
  --cluster="${CLUSTER_NAME}" \
  --zone="${ZONE}" \
  --machine-type="e2-medium" \
  --image-type="cos_containerd" \
  --enable-autoscaling --min-nodes=0 --max-nodes=5 \
  --num-nodes=0 \
  --sandbox type=gvisor
```

Use this mode only if you intentionally want node pool lifecycle outside Terraform. If Terraform manages the same pool name, creating/deleting it with `gcloud` can introduce drift.

Delete the on-demand sandbox pool:

```bash
gcloud container node-pools delete gvisor-sandbox-pool \
  --cluster="${CLUSTER_NAME}" \
  --zone="${ZONE}" \
  --quiet
```

## 2) Run an isolated workload and connect to it

Use the example manifest:

```bash
# from iac/gke-secure-gpu-cluster/
kubectl apply -f k8s/gvisor-isolated-example.yaml
```

This creates:

- `gvisor-echo` deployment (sandbox runtime requested)
- `gvisor-echo` ClusterIP service
- `caller` pod that can reach the service

Verify runtime and connectivity:

```bash
kubectl -n alt-default get pods -o wide
kubectl -n alt-default get pod -l app=gvisor-echo -o jsonpath='{.items[0].spec.runtimeClassName}'
kubectl -n alt-default exec caller -- curl -s http://gvisor-echo
```

Expected curl output:

```text
hello-from-gvisor
```

## 3) Dynamic start and de-provision model

For on-demand execution from Python, use this lifecycle:

1. Submit a short-lived Job with `runtimeClassName: gvisor` and the same selector/toleration.
2. Let cluster autoscaler create nodes when pending Pods appear.
3. Delete Job/Pods when work completes.
4. Let autoscaler scale the pool back down (to `gvisor_pool_min_nodes`, typically `0`).

This pattern avoids node warm capacity costs while still keeping strict placement isolation.

Scheduling note: keep the toleration for `sandbox.gke.io/runtime=gvisor:NoSchedule`. GKE applies this taint automatically on sandbox node pools.

## 4) Python runtime integration options

### Option A (recommended): Kubernetes-native trigger

From Python, create a Job/Pod through the Kubernetes API and let autoscaling react.

```python
from kubernetes import client, config

config.load_kube_config()
batch = client.BatchV1Api()

job = client.V1Job(
    metadata=client.V1ObjectMeta(name="sandbox-job"),
    spec=client.V1JobSpec(
        template=client.V1PodTemplateSpec(
            spec=client.V1PodSpec(
                restart_policy="Never",
                runtime_class_name="gvisor",
                node_selector={"workload-isolation": "gvisor"},
                tolerations=[
                    client.V1Toleration(
                        key="sandbox.gke.io/runtime",
                        value="gvisor",
                        effect="NoSchedule",
                        operator="Equal",
                    )
                ],
                containers=[
                    client.V1Container(
                        name="worker",
                        image="python:3.12-slim",
                        command=["python", "-c", "print('sandboxed run')"],
                    )
                ],
            )
        )
    ),
)

batch.create_namespaced_job(namespace="alt-default", body=job)
```

### Option B: Explicit node pool resizing

If you need deterministic pre-warm capacity, call GKE API (or `gcloud`) from Python to resize the pool before submitting work, then resize to `0` afterwards.

This is useful for latency-sensitive workloads where first-node startup time is too high.

## 5) Fast cleanup

Delete example workloads:

```bash
kubectl delete -f k8s/gvisor-isolated-example.yaml
```

Delete the isolated node pool (Terraform-managed):

```bash
terraform apply -var-file=terraform.v3.tfvars -var='enable_gvisor_pool=false'
```
