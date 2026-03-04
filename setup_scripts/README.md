## Setup

### Pre-deployment
Before deploying the cluster:

1. Install Terraform.
2. Enable required Google Cloud APIs (and ensure IAM permissions are in place).

This is handled by scripts in `setup_scripts/pre-gke-deploy/`.

Scripts are numbered in suggested execution order. Numbering does not always imply strict dependency.

If you are running Ubuntu 24.x (or equivalent), `02_install_terraform.sh` should work.
For other systems, follow HashiCorp's install guide:

- `https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli`

## Post-deployment (`kubectl` setup)

After deployment, set up `kubectl` and the GKE auth plugin.

See scripts in `setup_scripts/post-gke-deploy/`:

- `01_install_kubectl.sh`
- `02_install_gke_auth_plugin.sh`
- `03_configure_gke.py`
