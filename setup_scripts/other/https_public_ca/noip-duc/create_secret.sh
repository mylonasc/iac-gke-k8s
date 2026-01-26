DUC_SECRET_PATH=~/Workspace/secrets/noip-duc.env

kubectl create secret generic noip-credentials \
  --from-env-file=$DUC_SECRET_PATH \
  --namespace ingress-nginx