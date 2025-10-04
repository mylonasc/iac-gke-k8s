# Save this content in a file named backend.tf
terraform {
  backend "gcs" {
    bucket  = "gcp-ops-data-tfstate"
    prefix  = "terraform/state"
  }
}
