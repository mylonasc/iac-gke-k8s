Starting GKE Cluster Inspection...
Context: gke_gke-gpu-project-473410_europe-west4-a_gpu-spot-cluster

[1;34m================================================================================
  1. INFRASTRUCTURE & NODE POOLS
================================================================================[0m

[1;32m>> Nodes Overview (Internal IPs & OS)[0m
NAME                                               STATUS   ROLES    AGE     VERSION               INTERNAL-IP     EXTERNAL-IP    OS-IMAGE                             KERNEL-VERSION   CONTAINER-RUNTIME
gke-gpu-spot-cluster-primary-nodes-9e7d98b4-xqe7   Ready    <none>   3d23h   v1.33.5-gke.1308000   10.164.15.218   34.13.227.10   Container-Optimized OS from Google   6.6.105+         containerd://2.0.6

[1;32m>> Identifying Node Pools (via Labels)[0m
NAME                                               NODEPOOL        ZONE             INSTANCE_TYPE
gke-gpu-spot-cluster-primary-nodes-9e7d98b4-xqe7   primary-nodes   europe-west4-a   e2-standard-2

[1;32m>> Resource Capacity vs. Usage[0m
NAME                                               CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)   
gke-gpu-spot-cluster-primary-nodes-9e7d98b4-xqe7   85m          4%       1529Mi          25%         

[1;34m================================================================================
  2. NETWORKING & CONNECTIVITY
================================================================================[0m

[1;32m>> Services (LoadBalancers & ClusterIPs)[0m
NAMESPACE     NAME                   TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)            AGE
default       kubernetes             ClusterIP   34.118.224.1     <none>        443/TCP            61d
gmp-system    alertmanager           ClusterIP   None             <none>        9093/TCP           61d
gmp-system    gmp-operator           ClusterIP   34.118.237.211   <none>        8443/TCP,443/TCP   61d
gmp-system    rule-evaluator         ClusterIP   34.118.225.198   <none>        19092/TCP          61d
kube-system   default-http-backend   NodePort    34.118.227.238   <none>        80:31042/TCP       61d
kube-system   kube-dns               ClusterIP   34.118.224.10    <none>        53/UDP,53/TCP      61d
kube-system   metrics-server         ClusterIP   34.118.235.3     <none>        443/TCP            61d

[1;32m>> Ingress Resources (GCP HTTP(S) Load Balancers)[0m

[1;32m>> API Service Status[0m
v1.networking.gke.io                 Local                        True        61d
v1beta1.networking.gke.io            Local                        True        61d
v1beta2.networking.gke.io            Local                        True        61d

[1;34m================================================================================
  3. STORAGE & EXTERNAL INTEGRATIONS
================================================================================[0m

[1;32m>> Storage Classes (PD Types defined in Terraform)[0m
NAME                     PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION   AGE
premium-rwo              pd.csi.storage.gke.io   Delete          WaitForFirstConsumer   true                   61d
standard                 kubernetes.io/gce-pd    Delete          Immediate              true                   61d
standard-rwo (default)   pd.csi.storage.gke.io   Delete          WaitForFirstConsumer   true                   61d

[1;32m>> Secret Provider Classes (GCP Secret Manager Mapping)[0m

[1;34m================================================================================
  4. IDENTITY & SECURITY
================================================================================[0m

[1;32m>> Service Accounts with GCP IAM Bindings[0m
alt-default  default-ksa  default-service-account@gke-gpu-project-473410.iam.gserviceaccount.com

[1;34m================================================================================
  5. CLUSTER EVENTS (Last 10)
================================================================================[0m

[1;35mInspection Complete.[0m
