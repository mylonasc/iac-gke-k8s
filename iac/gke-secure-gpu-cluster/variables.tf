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
  type        = bool
  default     = false
}

variable "environment" {
  description = "A variable labeling the secret manager's secret."
  type        = string
  default     = "production"
}

variable "custom_cluster_secrets" {
  type = map(string)
  default = {
    "dockerhub-ro-pat" = "A personal access token giving read-only access to the private dockerhub repo."
    "openai-api-key"   = "OpenAI API Key for accessing the external resource."
  }
}

# Additional configuration for k8s, applied after creation:
variable "k8s_namespace" {
  description = "An additional namespace created (and given access to the configured secret)"
  type        = string
  default     = "alt-default"
}

variable "enable_gvisor_pool" {
  description = "When true, creates a dedicated node pool for gVisor-sandboxed workloads."
  type        = bool
  default     = true
}

variable "gvisor_pool_machine_type" {
  description = "Machine type for the gVisor node pool."
  type        = string
  default     = "e2-medium"
}

variable "gvisor_pool_min_nodes" {
  description = "Minimum node count for the gVisor node pool autoscaler."
  type        = number
  default     = 0
}

variable "gvisor_pool_max_nodes" {
  description = "Maximum node count for the gVisor node pool autoscaler."
  type        = number
  default     = 5
}

variable "gvisor_pool_is_spot" {
  description = "Whether gVisor node pool nodes should use Spot VMs."
  type        = bool
  default     = true
}

variable "enable_agent_sandbox" {
  description = "When true, installs and manages Agent Sandbox resources in the cluster via Terraform."
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
  default     = "us-central1-docker.pkg.dev/k8s-staging-images/agent-sandbox/python-runtime-sandbox:latest-main"
}

variable "agent_sandbox_runtime_image_pydata" {
  description = "Container image for pydata-enabled sandbox runtime pods."
  type        = string
  default     = "us-central1-docker.pkg.dev/k8s-staging-images/agent-sandbox/python-runtime-sandbox-pydata:latest-main"
}

variable "agent_sandbox_router_image" {
  description = "Container image for sandbox router pods."
  type        = string
  default     = "us-central1-docker.pkg.dev/k8s-staging-images/agent-sandbox/sandbox-router:latest-main"
}

variable "agent_sandbox_warm_pool_replicas" {
  description = "Number of pre-warmed sandbox pods to keep available."
  type        = number
  default     = 2
}

variable "agent_sandbox_router_replicas" {
  description = "Number of sandbox router pod replicas to keep available."
  type        = number
  default     = 2
}

variable "enable_agent_sandbox_runtime" {
  description = "When true, manages Agent Sandbox runtime resources (SandboxTemplate, warm pool, router). Keep false for the first apply so CRDs are installed first."
  type        = bool
  default     = false
}

variable "enable_agent_sandbox_pydata_template" {
  description = "When true, creates an additional opt-in pydata SandboxTemplate."
  type        = bool
  default     = true
}
