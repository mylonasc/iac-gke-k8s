project_id                  = "gke-gpu-project-473410"
cluster_deletion_protection = false
# location                    = europe-west4-a
# region                      = "europe-north1-a"
gpu_count                   = 1

gpu_type_ng_a               = "nvidia-l4"
gpu_machine_type_ng_a       = "g2-standard-4"

gpu_type_ng_b               = "nvidia-tesla-t4"
gpu_machine_type_ng_b       = "n1-standard-4"

# L4 small setup (4 vCPUs, 16GB RAM)
# gpu_type = "nvidia-tesla-l4"
# gpu_machine_type = "g2-standard-4"

# L4 medium setup (
# gpu_type = "nvidia-tesla-l4"
# gpu_machine_type = "g2-standard-4"
