#!/bin/bash

# ==============================================================================
# GKE Node Pool Taint Inspector
#
# Description:
#   This script inspects all node pools in a specified GKE cluster and
#   reports the taints configured on them. This is the correct method for
#   checking taints on node pools that may be scaled to zero.
#
# Prerequisites:
#   - `gcloud` (Google Cloud SDK) command-line tool, authenticated.
#   - `jq` command-line JSON processor.
#
# Usage:
#   ./inspect_gke_taints.sh <CLUSTER_NAME> <GCP_LOCATION>
#
# Example:
#   ./inspect_gke_taints.sh my-production-cluster us-central1-c
#
# ==============================================================================

# Exit immediately if a command exits with a non-zero status.
set -e -o pipefail

# --- Get script arguments ---
CLUSTER_NAME="$1"
LOCATION="$2" # Can be a zone like us-central1-c or a region like us-central1

# --- Functions ---

# Function to print usage information and exit.
usage() {
  echo "Usage: $0 <CLUSTER_NAME> <GCP_LOCATION>"
  echo "  <CLUSTER_NAME>: The name of your GKE cluster."
  echo "  <GCP_LOCATION>: The GCP zone (e.g., us-central1-c) or region (e.g., us-central1) where the cluster resides."
  echo
  echo "Example: $0 my-gke-cluster us-central1-c"
  exit 1
}

# Function to check for required command-line tools.
check_dependencies() {
  if ! command -v gcloud &> /dev/null; then
    echo "ERROR: 'gcloud' command not found. Please install the Google Cloud SDK and ensure it's in your PATH."
    exit 1
  fi
  if ! command -v jq &> /dev/null; then
    echo "ERROR: 'jq' command not found. Please install jq to parse JSON output."
    echo "  On macOS: brew install jq"
    echo "  On Debian/Ubuntu: sudo apt-get install jq"
    echo "  On RHEL/CentOS: sudo yum install jq"
    exit 1
  fi
}

# --- Main Script ---

# 1. Verify dependencies and arguments
check_dependencies
if [ -z "$CLUSTER_NAME" ] || [ -z "$LOCATION" ]; then
  echo "Error: Missing required arguments."
  usage
fi

echo "🔍 Fetching node pools for cluster '$CLUSTER_NAME' in location '$LOCATION'..."
echo "------------------------------------------------------------------"

# 2. Determine if the location is a zone or a region to use the correct gcloud flag.
# We suppress error output for the check in case the user provides a zone first.
if gcloud compute regions describe "$LOCATION" >/dev/null 2>&1; then
    LOCATION_FLAG="--region"
else
    LOCATION_FLAG="--zone"
fi


# 3. Get the list of all node pools for the specified cluster.
# The 'gcloud ... --format="value(name)"' command returns a simple, newline-separated list of names.
node_pools=$(gcloud container node-pools list \
  --cluster="$CLUSTER_NAME" \
  "$LOCATION_FLAG"="$LOCATION" \
  --format="value(name)")

if [ -z "$node_pools" ]; then
    echo "No node pools found for cluster '$CLUSTER_NAME' in '$LOCATION'."
    exit 0
fi

# 4. Loop through each node pool name.
while IFS= read -r pool_name; do
  echo "🔹 Node Pool: $pool_name"

  # Describe the node pool and get its taints in JSON format.
  # This output will be a JSON array of taint objects, or 'null' if none exist.
  taints_json=$(gcloud container node-pools describe "$pool_name" \
    --cluster="$CLUSTER_NAME" \
    "$LOCATION_FLAG"="$LOCATION" \
    --format="json(config.taints)")

  # 5. Use jq to check if the taints field is null or an empty array.
  if [[ "$taints_json" == "null" || $(echo "$taints_json" | jq 'length') -eq 0 ]]; then
    echo "   <No taints configured>"
  else
    # If taints exist, use jq to parse the JSON and format each taint on a new line.
    echo "$taints_json" | jq -r '.[] | "   - Key=\(.key), Value=\(.value), Effect=\(.effect)"'
  fi
  echo # Add a newline for better readability between node pools.
done <<< "$node_pools"

echo "------------------------------------------------------------------"
echo " Script finished."
