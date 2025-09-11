#!/bin/bash
REGION=$1
GPU_TYPE='NVIDIA_T4_GPUS'
gcloud compute project-info describe \
    --region europe-west4 \
    --format="value(quotas[metric=$GPU_TYPE].limit)"

