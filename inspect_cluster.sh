#!/bin/bash

# --- Helper Function for Formatting ---
print_header() {
    echo -e "\n\033[1;34m================================================================================"
    echo -e "  $1"
    echo -e "================================================================================\033[0m"
}

print_subheader() {
    echo -e "\n\033[1;32m>> $1\033[0m"
}

echo "Starting GKE Cluster Inspection..."
echo "Context: $(kubectl config current-context)"

# --- 1. INFRASTRUCTURE & COMPUTE ---
print_header "1. INFRASTRUCTURE & NODE POOLS"

print_subheader "Nodes Overview (Internal IPs & OS)"
kubectl get nodes -o wide

print_subheader "Identifying Node Pools (via Labels)"
# In GKE, nodes are labeled with their pool name
kubectl get nodes -l cloud.google.com/gke-nodepool -o custom-columns=NAME:.metadata.name,NODEPOOL:.metadata.labels."cloud\.google\.com/gke-nodepool",ZONE:.metadata.labels."topology\.kubernetes\.io/zone",INSTANCE_TYPE:.metadata.labels."beta\.kubernetes\.io/instance-type"

print_subheader "Resource Capacity vs. Usage"
kubectl top nodes || echo "Metrics server still initializing..."

# --- 2. NETWORKING & ACCESS ---
print_header "2. NETWORKING & CONNECTIVITY"

print_subheader "Services (LoadBalancers & ClusterIPs)"
kubectl get svc -A

print_subheader "Ingress Resources (GCP HTTP(S) Load Balancers)"
kubectl get ingress -A

print_subheader "API Service Status"
# This shows which GKE-specific APIs (like metrics or networking) are healthy
kubectl get apiservices | grep -E 'antrea|networking.gke|monitoring.gke'

# --- 3. STORAGE & CONFIGURATION ---
print_header "3. STORAGE & EXTERNAL INTEGRATIONS"

print_subheader "Storage Classes (PD Types defined in Terraform)"
kubectl get sc

print_subheader "Secret Provider Classes (GCP Secret Manager Mapping)"
# This maps to the csi-secrets-store pods in your output
kubectl get secretproviderclasses -A

# --- 4. GKE WORKLOAD IDENTITY ---
print_header "4. IDENTITY & SECURITY"

print_subheader "Service Accounts with GCP IAM Bindings"
# This identifies which K8s accounts can act as GCP IAM roles
kubectl get sa -A -o jsonpath='{range .items[?(@.metadata.annotations.iam\.gke\.io/gcp-service-account)]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{.metadata.annotations.iam\.gke\.io/gcp-service-account}{"\n"}{end}' | column -t -s $'\t' || echo "No Workload Identity bindings found."

# --- 5. CLUSTER HEALTH & EVENTS ---
print_header "5. CLUSTER EVENTS (Last 10)"
kubectl get events -A --sort-by='.lastTimestamp' | tail -n 11

echo -e "\n\033[1;35mInspection Complete.\033[0m"
