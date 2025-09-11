# Configure the Google Cloud provider
provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable necessary APIs for the project
resource "google_project_service" "gke_api" {
  service = "container.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "compute_api" {
  service = "compute.googleapis.com"
  disable_on_destroy = false
}

# Define the GKE cluster
# We remove the default node pool to have full control over our custom node pools.
resource "google_container_cluster" "primary" {
  name     = var.cluster_name
  location = var.region

  # We can't create a cluster with no node pool defined, but we want to use
  # a separate 'google_container_node_pool' resource.
  # So we create the smallest possible default node pool and immediately remove it.
  remove_default_node_pool = true
  initial_node_count       = 1

  depends_on = [
    google_project_service.gke_api,
    google_project_service.compute_api
  ]
  deletion_protection = var.cluster_deletion_protection
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
}

# Standard node pool for system pods and reliability
# This follows the best practice mentioned in the documentation.
resource "google_container_node_pool" "primary_nodes" {
  name       = "primary-nodes"
  cluster    = google_container_cluster.primary.id
  location   = var.region
  node_count = 1

  # Add this autoscaling block
  autoscaling {
    min_node_count = 0
    max_node_count = 1 # Or another small number
  }

  node_config {
    machine_type = "e2-medium"
    spot = var.primary_is_spot
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }
}

# GPU node pool using Spot VMs - type 1
resource "google_container_node_pool" "gpu_spot_pool_np_a" {
  name    = "gpu-spot-pool-a"
  cluster = google_container_cluster.primary.id
  location = var.region

  autoscaling {
    min_node_count = 0
    max_node_count = 4
  }

  node_config {
    # This 'spot = true' flag is the key to using Spot VMs
    spot = true

    machine_type = var.gpu_machine_type_ng_a
    
    # Define the GPU type and count
    guest_accelerator {
      type  = var.gpu_type_ng_a
      count = var.gpu_count
    }

    # As per documentation, GKE automatically adds the nvidia.com/gpu taint.
    # We also add a taint for Spot VMs to prevent workloads from being scheduled here by default.
    taint {
      key    = "cloud.google.com/gke-spot"
      value  = "true"
      effect = "NO_SCHEDULE"
    }

    taint {
      key    = "gpu-type"
      value  = var.gpu_type_ng_a
      effect = "NO_SCHEDULE"
    }

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }

  # Ensure the standard node pool is created first
  depends_on = [
    google_container_node_pool.primary_nodes,
  ]
}

# GPU node pool using Spot VMs - type 1
resource "google_container_node_pool" "gpu_spot_pool_np_b" {
  name    = "gpu-spot-pool-b"
  cluster = google_container_cluster.primary.id
  location = var.region

  autoscaling {
    min_node_count = 0
    max_node_count = 4
  }

  node_config {
    # This 'spot = true' flag is the key to using Spot VMs
    spot = true

    machine_type = var.gpu_machine_type_ng_b
    
    # Define the GPU type and count
    guest_accelerator {
      type  = var.gpu_type_ng_b
      count = var.gpu_count
    }

    # As per documentation, GKE automatically adds the nvidia.com/gpu taint.
    # We also add a taint for Spot VMs to prevent workloads from being scheduled here by default.
    taint {
      key    = "cloud.google.com/gke-spot"
      value  = "true"
      effect = "NO_SCHEDULE"
    }
    
    taint {
      key    = "gpu-type"
      value  = var.gpu_type_ng_b
      effect = "NO_SCHEDULE"
    }

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }

  # Ensure the standard node pool is created first
  depends_on = [
    google_container_node_pool.primary_nodes,
  ]
}

# General-purpose node pool for standard workloads like web servers
resource "google_container_node_pool" "general_purpose_pool" {
  name     = "general-purpose-pool"
  cluster  = google_container_cluster.primary.id
  location = var.region

  # Configure autoscaling for cost-efficiency and performance
  autoscaling {
    min_node_count = 0
    max_node_count = 5
  }

  node_config {
    # e2-standard-4 provides 4 vCPUs and 16 GB of memory
    machine_type = "e2-standard-4"

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }

  # Ensure the standard node pool is created first for stability
  depends_on = [
    google_container_node_pool.primary_nodes,
  ]
}

##########################################################################################
#----- Resource creation with the K8S provider (for the already created K8S cluster -----#
##########################################################################################

# 1. Setting up the provider:
#
# :Note:
# Since it uses variables from the GKE cluster creation, terraform knows this depends on 
# the blocks above. Therefore there is an implicit "depends" for the blocks below to the 
# blocks above.
#

# Use a data source to get the credentials of the cluster we just created
data "google_container_cluster" "my_cluster" {
  name     = google_container_cluster.primary.name
  location = google_container_cluster.primary.location
}

# This makes the gcloud's credentials available to terraform, to 
# perform k8s configurations.
data "google_client_config" "default" {}

# Configure the Kubernetes provider to connect to your new GKE cluster
provider "kubernetes" {
  # host  = "https://iam.googleapis.com/v1/${data.google_container_cluster.my_cluster.id}"
  host  = "https://${data.google_container_cluster.my_cluster.endpoint}"

  token = data.google_client_config.default.access_token

  cluster_ca_certificate = base64decode(data.google_container_cluster.my_cluster.master_auth[0].cluster_ca_certificate)
}

# 2. Configuring a new namespace:

# Now, use the configured Kubernetes provider to create a namespace
resource "kubernetes_namespace" "app" {
  metadata {
    name = var.k8s_namespace
    labels = {
      "environment" = var.environment
    }
  }
}


