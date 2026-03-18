# LiteLLM Gateway + vLLM on GKE GPU Pools

This app provides an OpenAI-compatible in-cluster gateway using LiteLLM and sample vLLM inference deployments that run on this repo's GPU node pools.

It is designed for fast iteration:

- One gateway endpoint for both hosted providers and self-hosted vLLM models.
- Two sample vLLM deployments, one pinned to the L4 pool and one pinned to the T4 pool.
- Kubernetes-native manifests only (easy to modify, no hidden control plane).

## What is included

- `k8s/namespace.yaml`: dedicated namespace (`llm-gateway`).
- `k8s/litellm-configmap.yaml`: routing config for LiteLLM.
- `k8s/litellm-deployment.yaml`: LiteLLM deployment + env wiring.
- `k8s/litellm-service.yaml`: ClusterIP service for in-cluster access.
- `k8s/litellm-ingress.yaml`: optional external ingress path.
- `k8s/vllm-l4-deployment.yaml`: vLLM pinned to `gpu-spot-pool-a` (L4).
- `k8s/vllm-l4-service.yaml`: service for L4 vLLM.
- `k8s/vllm-t4-deployment.yaml`: vLLM pinned to `gpu-spot-pool-b` (T4).
- `k8s/vllm-t4-service.yaml`: service for T4 vLLM.
- `k8s/secrets.example.yaml`: example secret manifest (do not commit real values).
- `app_up.sh` / `app_down.sh`: convenience deploy/teardown scripts.

## Architecture

1. Client calls LiteLLM at `http://litellm-gateway.llm-gateway.svc.cluster.local:4000/v1/*`.
2. LiteLLM routes by `model` value:
   - Hosted model route: OpenAI (`OPENAI_API_KEY`).
   - Self-hosted routes: vLLM L4 / vLLM T4 service backends.
3. vLLM pods schedule on tainted GPU spot pools via `nodeSelector` + tolerations.

## Prerequisites

- GKE cluster from this repo already running.
- GPU node pools available (`gpu-spot-pool-a`, `gpu-spot-pool-b`).
- NVIDIA device plugin available on GPU nodes (GKE usually handles this in Standard GPU clusters).
- `kubectl` context set to your target cluster.

## Deploy

From repo root:

```bash
./apps/litellm-gateway/app_up.sh
```

This applies the namespace, vLLM services/deployments, LiteLLM config/deployment/service, and ingress.

## Set secrets (including Hugging Face token)

You need one Kubernetes secret named `litellm-gateway-secrets` in namespace `llm-gateway`.

Recommended (no file written with secrets):

```bash
kubectl -n llm-gateway create secret generic litellm-gateway-secrets \
  --from-literal=litellm-master-key='replace-with-strong-master-key' \
  --from-literal=openai-api-key='sk-...' \
  --from-literal=huggingface-token='hf_...' \
  --dry-run=client -o yaml | kubectl apply -f -
```

Notes:

- `huggingface-token` is used by vLLM containers as `HF_TOKEN` to pull gated/private model weights.
- If you only run public HF models, token is still recommended to avoid aggressive anonymous rate limits.
- `litellm-master-key` protects your gateway API. Keep it private.

You can also start from `k8s/secrets.example.yaml` and apply it after replacing placeholders.

## Verify rollout

```bash
kubectl -n llm-gateway get deploy,svc,pods
kubectl -n llm-gateway rollout status deploy/litellm-gateway --timeout=300s
kubectl -n llm-gateway rollout status deploy/vllm-l4 --timeout=900s
kubectl -n llm-gateway rollout status deploy/vllm-t4 --timeout=900s
```

Check GPU visibility in each vLLM pod:

```bash
kubectl -n llm-gateway exec deploy/vllm-l4 -- nvidia-smi
kubectl -n llm-gateway exec deploy/vllm-t4 -- nvidia-smi
```

## Test the gateway

Port-forward LiteLLM:

```bash
kubectl -n llm-gateway port-forward svc/litellm-gateway 4000:4000
```

In another shell, list models:

```bash
curl -sS http://127.0.0.1:4000/v1/models \
  -H "Authorization: Bearer replace-with-strong-master-key"
```

Call self-hosted vLLM route through gateway:

```bash
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer replace-with-strong-master-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2p5-1p5b-l4",
    "messages": [{"role": "user", "content": "Say hello in one short sentence."}],
    "temperature": 0.2
  }'
```

Call hosted OpenAI route through same gateway:

```bash
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer replace-with-strong-master-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini-proxy",
    "messages": [{"role": "user", "content": "Reply with OK."}]
  }'
```

## Integrating your agentic apps

Any OpenAI-compatible client can use this gateway.

- Base URL: `http://litellm-gateway.llm-gateway.svc.cluster.local:4000/v1`
- API key: `litellm-master-key`
- Model: one of the configured aliases in `k8s/litellm-configmap.yaml`

For in-cluster apps, set environment variables similar to:

```bash
OPENAI_API_KEY=<litellm-master-key>
OPENAI_BASE_URL=http://litellm-gateway.llm-gateway.svc.cluster.local:4000/v1
OPENAI_MODEL=qwen2p5-1p5b-l4
```

## Scheduling details (GPU pools)

The vLLM manifests are intentionally strict:

- `nodeSelector` pins to one node pool (`gpu-spot-pool-a` or `gpu-spot-pool-b`).
- Tolerations match repo taints:
  - `cloud.google.com/gke-spot=true:NoSchedule`
  - `gpu-type:NoSchedule` (tolerated with `Exists` to support different GPU type values)
  - `nvidia.com/gpu:NoSchedule` (Exists)
- Resource request includes `nvidia.com/gpu: 1`.

If your Terraform node pool names differ, update `nodeSelector.cloud.google.com/gke-nodepool` in the vLLM deployment manifests.

## Customizing models

Edit these fields:

- vLLM model startup args in:
  - `k8s/vllm-l4-deployment.yaml`
  - `k8s/vllm-t4-deployment.yaml`
- LiteLLM route aliases in:
  - `k8s/litellm-configmap.yaml`

Keep model names and gateway route names aligned to avoid confusion.

## Teardown

```bash
./apps/litellm-gateway/app_down.sh
```

This removes all resources in `apps/litellm-gateway/k8s`.
