PROJECT=$(cd ../../ && ./util_scripts/get_project.sh)

gcloud secrets versions add dockerhub-ro-pat --data-file="docker_secret.bs64" --project $PROJECT
