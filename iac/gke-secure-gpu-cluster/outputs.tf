output "cluster_name" {
  value = google_container_cluster.primary.name
}

output "cluster_endpoint" {
  value = google_container_cluster.primary.endpoint
}

output "get_credentials_command" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.primary.name} --region ${google_container_cluster.primary.location}"
}

output "gke_project_id" {
  description = "The GCP project ID where the GKE cluster is deployed."
  value       = google_container_cluster.primary.project
}


output "deploying_account_email" {
  description = "The email address of the account that performed the Terraform deployment."
  value       = data.google_client_openid_userinfo.current.email
  sensitive   = true # Recommended: Prevents the email from showing in CLI logs
}
