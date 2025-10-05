VARFILE=terraform.v2.tfvars
PROJECT_ID=$(./util_scripts/get_project.sh)

USER_EMAIL=$(./util_scripts/get_account_id.sh)

echo "Setting IAM for user ${USER_EMAIL} in project ${PROJECT_ID} (found from varfile ${VARFILE})"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="user:${USER_EMAIL}" \
    --role="roles/serviceusage.serviceUsageAdmin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="user:${USER_EMAIL}" \
    --role="roles/secretmanager.admin"
