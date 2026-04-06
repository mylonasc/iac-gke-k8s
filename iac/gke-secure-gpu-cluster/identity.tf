
# 1. Google Service Account (GSA) for your app
resource "google_service_account" "default_gsa" {
  project      = var.project_id
  account_id   = "default-service-account"
  display_name = "The Default Service Account for managing the deployment."
}

resource "google_service_account" "backend_admin_gsa" {
  project      = var.project_id
  account_id   = var.backend_admin_gsa_account_id
  display_name = "Backend admin service account for sandbox workspace provisioning."
}

# The variable containing the secrets and their descriptions is app_secrets

# 2. Grant the GSA permission to access all the secrets in custom_cluster_secrets
resource "google_secret_manager_secret_iam_member" "secret_accessor" {
  for_each  = var.custom_cluster_secrets
  project   = google_secret_manager_secret.secrets[each.key].project # the custom_cluster_secrets[each.key] from secrets.tf
  secret_id = google_secret_manager_secret.secrets[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.default_gsa.email}"
}

resource "google_secret_manager_secret_iam_member" "backend_admin_secret_accessor" {
  for_each  = var.custom_cluster_secrets
  project   = google_secret_manager_secret.secrets[each.key].project
  secret_id = google_secret_manager_secret.secrets[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend_admin_gsa.email}"
}

# 3. Allow the Kubernetes Service Account to impersonate the Google Service Account
resource "google_service_account_iam_member" "workload_identity_user" {
  service_account_id = google_service_account.default_gsa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.k8s_namespace}/default-ksa]" # Replace project, namespace, and ksa name
}

resource "google_service_account_iam_member" "backend_admin_workload_identity_user" {
  service_account_id = google_service_account.backend_admin_gsa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.k8s_namespace}/${var.backend_admin_ksa_name}]"
}

resource "google_project_iam_member" "backend_admin_service_account_admin" {
  project = var.project_id
  role    = "roles/iam.serviceAccountAdmin"
  member  = "serviceAccount:${google_service_account.backend_admin_gsa.email}"
}

resource "google_storage_bucket_iam_member" "backend_admin_workspace_storage_admin" {
  count  = var.enable_sandbox_workspace_bucket ? 1 : 0
  bucket = google_storage_bucket.sandbox_workspace[0].name
  role   = "roles/storage.admin"
  member = "serviceAccount:${google_service_account.backend_admin_gsa.email}"
}
