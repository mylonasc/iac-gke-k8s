---
name: release-build-images
description: Use when building images, pushing DockerHub images, bumping Helm values, checking versions, or doing Janet release operations.
---

# Release Build Images

Use this skill for image build/push workflows, release helpers, DockerHub version checks, Helm image tag bumps, and Janet deployment updates.

## Main App Release Area

- App root: `apps/janet`
- Image repo in Helm values: `docker.io/mylonasc/magarathea`
- Backend values: `apps/janet/helm/backend/values.yaml`
- Frontend values: `apps/janet/helm/frontend/values.yaml`

## Janet Commands

From `apps/janet`:

```bash
./ops.sh versions
./ops.sh release
./scripts/push_images.sh
./scripts/release.sh
./ops.sh update --release sandboxed-react-agent-backend --set image.tag=<tag>
./ops.sh update --release sandboxed-react-agent-frontend --set image.tag=<tag>
```

For private DockerHub repositories, version checks may require:

```bash
DOCKERHUB_TOKEN=<token> ./ops.sh versions
```

## Helm Values To Bump

- Backend image tag: `apps/janet/helm/backend/values.yaml`, key `image.tag`
- Frontend image tag: `apps/janet/helm/frontend/values.yaml`, key `image.tag`

Current tags use the pattern:

- `sandboxed-react-agent-backend-git-<sha>`
- `sandboxed-react-agent-frontend-git-<sha>`

## Related App Image Scripts

- `apps/cluster-authz-manager/push_images.sh`
- `apps/sandboxed-react-agent-authz/push_images.sh`
- `apps/telegram-service/push_images.sh`
- `apps/litellm-gateway/app_up.sh`

## Safety Notes

- Check `git status` before release or image tag edits.
- Do not overwrite unrelated Helm value changes.
- Verify image tags exist before updating a running deployment.
- Confirm `dockerhub-regcred` exists in the target namespace for private images.
- Avoid printing DockerHub tokens.
- Prefer `./ops.sh update` for a single release and `./ops.sh deploy` for full backend/frontend deploy.

## Verification

```bash
cd apps/janet
./ops.sh versions
kubectl -n alt-default get deploy sandboxed-react-agent-backend -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl -n alt-default get deploy sandboxed-react-agent-frontend -o jsonpath='{.spec.template.spec.containers[0].image}'
```

## References

- `apps/janet/ops.sh`
- `apps/janet/scripts/release.sh`
- `apps/janet/scripts/push_images.sh`
- `apps/janet/scripts/versions.sh`
- `apps/janet/scripts/update_app.sh`
- `apps/janet/helm/backend/values.yaml`
- `apps/janet/helm/frontend/values.yaml`
