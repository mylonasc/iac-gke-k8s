# find the name and value of the secret from 
gcloud secrets \
	versions add example-api-key\ 
       	--data-file="~/Workspace/secrets/example-secret-file.txt"

