---
name: monorepo-inventory-docs
description: Use when navigating the monorepo, updating docs, explaining architecture, creating onboarding steps, or answering where code/resources live.
---

# Monorepo Inventory And Docs

Use this skill for repo navigation, architecture explanations, onboarding, documentation updates, inventory checks, and distinguishing Terraform-managed, Helm-managed, and manually-applied resources.

## Repo Map

- `iac/`: Terraform and cluster infrastructure.
- `iac/gke-secure-gpu-cluster`: main GKE stack.
- `iac/gke-secure-gpu-cluster/k8s`: Terraform-managed Kubernetes module.
- `iac/sandbox_workspace_provisioning_setup`: checks/docs for lazy sandbox workspace provisioning.
- `apps/janet`: main React/FastAPI sandboxed agent platform.
- `apps/litellm-gateway`: LiteLLM and vLLM GPU workloads.
- `apps/cluster-authz-manager`: authz control plane component.
- `apps/sandboxed-react-agent-authz`: authz UI/backend app.
- `apps/alt-default-ops-console`: operational console for `alt-default`.
- `setup_scripts`: workstation setup and optional infra/auth examples.
- `docs`: deployment guide, inventory, links, runbooks.
- `hybridcloud`: hybrid/on-prem supporting services such as postgres.

## Documentation Sources Of Truth

- Top-level overview: `README.md`
- Documentation index: `docs/README.md`
- Deployment operations: `docs/deploy-and-operations.md`
- Deployed inventory: `docs/inventory.md`
- Architecture notes: `REPO_ARCHITECTURE.md`
- Manual quota notes: `required_manual_adjustments.md`

## Management Boundaries

When answering or editing docs, preserve these distinctions:

- Terraform-managed GCP resources live under `iac/gke-secure-gpu-cluster`.
- Terraform-managed Kubernetes resources live in `module.k8s` under `iac/gke-secure-gpu-cluster/k8s`.
- Janet app resources are Helm-managed under `apps/janet/helm` and operated by `apps/janet/ops.sh`.
- Legacy raw manifests exist in some app `k8s/` directories and may not be source of truth.
- Secret Manager containers are Terraform-managed, while secret values are usually out-of-band.

## Documentation Update Guidance

- Update docs when lifecycle commands, default names, state backend, namespaces, or source-of-truth boundaries change.
- Prefer concise command blocks and explicit working directories.
- Note destructive or secret-handling caveats near the commands they affect.
- Avoid documenting secrets or private tokens.
- If app behavior changes, update the relevant app README and not only top-level docs.

## Useful Questions To Answer With This Skill

- Where is the GKE cluster defined?
- Which resources are Terraform-managed versus Helm-managed?
- How do I reproduce or tear down the stack?
- What app owns a given service or ingress?
- Which docs should be updated after a change?

## References

- `README.md`
- `docs/README.md`
- `docs/inventory.md`
- `docs/deploy-and-operations.md`
- `REPO_ARCHITECTURE.md`
- `apps/README.md`
- `iac/README.md`
