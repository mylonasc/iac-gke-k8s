export EXTERNAL_IP=$(kubectl get service ingress-nginx-controller | awk '{print $4}'|tail -n 1)

