# About

Postgres is hosted on-prem for better cost performance. The communication to the postgres DB is encrypted using a wireguard-based VPN.

* For the VPN configuration you may refer to [mylonasc/homelab/vpn](https://github.com/mylonasc/homelab/tree/main/vpn).
* For the on-prem configuration (how the on-prem system is set up) you may refer to [mylonasc/homelab/database]() (might be innaccessible to the public). 

## 1. Kubernetes Service Abstraction (DNS Aliasing)

To avoid hardcoding VPN IP addresses within the application logic, we utilize a Kubernetes **Service** without a selector, paired with a manual **EndpointSlice**. This allows the application to connect to the database using the internal DNS name: `postgres-db-svc.wg-db-example.svc.cluster.local`.

### **Network Alias Manifest (`service-alias.yaml`)**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres-db-svc
  namespace: wg-db-example
spec:
  ports:
    - protocol: TCP
      port: 5432
      targetPort: 5432
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: postgres-db-svc-slice
  namespace: wg-db-example
  labels:
    kubernetes.io/service-name: postgres-db-svc
addressType: IPv4
ports:
  - protocol: TCP
    port: 5432
endpoints:
  - addresses:
      - "10.8.0.4" # Replace with the VPN IP assigned to the On-Prem DB Sidecar
```

---

## 2. Cloud Application Deployment (`deployment.yaml`)

The deployment utilizes a shared network namespace. The `wg-sidecar` establishes the tunnel and handles routing, while the `app-container` consumes the database via the alias defined above.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cloud-app-deployment
  namespace: wg-db-example
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hybrid-app
  template:
    metadata:
      labels:
        app: hybrid-app
    spec:
      containers:
        # --- PRIMARY APPLICATION CONTAINER ---
        - name: app-container
          image: python:3.11-slim # Example application image
          env:
            - name: DB_HOST
              value: "postgres-db-svc"
            - name: DB_PORT
              value: "5432"
            - name: DB_USER
              value: "db_service_user"
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: db-credentials
                  key: password
          command: ["sh", "-c", "sleep infinity"] # Placeholder for application logic

        # --- WIREGUARD NETWORK SIDECAR ---
        - name: wg-sidecar
          image: linuxserver/wireguard:latest
          securityContext:
            capabilities:
              add:
                - NET_ADMIN
            privileged: false # Prefer NET_ADMIN over privileged where possible
          env:
            - name: PUID
              value: "1000"
            - name: PGID
              value: "1000"
          volumeMounts:
            - name: wg-config-volume
              mountPath: /config/wg_confs/wg0.conf
              subPath: wg0.conf
              readOnly: true
            - name: host-modules
              mountPath: /lib/modules
              readOnly: true

      volumes:
        - name: wg-config-volume
          secret:
            secretName: wg-config # Matches existing working configuration
            defaultMode: 0600
        - name: host-modules
          hostPath:
            path: /lib/modules
```

---

## 3. Operational Implementation Guide

### **I. Namespace and Secret Initialization**
Ensure the target namespace and necessary secrets exist before deploying the manifests:
```bash
kubectl create namespace wg-db-example
# Note: Ensure the 'wg-config' secret containing wg0.conf is present in this namespace
```

### **II. Applying the Manifests**
1. Apply the Service and EndpointSlice:
   ```bash
   kubectl apply -f service-alias.yaml
   ```
2. Apply the Deployment:
   ```bash
   kubectl apply -f deployment.yaml
   ```

### **III. Integration Verification**
To verify that the application container can resolve and reach the on-premise database through the tunnel alias:

| Step | Command |
| :--- | :--- |
| **DNS Resolution** | `kubectl exec -it -n wg-db-example <POD_NAME> -c app-container -- getent hosts postgres-db-svc` |
| **Port Connectivity** | `kubectl exec -it -n wg-db-example <POD_NAME> -c app-container -- nc -zv postgres-db-svc 5432` |
| **WireGuard Status** | `kubectl exec -it -n wg-db-example <POD_NAME> -c wg-sidecar -- wg show` |

---

## 4. Summary of Configuration Logic
By defining a Kubernetes **Service** without a selector and manually populating its **EndpointSlice** with the VPN IP, we decouple the application code from the network infrastructure. The application simply connects to `postgres-db-svc`. If the database is migrated or its VPN IP changes, only the `EndpointSlice` manifest requires updating, ensuring zero changes to the application environment variables or code.

