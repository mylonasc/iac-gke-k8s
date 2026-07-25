Diagrams
========

Reviewed at: 2026-07-25 11:07:04 UTC

This page stores PlantUML diagrams rendered by ``sphinxcontrib-plantuml`` during
the Sphinx build. The build environment must provide a ``plantuml`` executable on
``PATH``.

Platform Context
----------------

.. uml::
   :caption: iac-gke-k8s Platform Context

   @startuml
   title iac-gke-k8s Platform Context
   skinparam componentStyle rectangle

   actor "Infrastructure Engineer" as Infra
   actor "Cluster Admin" as Admin
   actor "Developer" as Dev

   rectangle "Repository" as Repo {
     component "Terraform root\niac/gke-secure-gpu-cluster" as TFRoot
     component "Kubernetes module\niac/gke-secure-gpu-cluster/k8s" as TFK8s
     component "App-owned releases\nHelm/manifests/scripts" as Apps
   }

   cloud "Google Cloud" as GCP {
     component "GKE Standard cluster" as GKE
     database "Secret Manager\ncontainers" as GSM
     database "GCS workspace bucket" as GCS
     component "IAM / Workload Identity" as IAM
   }

   node "Kubernetes cluster" as K8S {
     component "Agent Sandbox\ncontroller + CRDs" as AS
     component "Sandbox router" as Router
     component "Base namespace\nalt-default" as NS
   }

   Infra --> TFRoot
   Admin --> K8S
   Dev --> Apps
   TFRoot --> GKE
   TFRoot --> GSM
   TFRoot --> GCS
   TFRoot --> IAM
   TFRoot --> TFK8s
   TFK8s --> AS
   TFK8s --> Router
   TFK8s --> NS
   Apps --> NS
   AS --> Router
   @enduml

Terraform Apply Sequence
------------------------

.. uml::
   :caption: Two-Stage Terraform Apply

   @startuml
   title Two-Stage Terraform Apply
   actor Operator
   participant "Terraform root" as Root
   participant "Google Cloud APIs" as GCP
   participant "GKE API" as GKE
   participant "Kubernetes module" as K8s

   Operator -> Root: terraform init / plan
   Operator -> Root: Phase A apply
   Root -> GCP: enable APIs, IAM, secrets, storage
   Root -> GCP: create GKE cluster and node pools
   Operator -> GKE: refresh kubeconfig and verify readiness
   Operator -> Root: Phase B apply target=module.k8s
   Root -> K8s: configure provider from live cluster
   K8s -> GKE: namespace, KSAs, Agent Sandbox, router
   Operator -> GKE: verify nodes, pods, templates, router
   @enduml

Node Pool Scheduling View
-------------------------

.. uml::
   :caption: Node Pool Scheduling Model

   @startuml
   title Node Pool Scheduling Model
   skinparam componentStyle rectangle

   rectangle "GKE Cluster" {
     node "primary-nodes\ne2-standard-2" as Primary
     node "general-purpose-pool\ne2-medium\ntaint purpose=general-apps" as General
     node "general-purpose-pool-small\ne2-small spot\ntaint purpose=general-apps-small" as Small
     node "gpu-spot-pool-a\nL4" as L4
     node "gpu-spot-pool-b\nT4" as T4
     node "gvisor-sandbox-pool\nruntime gvisor\ntaint sandbox.gke.io/runtime=gvisor" as Gvisor
   }

   component "System/platform pods" as System
   component "General app pods" as Apps
   component "GPU inference pods" as GPU
   component "Sandbox runtime pods" as Runtime
   component "Sandbox router" as Router

   System --> Primary
   Apps --> General
   Apps --> Small
   GPU --> L4
   GPU --> T4
   Runtime --> Gvisor
   Router --> Primary
   Router --> General
   @enduml

Agent Sandbox Runtime Flow
--------------------------

.. uml::
   :caption: Agent Sandbox Runtime Flow

   @startuml
   title Agent Sandbox Runtime Flow
   actor "Client/backend" as Client
   participant "Kubernetes API" as API
   participant "Agent Sandbox controller" as Controller
   participant "Sandbox router service" as Router
   participant "gVisor sandbox runtime pod" as Runtime

   Client -> API: create SandboxClaim
   API -> Controller: reconcile claim
   Controller -> API: create/bind Sandbox
   Controller -> Runtime: schedule pod from SandboxTemplate
   Runtime --> Controller: ready
   Client -> Router: execution/file request with sandbox routing headers
   Router -> Runtime: forward request
   Runtime --> Router: result
   Router --> Client: result
   @enduml
