## GPU Quota Adjustment
If you are to use GPUs, it is required to manually set the GPU quota manually. 
**Note:** There are both per-region quotas and global! 
In cloud console search `GPUS_ALL_REGIONS` and set the global quota to a number larger than 1.

link to quota page (project `gke-gpu-project`): [link](https://console.cloud.google.com/iam-admin/quotas?referrer=search&project=gke-gpu-project-473410&pageState=(%22allQuotasTable%22:(%22f%22:%22%255B%257B_22k_22_3A_22Metric_22_2C_22t_22_3A10_2C_22v_22_3A_22_5C_22compute.googleapis.com%252Fgpus_all_regions_5C_22_22_2C_22s_22_3Atrue_2C_22i_22_3A_22metricName_22%257D%255D%22)))
