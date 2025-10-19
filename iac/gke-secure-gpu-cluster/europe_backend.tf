terraform {
  backend "gcs" {
    bucket  = "gcp-ops-data-tfstate-europe"
    prefix  = "terraform/state"
  }
}
