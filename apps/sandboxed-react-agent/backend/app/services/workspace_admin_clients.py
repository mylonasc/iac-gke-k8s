from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class GoogleWorkspaceAdminClient(Protocol):
    def ensure_bucket(self, *, bucket_name: str) -> None: ...

    def ensure_service_account(self, *, account_id: str, display_name: str) -> str: ...

    def ensure_workload_identity_binding(
        self,
        *,
        gsa_email: str,
        project_id: str,
        namespace: str,
        ksa_name: str,
    ) -> None: ...

    def ensure_bucket_access(
        self,
        *,
        bucket_name: str,
        gsa_email: str,
        role: str,
    ) -> None: ...

    def delete_bucket_access(
        self,
        *,
        bucket_name: str,
        gsa_email: str,
        role: str,
    ) -> None: ...

    def delete_workload_identity_binding(
        self,
        *,
        gsa_email: str,
        project_id: str,
        namespace: str,
        ksa_name: str,
    ) -> None: ...

    def delete_bucket(self, *, bucket_name: str, delete_contents: bool) -> None: ...

    def delete_service_account(self, *, gsa_email: str) -> None: ...


class KubernetesWorkspaceAdminClient(Protocol):
    def ensure_service_account(
        self, *, namespace: str, name: str, annotations: dict[str, str]
    ) -> None: ...

    def ensure_sandbox_template(
        self,
        *,
        namespace: str,
        name: str,
        base_template_name: str,
        ksa_name: str,
        bucket_name: str,
        managed_folder_path: str,
        mount_path: str,
        labels: dict[str, str],
    ) -> None: ...

    def delete_sandbox_template(self, *, namespace: str, name: str) -> None: ...

    def delete_service_account(self, *, namespace: str, name: str) -> None: ...


@dataclass
class DisabledGoogleWorkspaceAdminClient:
    reason: str = "google workspace admin client is not configured"

    def _raise(self) -> None:
        raise RuntimeError(self.reason)

    def ensure_bucket(self, *, bucket_name: str) -> None:
        self._raise()

    def ensure_service_account(self, *, account_id: str, display_name: str) -> str:
        self._raise()
        return ""

    def ensure_workload_identity_binding(
        self,
        *,
        gsa_email: str,
        project_id: str,
        namespace: str,
        ksa_name: str,
    ) -> None:
        self._raise()

    def ensure_bucket_access(
        self,
        *,
        bucket_name: str,
        gsa_email: str,
        role: str,
    ) -> None:
        self._raise()

    def delete_bucket_access(
        self,
        *,
        bucket_name: str,
        gsa_email: str,
        role: str,
    ) -> None:
        self._raise()

    def delete_workload_identity_binding(
        self,
        *,
        gsa_email: str,
        project_id: str,
        namespace: str,
        ksa_name: str,
    ) -> None:
        self._raise()

    def delete_bucket(self, *, bucket_name: str, delete_contents: bool) -> None:
        self._raise()

    def delete_service_account(self, *, gsa_email: str) -> None:
        self._raise()


@dataclass
class DisabledKubernetesWorkspaceAdminClient:
    reason: str = "kubernetes workspace admin client is not configured"

    def _raise(self) -> None:
        raise RuntimeError(self.reason)

    def ensure_service_account(
        self, *, namespace: str, name: str, annotations: dict[str, str]
    ) -> None:
        self._raise()

    def ensure_sandbox_template(
        self,
        *,
        namespace: str,
        name: str,
        base_template_name: str,
        ksa_name: str,
        bucket_name: str,
        managed_folder_path: str,
        mount_path: str,
        labels: dict[str, str],
    ) -> None:
        self._raise()

    def delete_sandbox_template(self, *, namespace: str, name: str) -> None:
        self._raise()

    def delete_service_account(self, *, namespace: str, name: str) -> None:
        self._raise()


