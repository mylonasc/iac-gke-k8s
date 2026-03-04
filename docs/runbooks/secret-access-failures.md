# Runbook: Secret Access Failures

## Symptoms

- Application fails when reading secrets.
- Errors indicate permission denied or missing secret versions.

## Immediate checks

```bash
kubectl get sa -n alt-default default-ksa -o yaml
gcloud secrets list --project <project-id>
gcloud secrets versions list <secret-name> --project <project-id>
```

## Common causes

- Secret container exists but has no active versions.
- Workload Identity mapping is missing or wrong namespace/service account.
- IAM role `roles/secretmanager.secretAccessor` missing on target secret.
- Workload is running under a different KSA than expected.

## Triage and fix

1. Confirm KSA annotation points to `default-service-account@<project>.iam.gserviceaccount.com`.
2. Confirm IAM binding exists for each required secret.
3. Upload secret versions (manual or CI) for required keys.
4. Re-run Phase B apply for `module.k8s` if K8s-side wiring changed.

## Validation

- Restart failing workload and confirm secret fetch succeeds.
- Re-check pod logs for prior permission errors.
