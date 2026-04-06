resource "google_storage_bucket" "sandbox_workspace" {
  count    = var.enable_sandbox_workspace_bucket ? 1 : 0
  provider = google-beta

  name                        = var.sandbox_workspace_bucket_name
  location                    = var.sandbox_workspace_bucket_location
  storage_class               = var.sandbox_workspace_bucket_storage_class
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  hierarchical_namespace {
    enabled = true
  }

  depends_on = [
    google_project_service.storage_api,
  ]
}
