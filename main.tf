# Configure the Google Cloud provider
provider "google" {
  project = var.project_id
  region  = var.region
}

# Create the GKE cluster
resource "google_container_cluster" "primary" {
  name                     = var.cluster_name
  location                 = var.region
  remove_default_node_pool = true
  initial_node_count       = 1
  network                  = "default" # Using the default VPC for simplicity

  # Enable Workload Identity for secure access to GCP services
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  deletion_protection      = false
}

# Add this new node pool for system pods
resource "google_container_node_pool" "system_pool" {
  name       = "system-pool"
  project    = var.project_id # Replace with your project ID if not inferred
  location   = var.region
  cluster    = google_container_cluster.primary.name
  node_count = 1

  node_config {
    # Use a small, cost-effective machine type
    machine_type = "e2-small"
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }
}

# Create the dedicated GPU node pool
resource "google_container_node_pool" "gpu_pool" {
  name       = "gpu-pool"
  cluster    = google_container_cluster.primary.name
  location   = var.region
  node_count = 1 # Start with one node for simplicity

  # Node configuration
  node_config {
    # We use the G2 machine type which supports L4 GPUs
    # or N1 machines that support T4, P4, V100, p100 GPUs. 
    # see https://cloud.google.com/spot-vms/pricing?hl=en for pricing info
    # machine_type = "n1-standard-4"
    machine_type = "g2-standard-4"
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]

    # This block requests the GPU
    guest_accelerator {
      type  = var.gpu_type
      count = 0
    }

    # Taint the node to ensure only GPU workloads are scheduled on it
    taint {
      key    = "nvidia.com/gpu"
      value  = "present"
      effect = "NO_SCHEDULE"
    }

    # Labels for targeting this node pool in Kubernetes
    labels = {
      "gpu-pool" = "true"
    }
  }

  # Autoscaling for the node pool
  autoscaling {
    min_node_count = 0
    max_node_count = 1
  }

  # Ensure nodes are properly managed
  management {
    auto_repair  = true
    auto_upgrade = true
  }
}
