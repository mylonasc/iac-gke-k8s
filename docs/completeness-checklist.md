# Documentation Completeness Checklist

This checklist is tailored to this repository and to the currently deployed Terraform-managed GKE cluster.

## 1) Scope and ownership

- [x] Primary IaC entry point documented (`iac/gke-secure-gpu-cluster`).
- [x] Terraform state backend location documented (`iac/gke-secure-gpu-cluster/europe_backend.tf`).
- [x] Management boundary documented (GCP infra in root module, K8s resources in `module.k8s`).
- [ ] Explicit owner/on-call contacts documented per area (cluster, networking, IAM, app runtime).

## 2) Deployed inventory

- [x] Cluster-level inventory exists (`docs/inventory.md`).
- [x] Node pool intent and scheduling model documented.
- [x] Secret and identity model documented (Workload Identity + Secret Manager).
- [x] Runtime components documented (Agent Sandbox controller/runtime, namespace and service account).
- [ ] External dependencies mapped with account ownership (DNS provider, OAuth IdP, container registry).

## 3) Deployment workflow

- [x] Two-stage apply workflow documented with rationale.
- [x] Scripted deploy flow documented (`deploy_with_secrets.sh`).
- [x] Secret upload flow documented with safe defaults.
- [x] Post-deploy verification steps documented.
- [ ] Rollback playbook with explicit decision points and expected blast radius.

## 4) Day-2 operations

- [x] Diagnostics collection guide exists.
- [x] Runbooks exist for common incidents (`docs/runbooks/*`).
- [x] Drift detection workflow documented.
- [ ] Upgrade policy documented (Kubernetes version, provider version, node image cadence).

## 5) Security and compliance posture

- [x] Secret handling guidance present (avoid logging plaintext secrets).
- [x] Workload Identity mapping documented.
- [ ] IAM role matrix documented by principal and purpose.
- [ ] Sensitive data retention policy documented for diagnostics bundles.

## 6) Cost and capacity controls

- [x] Spot usage and scale-to-zero pools documented.
- [x] Manual GPU quota prerequisite documented.
- [ ] Budget alerts and cost ownership explicitly documented.

## 7) Links and discoverability

- [x] Central links page exists (`docs/links.md`).
- [x] Root README points to active docs.
- [x] Stale docs moved to archive or replaced with active pointers.

## 8) Intentionally skipped

- `docs/monitoring.md` is intentionally skipped per current project request.
