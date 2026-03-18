# PyData Sandbox Template Image

This image extends the default Agent Sandbox runtime image with a larger
scientific/data stack for advanced tasks.

Included additions:

- `numpy`
- `scipy`
- `pandas`
- `matplotlib`
- `seaborn`
- `polars`
- `yfinance`
- `sqlite3` CLI package
- `curl`

The image is intentionally not the default runtime template.

## Build locally

From repository root:

```bash
docker build \
  -t local/pydata-sandbox-template:dev \
  apps/sandboxed-react-agent/pydata-sandbox-template
```

## Push example

```bash
docker tag local/pydata-sandbox-template:dev docker.io/<docker-user>/<repo>:python-runtime-sandbox-pydata-0.1.0
docker push docker.io/<docker-user>/<repo>:python-runtime-sandbox-pydata-0.1.0
```

## Wire into Terraform

Set in `iac/gke-secure-gpu-cluster/terraform.v3.tfvars`:

```hcl
enable_agent_sandbox_pydata_template = true
agent_sandbox_runtime_image_pydata   = "docker.io/<docker-user>/<repo>:python-runtime-sandbox-pydata-0.1.0"
```

Then apply module `k8s`.

If your image is private, keep `dockerhub-regcred` in namespace `alt-default`
so `python-runtime-template-pydata` can pull it.

Resulting optional template name in-cluster:

- `python-runtime-template-pydata`

Keep `python-runtime-template` as default; switch to pydata template only when needed.
