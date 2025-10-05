# secrets.tf

resource "google_project_service" "secretmanager" {
  project = var.project_id
  service = "secretmanager.googleapis.com"
}

# Create the secret "container" in Secret Manager for each entry in the map.
resource "google_secret_manager_secret" "secrets" {
  for_each  = var.custom_cluster_secrets
  project   = var.project_id
  secret_id = each.key # Use the map key as the secret name

  replication {
    auto {}
  }

  labels = {
    "environment" = var.environment
  }

  depends_on = [
    google_project_service.secretmanager
  ]
}

