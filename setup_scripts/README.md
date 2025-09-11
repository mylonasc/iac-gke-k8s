## Setup

### Pre-deployment
In order to deploy the cluster, it is important to
1. Install terraform 
2. Enable the relevant services in google cloud (and cloud permissions where applicable).

This is handled by the scripts in `./pre-gke-deploy/...`. 

They are numbered with a suggested execution order - sequential numbering does not necessarily imply dependency.

If you are running in ubuntu24 (or equivallent) the terraform installation script should work fine. 
Otherwise, please follow the instructions in [hasicorp's website](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli) that are relevant for your system.

## Post-deployment (`kubectl` setup)

Post-deployment you need to set up the `kubectl` to use your cluster's certs and connect to it. 
See scripts in the folder `./post-gke-deploy/kubectl_setup/...`. 

