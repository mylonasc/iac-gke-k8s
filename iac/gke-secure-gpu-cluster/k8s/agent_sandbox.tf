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

  warm_pool_template_name = var.enable_agent_sandbox_pydata_template ? "python-runtime-template-pydata" : "python-runtime-template"
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

resource "kubernetes_service_account" "sandbox_runtime" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime ? 1 : 0

  metadata {
    name      = "sandbox-runtime-ksa"
    namespace = local.ns
  }

  automount_service_account_token = false

  depends_on = [
    kubernetes_namespace.app,
  ]
}

resource "kubernetes_manifest" "agent_sandbox_template" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime ? 1 : 0

  field_manager {
    force_conflicts = true
  }

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
            sandbox                = "python-sandbox-example"
            sandbox-network-access = "internet"
          }
        }
        spec = {
          serviceAccountName           = "sandbox-runtime-ksa"
          automountServiceAccountToken = false
          runtimeClassName             = "gvisor"
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
              securityContext = {
                capabilities = {
                  drop = ["NET_RAW"]
                }
              }
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
                initialDelaySeconds = 10
                periodSeconds       = 2
                timeoutSeconds      = 5
                failureThreshold    = 30
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
    kubernetes_service_account.sandbox_runtime,
  ]
}

resource "kubernetes_manifest" "agent_sandbox_template_small" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime ? 1 : 0

  field_manager {
    force_conflicts = true
  }

  manifest = {
    apiVersion = "extensions.agents.x-k8s.io/v1alpha1"
    kind       = "SandboxTemplate"
    metadata = {
      name      = "python-runtime-template-small"
      namespace = local.ns
    }
    spec = {
      podTemplate = {
        metadata = {
          labels = {
            sandbox                = "python-sandbox-small"
            sandbox-network-access = "internet"
          }
        }
        spec = {
          serviceAccountName           = "sandbox-runtime-ksa"
          automountServiceAccountToken = false
          runtimeClassName             = "gvisor"
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
              securityContext = {
                capabilities = {
                  drop = ["NET_RAW"]
                }
              }
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
                initialDelaySeconds = 10
                periodSeconds       = 2
                timeoutSeconds      = 5
                failureThreshold    = 30
              }
              resources = {
                requests = {
                  cpu               = "150m"
                  memory            = "256Mi"
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
    kubernetes_service_account.sandbox_runtime,
  ]
}

resource "kubernetes_manifest" "agent_sandbox_template_large" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime ? 1 : 0

  field_manager {
    force_conflicts = true
  }

  manifest = {
    apiVersion = "extensions.agents.x-k8s.io/v1alpha1"
    kind       = "SandboxTemplate"
    metadata = {
      name      = "python-runtime-template-large"
      namespace = local.ns
    }
    spec = {
      podTemplate = {
        metadata = {
          labels = {
            sandbox                = "python-sandbox-large"
            sandbox-network-access = "internet"
          }
        }
        spec = {
          serviceAccountName           = "sandbox-runtime-ksa"
          automountServiceAccountToken = false
          runtimeClassName             = "gvisor"
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
              securityContext = {
                capabilities = {
                  drop = ["NET_RAW"]
                }
              }
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
                initialDelaySeconds = 10
                periodSeconds       = 2
                timeoutSeconds      = 5
                failureThreshold    = 30
              }
              resources = {
                requests = {
                  cpu               = "500m"
                  memory            = "1Gi"
                  ephemeral-storage = "1Gi"
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
    kubernetes_service_account.sandbox_runtime,
  ]
}

resource "kubernetes_manifest" "agent_sandbox_template_pydata" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime && var.enable_agent_sandbox_pydata_template ? 1 : 0

  field_manager {
    force_conflicts = true
  }

  manifest = {
    apiVersion = "extensions.agents.x-k8s.io/v1alpha1"
    kind       = "SandboxTemplate"
    metadata = {
      name      = "python-runtime-template-pydata"
      namespace = local.ns
    }
    spec = {
      podTemplate = {
        metadata = {
          labels = {
            sandbox                = "python-sandbox-pydata"
            sandbox-network-access = "internet"
          }
        }
        spec = {
          serviceAccountName           = "sandbox-runtime-ksa"
          automountServiceAccountToken = false
          runtimeClassName             = "gvisor"
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
          imagePullSecrets = [
            {
              name = "dockerhub-regcred"
            }
          ]
          containers = [
            {
              name  = "python-runtime"
              image = var.agent_sandbox_runtime_image_pydata
              securityContext = {
                capabilities = {
                  drop = ["NET_RAW"]
                }
              }
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
                initialDelaySeconds = 10
                periodSeconds       = 2
                timeoutSeconds      = 5
                failureThreshold    = 30
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
    kubernetes_service_account.sandbox_runtime,
  ]
}

resource "kubernetes_manifest" "agent_sandbox_warm_pool" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime ? 1 : 0

  # Keep runtime scaling flexible: allow controllers/UI to own live replica count
  # without causing Terraform field-manager conflicts.
  computed_fields = [
    "spec.replicas",
  ]

  field_manager {
    force_conflicts = true
  }

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
        name = local.warm_pool_template_name
      }
    }
  }

  depends_on = [
    kubernetes_manifest.agent_sandbox_template,
  ]
}

resource "kubernetes_manifest" "agent_sandbox_runtime_egress_policy" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime ? 1 : 0

  field_manager {
    force_conflicts = true
  }

  manifest = {
    apiVersion = "networking.k8s.io/v1"
    kind       = "NetworkPolicy"
    metadata = {
      name      = "sandbox-runtime-allow-internet-egress"
      namespace = local.ns
    }
    spec = {
      podSelector = {
        matchExpressions = [
          {
            key      = "agents.x-k8s.io/sandbox-template-ref-hash"
            operator = "Exists"
          }
        ]
      }
      policyTypes = ["Egress"]
      egress = [
        {
          to = [
            {
              namespaceSelector = {
                matchLabels = {
                  "kubernetes.io/metadata.name" = "kube-system"
                }
              }
              podSelector = {
                matchLabels = {
                  "k8s-app" = "kube-dns"
                }
              }
            }
          ]
          ports = [
            {
              protocol = "UDP"
              port     = 53
            },
            {
              protocol = "TCP"
              port     = 53
            }
          ]
        },
        {
          to = [
            {
              ipBlock = {
                cidr = "0.0.0.0/0"
                except = [
                  "10.0.0.0/8",
                  "100.64.0.0/10",
                  "127.0.0.0/8",
                  "169.254.0.0/16",
                  "172.16.0.0/12",
                  "192.168.0.0/16",
                  "34.118.224.0/20",
                ]
              }
            }
          ]
        }
      ]
    }
  }

  depends_on = [
    kubernetes_manifest.agent_sandbox_template,
    kubernetes_manifest.agent_sandbox_template_small,
    kubernetes_manifest.agent_sandbox_template_large,
    kubernetes_manifest.agent_sandbox_template_pydata,
  ]
}

resource "kubernetes_manifest" "agent_sandbox_router_service" {
  count = var.enable_agent_sandbox && var.enable_agent_sandbox_runtime ? 1 : 0

  field_manager {
    force_conflicts = true
  }

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

  # Keep live ops tuning outside Terraform ownership to avoid conflicts with
  # kubectl edits or automation that adjusts router scaling/resources.
  computed_fields = [
    "spec.replicas",
    "spec.template.spec.containers[0].resources",
    "spec.template.spec.containers[0].resources.requests",
    "spec.template.spec.containers[0].resources.limits",
  ]

  field_manager {
    force_conflicts = true
  }

  manifest = {
    apiVersion = "apps/v1"
    kind       = "Deployment"
    metadata = {
      name      = "sandbox-router-deployment"
      namespace = local.ns
    }
    spec = {
      replicas = var.agent_sandbox_router_replicas
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
