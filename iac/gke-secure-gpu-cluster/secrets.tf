# secrets.tf

resource "google_project_service" "secretmanager" {
  project = var.project_id
  service = "secretmanager.googleapis.com"
}

# Create the secret "container" in Google Secret Manager
resource "google_secret_manager_secret" "example_api_key" {
  secret_id = "example-api-key"

  replication {
    auto {}
  }

  labels = {
    "environment" = var.environment
  }
  depends_on= [
    google_project_service.secretmanager,
  ]
}


