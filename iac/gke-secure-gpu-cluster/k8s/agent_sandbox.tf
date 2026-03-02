terraform {
  required_providers {
    google = {
      source = "hashicorp/google"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.0"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.4"
    }
  }
}

data "http" "agent_sandbox_manifest" {
  count = var.enable_agent_sandbox ? 1 : 0
  url   = "https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${var.agent_sandbox_version}/manifest.yaml"
}

data "http" "agent_sandbox_extensions" {
  count = var.enable_agent_sandbox ? 1 : 0
  url   = "https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${var.agent_sandbox_version}/extensions.yaml"
}

locals {
  agent_sandbox_manifest_docs = var.enable_agent_sandbox ? [
    for d in split("\n---", data.http.agent_sandbox_manifest[0].response_body) : trimspace(d)
    if can(regex("apiVersion:", d))
  ] : []

  agent_sandbox_extensions_docs = var.enable_agent_sandbox ? [
    for d in split("\n---", data.http.agent_sandbox_extensions[0].response_body) : trimspace(d)
    if can(regex("apiVersion:", d))
  ] : []

  agent_sandbox_manifest_objects = {
    for obj in [for d in local.agent_sandbox_manifest_docs : yamldecode(d)] :
    "${lower(obj.kind)}-${lookup(lookup(obj, "metadata", {}), "namespace", "cluster")}-${obj.metadata.name}" => obj
    if lower(obj.kind) != "statefulset"
  }

  agent_sandbox_extensions_objects = {
    for obj in [for d in local.agent_sandbox_extensions_docs : yamldecode(d)] :
    "${lower(obj.kind)}-${lookup(lookup(obj, "metadata", {}), "namespace", "cluster")}-${obj.metadata.name}" => obj
  }
}

resource "kubernetes_manifest" "agent_sandbox_install" {
  for_each = var.enable_agent_sandbox ? {
    for k, v in local.agent_sandbox_manifest_objects : k => jsonencode(v)
  } : {}

  manifest = jsondecode(each.value)
}

resource "kubernetes_manifest" "agent_sandbox_extensions" {
  for_each = var.enable_agent_sandbox ? {
    for k, v in local.agent_sandbox_extensions_objects : k => jsonencode(v)
  } : {}

  manifest = jsondecode(each.value)

  depends_on = [
    kubernetes_manifest.agent_sandbox_install,
  ]
}

resource "kubernetes_manifest" "agent_sandbox_template" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime ? 1 : 0

  manifest = {
    apiVersion = "extensions.agents.x-k8s.io/v1alpha1"
    kind       = "SandboxTemplate"
    metadata = {
      name      = "python-runtime-template"
      namespace = local.ns
    }
    spec = {
      podTemplate = {
        metadata = {
          labels = {
            sandbox = "python-sandbox-example"
          }
        }
        spec = {
          runtimeClassName = "gvisor"
          nodeSelector = {
            "workload-isolation" = "gvisor"
          }
          tolerations = [
            {
              key      = "sandbox.gke.io/runtime"
              operator = "Equal"
              value    = "gvisor"
              effect   = "NoSchedule"
            }
          ]
          containers = [
            {
              name  = "python-runtime"
              image = var.agent_sandbox_runtime_image
              ports = [
                {
                  containerPort = 8888
                }
              ]
              readinessProbe = {
                httpGet = {
                  path = "/"
                  port = 8888
                }
                initialDelaySeconds = 0
                periodSeconds       = 1
              }
              resources = {
                requests = {
                  cpu               = "250m"
                  memory            = "512Mi"
                  ephemeral-storage = "512Mi"
                }
              }
            }
          ]
          restartPolicy = "OnFailure"
        }
      }
    }
  }

  depends_on = [
    kubernetes_namespace.app,
    kubernetes_manifest.agent_sandbox_extensions,
  ]
}

resource "kubernetes_manifest" "agent_sandbox_warm_pool" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime ? 1 : 0

  manifest = {
    apiVersion = "extensions.agents.x-k8s.io/v1alpha1"
    kind       = "SandboxWarmPool"
    metadata = {
      name      = "python-sandbox-warmpool"
      namespace = local.ns
    }
    spec = {
      replicas = var.agent_sandbox_warm_pool_replicas
      sandboxTemplateRef = {
        name = "python-runtime-template"
      }
    }
  }

  depends_on = [
    kubernetes_manifest.agent_sandbox_template,
  ]
}

resource "kubernetes_manifest" "agent_sandbox_router_service" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime ? 1 : 0

  manifest = {
    apiVersion = "v1"
    kind       = "Service"
    metadata = {
      name      = "sandbox-router-svc"
      namespace = local.ns
    }
    spec = {
      type = "ClusterIP"
      selector = {
        app = "sandbox-router"
      }
      ports = [
        {
          name       = "http"
          protocol   = "TCP"
          port       = 8080
          targetPort = 8080
        }
      ]
    }
  }

  depends_on = [
    kubernetes_namespace.app,
  ]
}

resource "kubernetes_manifest" "agent_sandbox_router_deployment" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime ? 1 : 0

  manifest = {
    apiVersion = "apps/v1"
    kind       = "Deployment"
    metadata = {
      name      = "sandbox-router-deployment"
      namespace = local.ns
    }
    spec = {
      replicas = 2
      selector = {
        matchLabels = {
          app = "sandbox-router"
        }
      }
      template = {
        metadata = {
          labels = {
            app = "sandbox-router"
          }
        }
        spec = {
          nodeSelector = {
            "workload-isolation" = "gvisor"
          }
          tolerations = [
            {
              key      = "sandbox.gke.io/runtime"
              operator = "Equal"
              value    = "gvisor"
              effect   = "NoSchedule"
            }
          ]
          topologySpreadConstraints = [
            {
              maxSkew           = 1
              topologyKey       = "topology.kubernetes.io/zone"
              whenUnsatisfiable = "ScheduleAnyway"
              labelSelector = {
                matchLabels = {
                  app = "sandbox-router"
                }
              }
            }
          ]
          containers = [
            {
              name  = "router"
              image = var.agent_sandbox_router_image
              ports = [
                {
                  containerPort = 8080
                }
              ]
              readinessProbe = {
                httpGet = {
                  path = "/healthz"
                  port = 8080
                }
                initialDelaySeconds = 5
                periodSeconds       = 5
              }
              livenessProbe = {
                httpGet = {
                  path = "/healthz"
                  port = 8080
                }
                initialDelaySeconds = 10
                periodSeconds       = 10
              }
              resources = {
                requests = {
                  cpu    = "250m"
                  memory = "512Mi"
                }
                limits = {
                  cpu    = "1"
                  memory = "1Gi"
                }
              }
            }
          ]
          securityContext = {
            runAsUser  = 1000
            runAsGroup = 1000
          }
        }
      }
    }
  }

  depends_on = [
    kubernetes_manifest.agent_sandbox_router_service,
    kubernetes_manifest.agent_sandbox_extensions,
  ]
}
