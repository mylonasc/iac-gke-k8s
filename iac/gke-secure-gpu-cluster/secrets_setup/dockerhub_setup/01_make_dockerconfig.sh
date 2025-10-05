#!/bin/bash

# A script to generate a Kubernetes .dockerconfigjson secret format
# for authenticating with Docker Hub.

# --- Input Validation ---
if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <username> <personal-access-token> <email>"
    echo "Example: $0 myuser dckr_pat_abc123 myuser@example.com"
    exit 1
fi

# --- Assign Arguments to Variables ---
USERNAME=$1
PAT=$2
EMAIL=$3

read -s -p "Please enter the dockerhub password:" DH_PWD

# --- Generate Base64 Encoded Auth String ---
# The -n flag for echo is crucial to prevent a trailing newline from being encoded.
AUTH_STRING=$(echo -n "${USERNAME}:${PAT}" | base64)

# --- Generate and Print JSON Output ---
# Using a heredoc (<<EOF) to create the multi-line JSON structure.
# The variables are substituted with their values.
cat <<EOF
{
  "auths": {
    "https://index.docker.io/v1/": {
      "auth": "${AUTH_STRING}"
    }
  }
}
EOF
