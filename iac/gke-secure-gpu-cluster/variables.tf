variable "project_id" {
  description = "The Google Cloud project ID."
  type        = string
}

variable "region" {
  description = "The GCP region to deploy the GKE cluster in."
  type        = string
  default     = "europe-west4-a"
}

variable "cluster_name" {
  description = "The name for the GKE cluster."
  type        = string
  default     = "gpu-spot-cluster"
}

variable "gpu_machine_type_ng_a" {
  description = "The machine type for the GPU nodes (e.g., n1-standard-1, a2-highgpu-1g)."
  type        = string
  default     = "g2-standard-4"
}

variable "gpu_machine_type_ng_b" {
  description = "The machine type for the GPU nodes (e.g., n1-standard-1, a2-highgpu-1g)."
  type        = string
  default     = "n1-standard-1"
}

variable "gpu_type_ng_a" {
  description = "The type of GPU to attach (e.g., nvidia-tesla-t4, nvidia-tesla-v100)."
  type        = string
  default     = "nvidia-tesla-l4"
}

variable "gpu_type_ng_b" {
  description = "The type of GPU to attach (e.g., nvidia-tesla-t4, nvidia-tesla-v100)."
  type        = string
  default     = "nvidia-tesla-t4"
}

variable "gpu_count" {
  description = "The number of GPUs to attach to each node."
  type        = number
  default     = 1
}

variable "primary_is_spot" {
  description = "This controls whether the primary node pool is going to consist of spot machines (for cost savings)"
  type        = bool
  default     = true
}

variable "cluster_deletion_protection" {
  description = "Protects the cluster from accidental deletion (i.e., does not allow terraform to delete the cluster during destroy)"
  type = bool
  default = false
}

variable "environment" {
  description = "A variable labeling the secret manager's secret."
  type = string
  default = "production"
}

# Additional configuration for k8s, applied after creation:
variable "k8s_namespace" {
  description = "An additional namespace created (and given access to the configured secret)"
  type = string
  default = "alt-default"
}
