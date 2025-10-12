## Setup


### Enabling the `csi-secrets-store` feature
The cluster is set up to have a google service account, that is usable from the k8s cluster. 
Whenever the cluster needs any of the secrets that are stored in the secretstore of google cloud,  
the secrets are retrieved directly from GCP. 

This is different from the k8s secrets (i.e., the k8s secrets that are stored in the google secrets manager do not show up as secrets in k8s). 

To enable this, run the following command (on the existing cluster):

1. Find the name and region of the cluster you would like to update:

```bash
gcloud container clusters list

> NAME              LOCATION        MASTER_VERSION      MASTER_IP    MACHINE_TYPE  NODE_VERSION        NUM_NODES  STATUS   STACK_TYPE
> gpu-spot-cluster  europe-west4-a  1.33.4-gke.1350000  34.6.21.204  e2-small      1.33.4-gke.1350000  1          RUNNING  IPV4
```

2. Run the command to update the cluster: 

```bash
CL_REGION='europe-west4-a'
CL_NAME=$(gcloud container clusters list | tail -n 1 | awk '{print $1}')

gcloud container clusters update $CL_NAME --region=CL_REGION --enable-secret-manager
```

The command takes some time to finish. When running, the "operation" for the cluster update will be visible by running the following command:

```
gcloud container operations list 
```


3. Finally, to confirm that the operation was successful, check whether there are pods with `csi-secrets` in their name:

```bash
kubectl get pods -n kube-system | grep csi-secrets
```
