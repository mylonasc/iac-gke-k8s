
### About this repo
This repo contains a set of IaC code to set up and deploy to a K8S cluster using terraform to **Google Kubernetes Engine (GKE)**.

This comes from my need to have a well-configured cost-effective personal cluster I can use for learning and experimentation with IaC technologies.

Moreover, it is quite a hassle to manage the combinations of GPU and machine type constraints that google cloud has, and I thought it would be good to have an easy way to deploy GPU jobs from IaC code that I completely understand and control. 

### Setup Notes
To check in which regions a particular GPU type exists:
```
gcloud compute accelerator-types list --filter="name=nvidia-tesla-t4"

```

You will almost surely require manual adjustments for the GPU quotas (described [here](required_manual_adjustments.md)).

#### Machine type selection:
Different GPUs require different machine types. 
You can find the GPU machine types for google cloud here: [GPU machine types](https://cloud.google.com/compute/docs/gpus).

|GPU vRAM|GPU|Machine type|
|--|---|------------|
|16GB|`nvidia-tesla-t4` | [N1](https://cloud.google.com/compute/docs/gpus#n1-gpus) e.g., `n1-standard-4`|
|8GB|`nvidia-tesla-p4`| |
|16GB|`nvidia-tesla-v100`| |
|16GB|`nvidia-tesla-p100`| |
|24GB|`nvidia-tesla-l4`| [G2](https://cloud.google.com/compute/docs/accelerator-optimized-machines#g2-vms) | 



### Set up the `kubectl` tool
```bash 
gcloud container clusters get-credentials gpu-spot-cluster --region europe-west4
```

## `gcloud` cheatsheet 
To list projects:
```bash
gcloud projects list
```

to select default project:
```bash 
gcloud config set project ${PROJECT_ID}
```

