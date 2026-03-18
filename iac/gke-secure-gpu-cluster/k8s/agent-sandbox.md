# Agent Sandbox on this cluster

This repository manages Agent Sandbox through Terraform (`module.k8s`), not through manual `kubectl apply` of upstream manifests.

## What is already in place

- Cluster mode: GKE Standard
- RuntimeClass: `gvisor`
- Dedicated node pool: `gvisor-sandbox-pool`
- Node placement controls:
  - label: `workload-isolation=gvisor`
  - taint: `sandbox.gke.io/runtime=gvisor:NoSchedule`

## Terraform-managed resources

Agent Sandbox resources are defined in `k8s/agent_sandbox.tf` and include:

- controller namespace/service account/service/roles/bindings
- CRDs (`sandboxes`, `sandboxclaims`, `sandboxtemplates`, `sandboxwarmpools`)
- runtime resources in `alt-default`:
  - `SandboxTemplate` (`python-runtime-template`)
  - optional `SandboxTemplate` (`python-runtime-template-pydata`)
  - `SandboxWarmPool` (`python-sandbox-warmpool`)
  - router `Service` and `Deployment`

## Apply flow

For a fresh install on a cluster where CRDs are not yet present:

```bash
terraform apply -target=module.k8s -var='enable_agent_sandbox_runtime=false' -var-file=terraform.v3.tfvars
terraform apply -target=module.k8s -var='enable_agent_sandbox_runtime=true' -var-file=terraform.v3.tfvars
```

Automated equivalent:

```bash
./scripts/deploy_with_secrets.sh --execute --project <project-id> --var-file terraform.v3.tfvars --bootstrap-agent-sandbox
```

Note: if runtime objects already exist and you run bootstrap mode, pass 1 can remove runtime objects before pass 2 recreates them.

### Idle-at-zero mode

You can keep runtime resources managed while allowing the gVisor pool to scale to zero when idle by setting:

- `enable_agent_sandbox_runtime = true`
- `agent_sandbox_warm_pool_replicas = 0`
- `agent_sandbox_router_replicas = 0`

## Verify runtime status

```bash
kubectl get pods -n agent-sandbox-system
kubectl get sandboxtemplate,sandboxwarmpool -n alt-default
kubectl get deploy,svc -n alt-default
kubectl get pods -n alt-default
```

## Start a sandbox with SandboxClaim

Apply the example claim:

```bash
kubectl apply -f k8s/agent-sandbox-claim-example.yaml
kubectl -n alt-default get sandboxclaim python-runtime-claim
kubectl -n alt-default get sandboxes.agents.x-k8s.io
```

Release the claim:

```bash
kubectl -n alt-default delete sandboxclaim python-runtime-claim
```

## Python client example

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install kubernetes
```

Run the repository client (creates a claim and waits for a running sandbox pod):

```bash
python3 scripts/agent_sandbox_claim_client.py
```
