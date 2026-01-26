
# Kubernetes No-IP DNS Updater

This setup ensures that your **No-IP DNS record** always points to your **NGINX Ingress External IP**, rather than the Node's public egress IP.

## 📂 Folder Structure

* `create_secret.sh`: Script to generate K8s secrets from your local `.env`.
* `noip-duc-service-acct.yaml`: RBAC permissions (ServiceAccount, Role, Binding).
* `noip-updater-cron.yaml`: The CronJob that syncs the IP every 5 minutes.

---

## 🚀 Setup Instructions

### 1. Prepare your Environment

Create a `.env` file in the root of this directory:

```bash
NO_IP_USER=your_email@example.com
NO_IP_PASS=your_password
NO_IP_HOSTNAME=yourdomain.ddns.net

```

### 2. Create the Secret

Run your script to push the credentials to the cluster.

```bash
chmod +x create_secret.sh
./create_secret.sh

```

*Note: Ensure your script targets the `ingress-nginx` namespace.*

### 3. Apply RBAC Permissions

The CronJob needs permission to "read" the Ingress service to find its IP.

```bash
kubectl apply -f noip-duc-service-acct.yaml

```

### 4. Deploy the CronJob

This will schedule the update to run every 5 minutes.

```bash
kubectl apply -f noip-updater-cron.yaml

```

---

## 🛠 Troubleshooting & Manual Trigger

### Trigger an Update Now

If you don't want to wait 5 minutes to test, trigger a manual execution:

```bash
kubectl create job --from=cronjob/noip-sync noip-manual-run -n ingress-nginx

```

### Verify the Logs

Check if the API call to No-IP was successful:

```bash
# Get the pod name created by the manual run
kubectl logs -l job-name=noip-manual-run -n ingress-nginx

```

**Expected Output:**

* `good [IP]`: Success, DNS updated.
* `nochg [IP]`: Success, but the IP hasn't changed since the last update.
* `badauth`: Check your `.env` credentials.

---

## 🧹 Cleanup

To remove the updater from your cluster:

```bash
kubectl delete -f noip-updater-cron.yaml
kubectl delete -f noip-duc-service-acct.yaml
kubectl delete secret noip-credentials -n ingress-nginx

```

---
