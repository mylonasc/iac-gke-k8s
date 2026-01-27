#!/bin/bash
# Syncs the TLS secret from oauth2-proxy namespace to app-hello namespace

SOURCE_NS="oauth2-proxy"
DEST_NS="app-hello"
SECRET_NAME="magarathea-ddns-net-tls"

echo "Syncing secret $SECRET_NAME from $SOURCE_NS to $DEST_NS..."

kubectl get secret $SECRET_NAME -n $SOURCE_NS -o yaml | \
  sed "s/namespace: $SOURCE_NS/namespace: $DEST_NS/" | \
  kubectl apply -f -

echo "Done."
