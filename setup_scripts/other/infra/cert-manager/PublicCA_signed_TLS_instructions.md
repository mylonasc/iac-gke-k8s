## HTTPs K8S setup instructions


The following walks you through setting HTTPS on your GKE cluster using *Let's Encrypt*.

The best approach is to use an 
* **Ingress controller** combined with a 
* **cert-manager**. 

This combination automates the entire process of obtaining, installing, and renewing TLS certificates for your website.


-----

### Prerequisites

Before you begin, make sure you have the following:

  * A running **GKE cluster** and `kubectl` configured to connect to it.
  * A **registered domain name** (e.g., `your-website.com`). (you can get a dynamic DNS name from [noip.com](noip.com).
  * **Helm**, the package manager for Kubernetes. If you don't have it, you can [install it here](https://helm.sh/docs/intro/install/) (or check the provided installation script in the `post-deploy` folder).

-----

###  Step 1: Install an Ingress Controller

The Ingress controller is the component that sits at the edge of your cluster and routes external HTTP/HTTPS traffic to the correct services inside. We'll use the popular **NGINX Ingress Controller**.

1.  **Add the NGINX Helm repository:**

    ```bash
    helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
    helm repo update
    ```

2.  **Install the controller using Helm:**

    ```bash
    helm install ingress-nginx ingress-nginx/ingress-nginx
    ```

3.  **Get the External IP Address:** After a minute or two, the controller will be assigned a public IP address. Find it by running:

    ```bash
    kubectl get service ingress-nginx-controller -n ingress-nginx
    ```


    Look for the value in the `EXTERNAL-IP` column. It might take a moment to appear.

    ```
    NAME                       TYPE           CLUSTER-IP     EXTERNAL-IP     PORT(S)                      AGE
    ingress-nginx-controller   LoadBalancer   10.44.15.111   34.123.45.67    80:32711/TCP,443:30422/TCP   90s
    ```

    **Copy this external IP address** (e.g., `34.123.45.67`). You'll need it in the next step.

    [!TIP]
    You can store the public IP in a variable as such: 
    ```bash
    K8S_PUBLIC_IP=$(kubectl get service ingress-nginx-controller -n ingress-nginx | tail -n 1 | awk '{print $4}')
    ```

-----

### Step 2: Configure Your DNS

Now, you need to point your domain name to the Ingress controller's IP address.

Go to your domain registrar's (e.g., NoIP) DNS management panel and create an **A record**.

  * **Type:** `A`
  * **Host/Name:** `@` (for the root domain `your-website.com`) or `www` (for `www.your-website.com`).
  * **Value/Points to:** The external IP address you copied in Step 1.

In the future you also need to install an updater to update your DNS to point to the cluster (Public IPs of the ingress service can change).

-----

### Step 3: Install cert-manager

`cert-manager` will live in your cluster and will automatically handle TLS certificates from sources like Let's Encrypt.

1.  **Add the Jetstack Helm repository:**

    ```bash
    helm repo add jetstack https://charts.jetstack.io
    helm repo update
    ```

2.  **Install cert-manager:** It's important to install its Custom Resource Definitions (CRDs) first.

    ```bash
    helm install cert-manager jetstack/cert-manager \
      --namespace cert-manager \
      --create-namespace \
      --set installCRDs=true
    ```

-----

### Step 4: Create a Let's Encrypt Issuer

An `Issuer` (or `ClusterIssuer`) tells `cert-manager` how to obtain certificates. We'll create a `ClusterIssuer` so it can be used by any application in the cluster.

1.  Create a file named `cluster-ca-issuer.yaml`:

    ```yaml
    apiVersion: cert-manager.io/v1
    kind: ClusterIssuer
    metadata:
      name: letsencrypt-prod
    spec:
      acme:
        # The ACME server URL for Let's Encrypt's production environment.
        server: https://acme-v02.api.letsencrypt.org/directory
        # Email address used for ACME registration and renewal notifications.
        # IMPORTANT: Replace this with your own email address!
        email: your-email@example.com
        privateKeySecretRef:
          # Secret resource that will be used to store the account's private key.
          name: letsencrypt-prod-private-key
        # Add a single challenge solver, HTTP01, which is the most common.
        solvers:
        - http01:
            ingress:
              class: nginx
    ```

2.  **Apply this configuration** to your cluster:

    ```bash
    kubectl apply -f cluster-ca-issuer.yaml
    ```

-----

### Step 5: Deploy Your Website and Expose It

Now we'll deploy a simple web application, create a `Service` to expose it internally, and an `Ingress` resource to expose it to the world with HTTPS.

1.  Create a file named `my-website.yaml`:

    ```yaml
    # 1. The Deployment for your application
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: my-hello-website
    spec:
      replicas: 1
      selector:
        matchLabels:
          app: hello
      template:
        metadata:
          labels:
            app: hello
        spec:
          containers:
          - name: hello-web
            image: gcr.io/google-samples/hello-app:1.0 # A simple hello-world app
            ports:
            - containerPort: 8080
    ---
    # 2. The Service to expose the Deployment internally
    apiVersion: v1
    kind: Service
    metadata:
      name: my-hello-service
    spec:
      selector:
        app: hello
      ports:
        - protocol: TCP
          port: 80 # The port the service will listen on
          targetPort: 8080 # The port the container is listening on
    ---
    # 3. The Ingress to manage external traffic and TLS
    apiVersion: networking.k8s.io/v1
    kind: Ingress
    metadata:
      name: my-website-ingress
      annotations:
        # Use the NGINX Ingress controller
        kubernetes.io/ingress.class: "nginx"
        # Specify the ClusterIssuer to use for getting the certificate
        cert-manager.io/cluster-issuer: "letsencrypt-prod"
    spec:
      tls:
      - hosts:
        - your-website.com # IMPORTANT: Replace with your domain
        secretName: your-website-tls # cert-manager will create this secret with the TLS cert
      rules:
      - host: your-website.com # IMPORTANT: Replace with your domain
        http:
          paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-hello-service # Route traffic to our service
                port:
                  number: 80
    ```

2.  **IMPORTANT:** Before applying, replace `your-website.com` in the file with your actual domain name.

3.  **Apply the configuration:**

    ```bash
    kubectl apply -f my-website.yaml
    ```

-----

### Step 6: Verification

You're all set\! `cert-manager` will now see the `Ingress` resource, communicate with Let's Encrypt to get a certificate, and store it in a secret named `your-website-tls`. The NGINX Ingress controller will then use this certificate to secure traffic. This process can take a few minutes.

You can check the status:

```bash
# Check if a certificate has been successfully issued
kubectl get certificate
```

Once it shows `READY: True`, visit your domain in a web browser. You should be redirected to `https://your-website.com` and see a valid lock icon in the address bar. ✅