@dataclass
class GoogleApiWorkspaceAdminClient:
    project_id: str

    @staticmethod
    def _invoke(call):
        result = call()
        if hasattr(result, "execute"):
            return result.execute()
        return result

    @staticmethod
    def _policy_has_member(policy, *, role: str, member: str) -> bool:
        bindings = getattr(policy, "bindings", None)
        if bindings is None:
            for binding in list(policy.get("bindings") or []):
                if binding.get("role") == role and member in (
                    binding.get("members") or []
                ):
                    return True
            return False
        for binding in bindings:
            binding_role = getattr(binding, "role", None)
            binding_members = getattr(binding, "members", None)
            if binding_role is None and isinstance(binding, dict):
                binding_role = binding.get("role")
                binding_members = binding.get("members") or []
            if binding_role == role and member in list(binding_members or []):
                return True
        return False

    @staticmethod
    def _policy_add_member(policy, *, role: str, member: str):
        bindings = getattr(policy, "bindings", None)
        if bindings is None:
            bindings_list = list(policy.get("bindings") or [])
            for binding in bindings_list:
                if binding.get("role") != role:
                    continue
                members = set(binding.get("members") or [])
                binding["members"] = sorted(members | {member})
                policy["bindings"] = bindings_list
                return policy
            bindings_list.append({"role": role, "members": [member]})
            policy["bindings"] = bindings_list
            return policy

        for binding in bindings:
            binding_role = getattr(binding, "role", None)
            if binding_role is None and isinstance(binding, dict):
                binding_role = binding.get("role")
            if binding_role != role:
                continue
            binding_members = getattr(binding, "members", None)
            if binding_members is None and isinstance(binding, dict):
                binding_members = list(binding.get("members") or [])
                if member not in binding_members:
                    binding_members.append(member)
                    binding["members"] = binding_members
                return policy
            if member not in list(binding_members):
                binding_members.append(member)
            return policy
        if isinstance(bindings, list):
            bindings.append({"role": role, "members": [member]})
            return policy
        new_binding = policy.bindings.add()
        new_binding.role = role
        new_binding.members.append(member)
        return policy

    @staticmethod
    def _policy_remove_member(policy, *, role: str, member: str) -> bool:
        bindings = getattr(policy, "bindings", None)
        if bindings is None:
            changed = False
            updated = []
            for binding in list(policy.get("bindings") or []):
                if binding.get("role") != role:
                    updated.append(binding)
                    continue
                members = [
                    entry for entry in binding.get("members") or [] if entry != member
                ]
                if len(members) != len(binding.get("members") or []):
                    changed = True
                if members:
                    updated.append({**binding, "members": members})
            if changed:
                policy["bindings"] = updated
            return changed

        changed = False
        kept = []
        for binding in list(bindings):
            binding_role = getattr(binding, "role", None)
            binding_members = getattr(binding, "members", None)
            if binding_role is None and isinstance(binding, dict):
                binding_role = binding.get("role")
                binding_members = list(binding.get("members") or [])
            if binding_role != role:
                kept.append((binding_role, list(binding_members or [])))
                continue
            members = [
                entry for entry in list(binding_members or []) if entry != member
            ]
            if len(members) != len(list(binding_members or [])):
                changed = True
            if members:
                kept.append((binding_role, members))
        if not changed:
            return False
        if isinstance(policy, dict):
            policy["bindings"] = [
                {"role": kept_role, "members": kept_members}
                for kept_role, kept_members in kept
            ]
            return True
        del policy.bindings[:]
        for kept_role, kept_members in kept:
            new_binding = policy.bindings.add()
            new_binding.role = kept_role
            new_binding.members.extend(kept_members)
        return True

    def _iam_service(self):
        from googleapiclient.discovery import build

        return build("iam", "v1", cache_discovery=False)

    def _ensure_policy_binding(
        self, *, get_policy, set_policy, member: str, role: str
    ) -> None:
        policy = self._invoke(get_policy)
        if self._policy_has_member(policy, role=role, member=member):
            return
        policy = self._policy_add_member(policy, role=role, member=member)
        self._invoke(lambda: set_policy(policy))

    def _delete_policy_binding(
        self, *, get_policy, set_policy, member: str, role: str
    ) -> None:
        policy = self._invoke(get_policy)
        changed = self._policy_remove_member(policy, role=role, member=member)
        if not changed:
            return
        self._invoke(lambda: set_policy(policy))

    def ensure_bucket(self, *, bucket_name: str) -> None:
        from google.api_core.exceptions import Conflict, NotFound
        from google.cloud import storage

        client = storage.Client(project=self.project_id)
        bucket = client.bucket(bucket_name)
        try:
            bucket.reload()
            return
        except NotFound:
            pass
        try:
            client.create_bucket(bucket_name)
        except Conflict:
            return

    def ensure_service_account(self, *, account_id: str, display_name: str) -> str:
        from googleapiclient.errors import HttpError

        service = self._iam_service()
        email = f"{account_id}@{self.project_id}.iam.gserviceaccount.com"
        name = f"projects/{self.project_id}/serviceAccounts/{email}"
        try:
            service.projects().serviceAccounts().get(name=name).execute()
            return email
        except HttpError as exc:
            if getattr(exc.resp, "status", None) not in {403, 404}:
                raise
        body = {
            "accountId": account_id,
            "serviceAccount": {"displayName": display_name},
        }
        try:
            response = (
                service.projects()
                .serviceAccounts()
                .create(name=f"projects/{self.project_id}", body=body)
                .execute()
            )
            return str(response["email"])
        except HttpError as exc:
            if getattr(exc.resp, "status", None) == 409:
                return email
            raise

    def ensure_workload_identity_binding(
        self,
        *,
        gsa_email: str,
        project_id: str,
        namespace: str,
        ksa_name: str,
    ) -> None:
        service = self._iam_service()
        resource = f"projects/{self.project_id}/serviceAccounts/{gsa_email}"
        member = f"serviceAccount:{project_id}.svc.id.goog[{namespace}/{ksa_name}]"
        self._ensure_policy_binding(
            get_policy=lambda: (
                service.projects().serviceAccounts().getIamPolicy(resource=resource)
            ),
            set_policy=lambda policy: (
                service.projects()
                .serviceAccounts()
                .setIamPolicy(
                    resource=resource,
                    body={"policy": policy},
                )
            ),
            member=member,
            role="roles/iam.workloadIdentityUser",
        )

    def ensure_bucket_access(
        self,
        *,
        bucket_name: str,
        gsa_email: str,
        role: str,
    ) -> None:
        from google.cloud import storage

        client = storage.Client(project=self.project_id)
        bucket = client.bucket(bucket_name)
        policy = bucket.get_iam_policy(requested_policy_version=3)
        member = f"serviceAccount:{gsa_email}"
        if self._policy_has_member(policy, role=role, member=member):
            return
        self._policy_add_member(policy, role=role, member=member)
        bucket.set_iam_policy(policy)

    def delete_bucket_access(
        self,
        *,
        bucket_name: str,
        gsa_email: str,
        role: str,
    ) -> None:
        from google.cloud import storage

        client = storage.Client(project=self.project_id)
        bucket = client.bucket(bucket_name)
        policy = bucket.get_iam_policy(requested_policy_version=3)
        member = f"serviceAccount:{gsa_email}"
        changed = self._policy_remove_member(policy, role=role, member=member)
        if changed:
            bucket.set_iam_policy(policy)

    def delete_workload_identity_binding(
        self,
        *,
        gsa_email: str,
        project_id: str,
        namespace: str,
        ksa_name: str,
    ) -> None:
        service = self._iam_service()
        resource = f"projects/{self.project_id}/serviceAccounts/{gsa_email}"
        member = f"serviceAccount:{project_id}.svc.id.goog[{namespace}/{ksa_name}]"
        self._delete_policy_binding(
            get_policy=lambda: (
                service.projects().serviceAccounts().getIamPolicy(resource=resource)
            ),
            set_policy=lambda policy: (
                service.projects()
                .serviceAccounts()
                .setIamPolicy(
                    resource=resource,
                    body={"policy": policy},
                )
            ),
            member=member,
            role="roles/iam.workloadIdentityUser",
        )

    def delete_bucket(self, *, bucket_name: str, delete_contents: bool) -> None:
        from google.api_core.exceptions import NotFound
        from google.cloud import storage

        client = storage.Client(project=self.project_id)
        bucket = client.bucket(bucket_name)
        try:
            if delete_contents:
                for blob in client.list_blobs(bucket_name):
                    blob.delete()
            bucket.delete(force=delete_contents)
        except NotFound:
            return

    def delete_service_account(self, *, gsa_email: str) -> None:
        from googleapiclient.errors import HttpError

        service = self._iam_service()
        resource = f"projects/{self.project_id}/serviceAccounts/{gsa_email}"
        try:
            service.projects().serviceAccounts().delete(name=resource).execute()
        except HttpError as exc:
            if getattr(exc.resp, "status", None) != 404:
                raise


