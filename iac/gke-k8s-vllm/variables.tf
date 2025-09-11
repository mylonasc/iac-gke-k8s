variable "project_id" {
  description = "vllm-llama3-project"
  type        = string
}

variable "region" {
  description = "The GCP region to deploy resources."
  type        = string
  default     = "europe-west1-b"
}

variable "cluster_name" {
  description = "The name of the GKE cluster."
  type        = string
  default     = "vllm-llama3-cluster"
}

variable "gpu_type" {
  description = "The GPU type (see https://cloud.google.com/compute/docs/gpus for list)"
  type        = string
  default     = "nvidia-l4"
}
