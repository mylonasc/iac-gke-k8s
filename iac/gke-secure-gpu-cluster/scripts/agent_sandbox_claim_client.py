#!/usr/bin/env python3
import time
import uuid

from kubernetes import client, config


def main() -> None:
    namespace = "alt-default"
    template_name = "python-runtime-template"
    claim_name = f"sandbox-claim-{uuid.uuid4().hex[:8]}"

    try:
        config.load_kube_config()
    except Exception:
        config.load_incluster_config()

    custom = client.CustomObjectsApi()
    core = client.CoreV1Api()

    body = {
        "apiVersion": "extensions.agents.x-k8s.io/v1alpha1",
        "kind": "SandboxClaim",
        "metadata": {"name": claim_name, "namespace": namespace},
        "spec": {"sandboxTemplateRef": {"name": template_name}},
    }

    custom.create_namespaced_custom_object(
        group="extensions.agents.x-k8s.io",
        version="v1alpha1",
        namespace=namespace,
        plural="sandboxclaims",
        body=body,
    )
    print(f"Created SandboxClaim {claim_name}")

    pod_name = None
    for _ in range(120):
        pods = core.list_namespaced_pod(namespace=namespace).items
        for pod in pods:
            owner_refs = pod.metadata.owner_references or []
            for owner in owner_refs:
                if owner.kind == "Sandbox" and owner.name == claim_name:
                    pod_name = pod.metadata.name
                    phase = pod.status.phase
                    if phase == "Running":
                        print(f"Sandbox Pod is running: {pod_name}")
                        print("You can now exec into it or access exposed ports.")
                        print("Delete the claim to release the sandbox when done.")
                        return
                    break
        time.sleep(2)

    raise TimeoutError("Sandbox pod did not become Running within 240 seconds")


if __name__ == "__main__":
    main()
