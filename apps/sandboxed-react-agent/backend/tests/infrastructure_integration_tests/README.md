# Infrastructure Integration Tests

These tests validate the non-agentic Python-to-Kubernetes sandbox path end-to-end:

- provisioning a derived `SandboxTemplate` and service account,
- running sandbox commands through lifecycle reuse (`SandboxLifecycleService`),
- running direct cluster execution (`SandboxManager`).

They are intentionally disabled by default because they require a live cluster and
create real temporary resources.

## Run

From `apps/sandboxed-react-agent/backend`:

```bash
RUN_INFRA_INTEGRATION_TESTS=1 uv run pytest tests/infrastructure_integration_tests -q
```

Optional overrides:

- `INFRA_ITEST_NAMESPACE` (default: `alt-default`)
- `INFRA_ITEST_BASE_TEMPLATE_NAME` (default: `python-runtime-template-small`)
- `INFRA_ITEST_RUNTIME_TEMPLATE_NAME` (default: `python-runtime-template-small`)
- `INFRA_ITEST_SANDBOX_API_URL` (default: `http://127.0.0.1:18080`)
- `INFRA_ITEST_ARTIFACT_DIR` (default: `tests/infrastructure_integration_tests/artifacts`)

`INFRA_ITEST_BASE_TEMPLATE_NAME` is used for template cloning/provisioning checks.
`INFRA_ITEST_RUNTIME_TEMPLATE_NAME` is used for live execution checks and should be
a known-good runnable template in your cluster.

For local execution tests, expose the router first (example):

```bash
kubectl -n alt-default port-forward svc/sandbox-router-svc 18080:8080
```

## Diagnostics artifacts

Each test writes a JSON artifact with Kubernetes diagnostics so mount/runtime
issues can be inspected after the run.

Artifacts include:

- recent namespace `FailedMount` and `workspace-gcs-fuse` events,
- claim/sandbox objects and events (when claim is known),
- sandbox pod summary, pod events, and tail logs (when pod is discoverable).

## Safety and cleanup

- Every test run uses random resource names (`infra-itest-*`).
- Templates and service accounts are deleted in fixture teardown.
- Lifecycle-created sandbox claims are explicitly released and waited for deletion.
