variable "project_id" {
  description = "GCP project id"
  type        = string
}

variable "region" {
  description = "GCP region or zone where the cluster is located (matches the cluster data source)."
  type        = string
}

variable "cluster_name" {
  description = "The name of the GKE cluster to target"
  type        = string
}

variable "k8s_namespace" {
  description = "Namespace to create/manage in the cluster"
  type        = string
}

variable "environment" {
  description = "Environment label for k8s resources"
  type        = string
  default     = "production"
}

variable "create_docker_registry_secret" {
  description = "When true, create the docker registry k8s secret from the provided base64-encoded dockerconfigjson. If false, skip creation so secrets can be provisioned post-hoc."
  type        = bool
  default     = false
}

variable "dockerconfig_secret_data_b64" {
  description = "Base64-encoded dockerconfigjson payload for the kubernetes docker pull secret. Leave empty when `create_docker_registry_secret` is false and create versions post-hoc in Secret Manager or manually."
  type        = string
  default     = ""
}

variable "docker_registry_secret_name" {
  description = "Name for the kubernetes docker registry secret to create"
  type        = string
  default     = "dockerhub-pull-secret"
}

variable "enable_agent_sandbox" {
  description = "When true, install and manage Agent Sandbox resources via Terraform."
  type        = bool
  default     = true
}

variable "agent_sandbox_version" {
  description = "Agent Sandbox release version used for controller/CRD manifests."
  type        = string
  default     = "v0.1.0"
}

variable "agent_sandbox_runtime_image" {
  description = "Container image for sandbox runtime pods."
  type        = string
}

variable "agent_sandbox_router_image" {
  description = "Container image for sandbox router pods."
  type        = string
}

variable "agent_sandbox_warm_pool_replicas" {
  description = "Number of pre-warmed sandbox pods to maintain."
  type        = number
  default     = 2
}

variable "enable_agent_sandbox_runtime" {
  description = "When true, create Agent Sandbox runtime resources after CRDs are available."
  type        = bool
  default     = false
}
