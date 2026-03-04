# Runbook: Cluster API Unreachable

## Symptoms

- `kubectl` commands time out or return auth/context errors.
- Terraform `module.k8s` operations fail while GCP resources succeed.

## Immediate checks

```bash
kubectl config current-context
gcloud auth list
gcloud container clusters get-credentials <cluster> --region <region-or-zone> --project <project-id>
kubectl version
```

## Triage steps

1. Confirm cluster still exists in GCP console and is in `RUNNING` state.
2. Validate the active project and account in `gcloud`.
3. Re-fetch credentials and retry read-only `kubectl get nodes`.
4. If Terraform is failing in `module.k8s`, run Phase A only, wait for control plane health, then rerun Phase B.

## Resolution

- Fix auth/context mismatch.
- Wait for control plane recovery if cluster is upgrading or reconciling.
- Re-run deploy script after control plane and at least one node are ready.

## Escalation data to collect

- `kubectl version` output
- `gcloud container clusters describe <cluster> ...`
- Recent `terraform apply` error output from `module.k8s`
