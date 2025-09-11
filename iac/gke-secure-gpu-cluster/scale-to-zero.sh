CLUSTER_NAME=#1
gcloud container clusters resize YOUR_CLUSTER --node-pool=primary-nodes --num-nodes=0
