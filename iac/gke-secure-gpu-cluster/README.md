## About

This is a deployment that creates a GKE in google cloud kybernetes engine. 

The cloud has the following features:
* 2 types of GPU-enabled nodes clusters
* 1 type of non-GPU general purpose nodes cluster
* Secrets manager integration (e.g., for API keys)
* Remote backend integration


## Using a backend

## Public access
The most cost-effective (free) option is to use a node port for public access.
In order, however, to allow public access to pass google's firewall rules you must create an exception for your cluster. 

You can find the name of the available clusters by running:

```bash
gcloud container clusters list
```

## Extension with secret management

To create the `google_secret_manager` resource in google cloud and add a secret, run  the terraform apply on the `secrets.tf` file
```bash
terraform apply 
```


