
# 1. Google Service Account (GSA) for your app
resource "google_service_account" "default_gsa" {
  project      = var.project_id
  account_id   = "default-service-account"
  display_name = "The Default Service Account for managing the deployment."
}

# 2. Grant the GSA permission to access the secret
#
# To be edited when more secrets are in-place:
resource "google_secret_manager_secret_iam_member" "secret_accessor" {
  project   = google_secret_manager_secret.example_api_key.project # "example_api_key" - to be changed"
  secret_id = google_secret_manager_secret.example_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.default_gsa.email}"
}

# 3. Allow the Kubernetes Service Account to impersonate the Google Service Account
resource "google_service_account_iam_member" "workload_identity_user" {
  service_account_id = google_service_account.default_gsa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.k8s_namespace}/default-ksa]" # Replace project, namespace, and ksa name
}

# 4. Kubernetes Service Account (KSA) for your app
# This assumes you have the Kubernetes provider configured
resource "kubernetes_service_account" "default_ksa" {
  metadata {
    name      = "default-ksa"
    namespace = var.k8s_namespace # Replace
    annotations = {
      # This annotation links the KSA to the GSA
      "iam.gke.io/gcp-service-account" = google_service_account.default_gsa.email
    }
  }
}
