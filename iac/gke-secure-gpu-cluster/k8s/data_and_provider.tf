data "google_client_config" "default" {}

data "google_container_cluster" "primary" {
  name     = var.cluster_name
  location = var.region
  project  = var.project_id
}

provider "kubernetes" {
  host                   = "https://${data.google_container_cluster.primary.endpoint}"
  token                  = data.google_client_config.default.access_token
  cluster_ca_certificate = base64decode(data.google_container_cluster.primary.master_auth[0].cluster_ca_certificate)
}

# Notes:
# - This module uses a data source to find an existing cluster by `var.cluster_name` and `var.region`.
# - For blue/green or multi-cluster workflows, instantiate the module multiple times with different
#   `cluster_name`/`region` values (for example: `module.k8s` and `module.k8s_new`) or change the
#   module inputs and run targeted applies. Do NOT attempt to reuse the same `module.k8s` instance to
#   operate two clusters simultaneously unless you manage distinct inputs per-instance.
