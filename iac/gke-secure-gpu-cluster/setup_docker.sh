export DOCKERHUB_USER="mylonasc"
export DOCKERHUB_PAT="$(cat ~/Workspace/secrets/docker-pat-secret.txt)"   # paste token

printf '%s' "$DOCKERHUB_PAT" | docker login --username "$DOCKERHUB_USER" --password-stdin

kubectl -n default create secret docker-registry dockerhub-regcred \
  --docker-server="https://index.docker.io/v1/" \
  --docker-username="$DOCKERHUB_USER" \
  --docker-password="$DOCKERHUB_PAT"