@dataclass
class KubernetesApiWorkspaceAdminClient:
    namespace: str

    def _load_config(self) -> None:
        from kubernetes import config

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()

    def _core_api(self):
        from kubernetes import client

        self._load_config()
        return client.CoreV1Api()

    def _custom_objects_api(self):
        from kubernetes import client

        self._load_config()
        return client.CustomObjectsApi()

    def ensure_service_account(
        self, *, namespace: str, name: str, annotations: dict[str, str]
    ) -> None:
        from kubernetes import client
        from kubernetes.client.exceptions import ApiException

        api = self._core_api()
        body = client.V1ServiceAccount(
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=namespace,
                annotations=annotations,
            )
        )
        try:
            api.read_namespaced_service_account(name=name, namespace=namespace)
            api.patch_namespaced_service_account(
                name=name, namespace=namespace, body=body
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
            api.create_namespaced_service_account(namespace=namespace, body=body)

    def ensure_sandbox_template(
        self,
        *,
        namespace: str,
        name: str,
        base_template_name: str,
        ksa_name: str,
        bucket_name: str,
        managed_folder_path: str,
        mount_path: str,
        labels: dict[str, str],
    ) -> None:
        from kubernetes.client.exceptions import ApiException

        api = self._custom_objects_api()
        base = api.get_namespaced_custom_object(
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            namespace=namespace,
            plural="sandboxtemplates",
            name=base_template_name,
        )
        derived = dict(base)
        metadata = dict(derived.get("metadata") or {})
        metadata["name"] = name
        metadata["namespace"] = namespace
        metadata["labels"] = {**(metadata.get("labels") or {}), **labels}
        for key in [
            "resourceVersion",
            "uid",
            "creationTimestamp",
            "generation",
            "managedFields",
        ]:
            metadata.pop(key, None)
        derived["metadata"] = metadata

        spec = dict(derived.get("spec") or {})
        pod_template = dict(spec.get("podTemplate") or {})
        pod_template_metadata = dict(pod_template.get("metadata") or {})
        pod_template_metadata["annotations"] = {
            **(pod_template_metadata.get("annotations") or {}),
            "gke-gcsfuse/volumes": "true",
        }
        pod_template["metadata"] = pod_template_metadata
        pod_spec = dict(pod_template.get("spec") or {})
        pod_spec["serviceAccountName"] = ksa_name
        volumes = [
            entry
            for entry in list(pod_spec.get("volumes") or [])
            if entry.get("name") != "workspace-gcs-fuse"
        ]
        volumes.append(
            {
                "name": "workspace-gcs-fuse",
                "csi": {
                    "driver": "gcsfuse.csi.storage.gke.io",
                    "readOnly": False,
                    "volumeAttributes": {
                        "bucketName": bucket_name,
                        "mountOptions": "implicit-dirs",
                    },
                },
            }
        )
        pod_spec["volumes"] = volumes
        containers = []
        for container in list(pod_spec.get("containers") or []):
            updated = dict(container)
            mounts = [
                entry
                for entry in list(updated.get("volumeMounts") or [])
                if entry.get("name") != "workspace-gcs-fuse"
            ]
            mounts.append({"name": "workspace-gcs-fuse", "mountPath": mount_path})
            updated["volumeMounts"] = mounts
            containers.append(updated)
        pod_spec["containers"] = containers
        pod_template["spec"] = pod_spec
        spec["podTemplate"] = pod_template
        derived["spec"] = spec

        try:
            existing = api.get_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace=namespace,
                plural="sandboxtemplates",
                name=name,
            )
            derived["metadata"]["resourceVersion"] = existing["metadata"].get(
                "resourceVersion"
            )
            api.replace_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace=namespace,
                plural="sandboxtemplates",
                name=name,
                body=derived,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
            api.create_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace=namespace,
                plural="sandboxtemplates",
                body=derived,
            )

    def delete_sandbox_template(self, *, namespace: str, name: str) -> None:
        from kubernetes.client.exceptions import ApiException

        api = self._custom_objects_api()
        try:
            api.delete_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace=namespace,
                plural="sandboxtemplates",
                name=name,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise

    def delete_service_account(self, *, namespace: str, name: str) -> None:
        from kubernetes.client.exceptions import ApiException

        api = self._core_api()
        try:
            api.delete_namespaced_service_account(name=name, namespace=namespace)
        except ApiException as exc:
            if exc.status != 404:
                raise
