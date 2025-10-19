locals {
  ns = var.k8s_namespace
}

resource "kubernetes_namespace" "app" {
  metadata {
    name = local.ns
    labels = {
      environment = var.environment
    }
  }
}
// Optionally create the docker registry secret when an encoded payload is provided.
// This allows creating the cluster without requiring secret payloads to exist.
resource "kubernetes_secret" "docker_registry_secret" {
  count = var.create_docker_registry_secret && length(var.dockerconfig_secret_data_b64) > 0 ? 1 : 0

  metadata {
    name      = var.docker_registry_secret_name
    namespace = kubernetes_namespace.app.metadata[0].name
  }

  type = "kubernetes.io/dockerconfigjson"

  data = {
    ".dockerconfigjson" = base64decode(var.dockerconfig_secret_data_b64)
  }

  depends_on = [
    kubernetes_namespace.app
  ]
}

resource "kubernetes_service_account" "default_ksa" {
  metadata {
    name      = "default-ksa"
    namespace = kubernetes_namespace.app.metadata[0].name
    annotations = {
      "iam.gke.io/gcp-service-account" = "default-service-account@${var.project_id}.iam.gserviceaccount.com"
    }
  }
}
