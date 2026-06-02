---
name: agent-sandbox-platform
description: Use when working on Agent Sandbox, gVisor runtime, sandbox templates, warm pools, router, CRDs, SandboxClaim, or isolated execution.
---

# Agent Sandbox Platform

Use this skill for the Terraform-managed Agent Sandbox controller, CRDs, runtime resources, router, gVisor scheduling, and sandbox execution path.

## Canonical Paths

- Terraform resources: `iac/gke-secure-gpu-cluster/k8s/agent_sandbox.tf`
- K8s module variables: `iac/gke-secure-gpu-cluster/k8s/variables.tf`
- gVisor node pool: `iac/gke-secure-gpu-cluster/main.tf`
- Main app integration: `apps/janet`

## Managed Resources

Terraform fetches upstream Agent Sandbox release manifests with the HTTP provider:

- `manifest.yaml`
- `extensions.yaml`

Terraform-managed runtime objects include:

- `SandboxTemplate`
- `SandboxWarmPool`
- `NetworkPolicy`
- `Service` named `sandbox-router-svc`
- `Deployment` named `sandbox-router-deployment`
- runtime KSA `sandbox-runtime-ksa`

## Runtime Templates

Expected templates in `alt-default`:

- `python-runtime-template`
- `python-runtime-template-small`
- `python-runtime-template-large`
- `python-runtime-template-pydata` when enabled

The warm pool template is selected by `enable_agent_sandbox_pydata_template`; pydata currently uses image pull secret `dockerhub-regcred`.

## Scheduling Model

Runtime pods use:

- `runtimeClassName = gvisor`
- node selector `workload-isolation=gvisor`
- gVisor node pool `gvisor-sandbox-pool`
- toleration key `sandbox.gke.io/runtime`

Router pods run as normal workloads and should not require gVisor scheduling.

## Lifecycle Versus Execution

Sandbox creation is Kubernetes API driven: clients create `SandboxClaim` resources, the Agent Sandbox controller creates/binds `Sandbox` resources, runtime pods, and per-sandbox services. The router is not required for claims or sandboxes to become Ready.

Sandbox execution is router driven in the current Janet integration: `k8s-agent-sandbox==0.2.1` sends `/execute` and file operation requests to `sandbox-router-svc` with `X-Sandbox-ID`, `X-Sandbox-Namespace`, and `X-Sandbox-Port` headers. If the router is down, claims can still start but Janet cluster-mode tool execution fails.

## Bootstrap Rule

CRDs must exist before runtime custom resources. On a fresh cluster, use two passes:

```bash
terraform apply -target=module.k8s -var-file=terraform.v3.tfvars -var='enable_agent_sandbox_runtime=false'
terraform apply -target=module.k8s -var-file=terraform.v3.tfvars -var='enable_agent_sandbox_runtime=true'
```

The helper shortcut is:

```bash
./scripts/deploy_with_secrets.sh --execute --project gke-gpu-project-473410 --var-file terraform.v3.tfvars --bootstrap-agent-sandbox
```

## Common Checks

```bash
kubectl get pods -n agent-sandbox-system
kubectl -n alt-default get sandboxtemplate,sandboxwarmpool
kubectl -n alt-default get deploy,svc | grep sandbox-router
kubectl -n alt-default rollout status deploy/sandbox-router-deployment
kubectl -n alt-default logs deploy/sandbox-router-deployment --tail=100
```

For claims and sandboxes:

```bash
kubectl -n alt-default get sandboxclaim
kubectl -n alt-default get sandbox
```

## Failure Modes

- Runtime resources fail to apply because CRDs are not established yet.
- Warm pool pods stay pending because the gVisor node pool is at zero, quota is unavailable, or tolerations/selectors do not match.
- Pydata runtime image pulls fail when `dockerhub-regcred` is missing.
- Router is down: `SandboxClaim`/`Sandbox` lifecycle can still work, but Janet backend cannot execute tools or file operations through the current Agent Sandbox client.
- Router image requires auth while Janet uses `k8s-agent-sandbox==0.2.1`: either use compatible router auth/client support, pin a compatible router image, or explicitly enable unauthenticated router mode with NetworkPolicy restrictions.
- Runtime NetworkPolicy blocks unexpected private address ranges by design.

## References

- `iac/gke-secure-gpu-cluster/k8s/agent_sandbox.tf`
- `iac/gke-secure-gpu-cluster/k8s/agent-sandbox.md`
- `iac/gke-secure-gpu-cluster/k8s/gvisor-isolated-nodes.md`
- `apps/janet/README.md`
- `docs/runbooks/gpu-pods-pending.md`
