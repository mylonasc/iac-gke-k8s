from __future__ import annotations

import hashlib
import json
import logging
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)


DEFAULT_AUTHZ_POLICY_YAML = """
version: 1
default_roles:
  authenticated:
    - authenticated
  unauthenticated:
    - anonymous
role_mappings:
  groups:
    sra-admins:
      - ops_admin
    sra-pydata:
      - pydata_user
    sra-terminal:
      - terminal_user
roles:
  anonymous:
    capabilities:
      - terminal.open
      - sandbox.mode.cluster
      - sandbox.profile.transient
      - sandbox.execution_model.session
  authenticated:
    capabilities:
      - terminal.open
      - sandbox.mode.cluster
      - sandbox.profile.persistent_workspace
      - sandbox.profile.transient
      - sandbox.execution_model.session
      - sandbox.execution_model.ephemeral
      - sandbox.template.python-runtime-template-small
      - sandbox.template.python-runtime-template
      - sandbox.template.python-runtime-template-large
  terminal_user:
    capabilities:
      - terminal.open
  pydata_user:
    capabilities:
      - sandbox.template.python-runtime-template-pydata
  ops_admin:
    capabilities:
      - admin.ops.read
      - admin.ops.write
      - authz.policy.manage
feature_rules:
  terminal.open:
    any_capabilities:
      - terminal.open
  admin.ops.read:
    any_capabilities:
      - admin.ops.read
  admin.ops.write:
    any_capabilities:
      - admin.ops.write
  authz.policy.manage:
    any_capabilities:
      - authz.policy.manage
sandbox_rules:
  templates:
    python-runtime-template-pydata:
      any_capabilities:
        - sandbox.template.python-runtime-template-pydata
  modes:
    cluster: {}
    local:
      any_capabilities:
        - sandbox.mode.local
  profiles:
    persistent_workspace:
      any_capabilities:
        - sandbox.profile.persistent_workspace
    transient:
      any_capabilities:
        - sandbox.profile.transient
  execution_models:
    session:
      any_capabilities:
        - sandbox.execution_model.session
    ephemeral:
      any_capabilities:
        - sandbox.execution_model.ephemeral
""".strip()


def _as_lower_set(raw: Any) -> set[str]:
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw]
    else:
        values = []
    return {value.lower() for value in values if value}


def _as_str_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw]
    else:
        values = []
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _claims_groups(claims: dict[str, Any]) -> set[str]:
    raw = claims.get("groups")
    return _as_lower_set(raw)


@dataclass(frozen=True)
class AccessContext:
    user_id: str
    subject: str
    email: str
    groups: tuple[str, ...]
    roles: tuple[str, ...]
    capabilities: tuple[str, ...]
    authenticated: bool

    def has_capability(self, capability: str) -> bool:
        value = str(capability or "").strip().lower()
        if not value:
            return False
        return value in set(self.capabilities)


@dataclass(frozen=True)
class _Rule:
    any_roles: tuple[str, ...]
    all_roles: tuple[str, ...]
    any_capabilities: tuple[str, ...]
    all_capabilities: tuple[str, ...]


def _parse_rule(raw: Any) -> _Rule:
    if not isinstance(raw, dict):
        return _Rule((), (), (), ())
    return _Rule(
        any_roles=tuple(item.lower() for item in _as_str_list(raw.get("any_roles"))),
        all_roles=tuple(item.lower() for item in _as_str_list(raw.get("all_roles"))),
        any_capabilities=tuple(
            item.lower() for item in _as_str_list(raw.get("any_capabilities"))
        ),
        all_capabilities=tuple(
            item.lower() for item in _as_str_list(raw.get("all_capabilities"))
        ),
    )


def _rule_allows(rule: _Rule, *, roles: set[str], capabilities: set[str]) -> bool:
    if not any(
        (rule.any_roles, rule.all_roles, rule.any_capabilities, rule.all_capabilities)
    ):
        return True
    if rule.any_roles and not any(item in roles for item in rule.any_roles):
        return False
    if rule.all_roles and not all(item in roles for item in rule.all_roles):
        return False
    if rule.any_capabilities and not any(
        item in capabilities for item in rule.any_capabilities
    ):
        return False
    if rule.all_capabilities and not all(
        item in capabilities for item in rule.all_capabilities
    ):
        return False
    return True


@dataclass(frozen=True)
class _ResolvedPolicy:
    version: int
    default_roles_authenticated: tuple[str, ...]
    default_roles_unauthenticated: tuple[str, ...]
    role_mappings_groups: dict[str, tuple[str, ...]]
    role_mappings_user_ids: dict[str, tuple[str, ...]]
    role_mappings_emails: dict[str, tuple[str, ...]]
    role_capabilities: dict[str, tuple[str, ...]]
    feature_rules: dict[str, _Rule]
    sandbox_template_rules: dict[str, _Rule]
    sandbox_mode_rules: dict[str, _Rule]
    sandbox_profile_rules: dict[str, _Rule]
    sandbox_execution_model_rules: dict[str, _Rule]


def _parse_policy(raw: Any) -> _ResolvedPolicy:
    if not isinstance(raw, dict):
        raise ValueError("Authorization policy root must be a YAML mapping")

    version = int(raw.get("version") or 1)
    defaults = (
        raw.get("default_roles") if isinstance(raw.get("default_roles"), dict) else {}
    )
    default_roles_authenticated = tuple(
        item.lower() for item in _as_str_list(defaults.get("authenticated"))
    )
    default_roles_unauthenticated = tuple(
        item.lower() for item in _as_str_list(defaults.get("unauthenticated"))
    )

    role_mappings = (
        raw.get("role_mappings") if isinstance(raw.get("role_mappings"), dict) else {}
    )
    
    def _parse_mapping(key: str) -> dict[str, tuple[str, ...]]:
        mapping_raw = role_mappings.get(key) if isinstance(role_mappings.get(key), dict) else {}
        result: dict[str, tuple[str, ...]] = {}
        for identifier, roles in mapping_raw.items():
            normalized_id = str(identifier or "").strip().lower()
            if not normalized_id:
                continue
            result[normalized_id] = tuple(item.lower() for item in _as_str_list(roles))
        return result

    roles_raw = raw.get("roles") if isinstance(raw.get("roles"), dict) else {}
    role_capabilities: dict[str, tuple[str, ...]] = {}
    for role_name, role_config in roles_raw.items():
        normalized_role = str(role_name or "").strip().lower()
        if not normalized_role:
            continue
        if not isinstance(role_config, dict):
            role_config = {}
        role_capabilities[normalized_role] = tuple(
            item.lower() for item in _as_str_list(role_config.get("capabilities"))
        )

    feature_rules_raw = (
        raw.get("feature_rules") if isinstance(raw.get("feature_rules"), dict) else {}
    )
    feature_rules = {
        str(name).strip().lower(): _parse_rule(rule)
        for name, rule in feature_rules_raw.items()
        if str(name).strip()
    }

    sandbox_raw = (
        raw.get("sandbox_rules") if isinstance(raw.get("sandbox_rules"), dict) else {}
    )

    def _parse_named_rules(section_name: str) -> dict[str, _Rule]:
        section_raw = (
            sandbox_raw.get(section_name)
            if isinstance(sandbox_raw.get(section_name), dict)
            else {}
        )
        return {
            str(name).strip().lower(): _parse_rule(rule)
            for name, rule in section_raw.items()
            if str(name).strip()
        }

    return _ResolvedPolicy(
        version=version,
        default_roles_authenticated=default_roles_authenticated,
        default_roles_unauthenticated=default_roles_unauthenticated,
        role_mappings_groups=_parse_mapping("groups"),
        role_mappings_user_ids=_parse_mapping("user_ids"),
        role_mappings_emails=_parse_mapping("emails"),
        role_capabilities=role_capabilities,
        feature_rules=feature_rules,
        sandbox_template_rules=_parse_named_rules("templates"),
        sandbox_mode_rules=_parse_named_rules("modes"),
        sandbox_profile_rules=_parse_named_rules("profiles"),
        sandbox_execution_model_rules=_parse_named_rules("execution_models"),
    )


class AuthorizationPolicyService:
    def __init__(
        self,
        *,
        policy_path: str,
        remote_policy_url: str | None = None,
        remote_timeout_seconds: int = 3,
    ) -> None:
        self.policy_path = Path(policy_path)
        self.remote_policy_url = str(remote_policy_url or "").strip() or None
        self.remote_timeout_seconds = max(1, int(remote_timeout_seconds))
        self._state_lock = threading.RLock()
        self._policy_yaml_text = ""
        self._policy = _parse_policy(yaml.safe_load(DEFAULT_AUTHZ_POLICY_YAML))
        self._last_loaded_at = ""
        self._last_source = "default"
        self._last_error = ""
        self._ensure_policy_loaded()

    @classmethod
    def from_env(cls) -> "AuthorizationPolicyService":
        import os

        policy_path = (
            os.getenv("AUTHZ_POLICY_PATH")
            or "/tmp/sandboxed-react-agent-authz-policy.yaml"
        ).strip()
        remote_policy_url = (os.getenv("AUTHZ_POLICY_URL") or "").strip() or None
        remote_timeout_seconds_raw = os.getenv("AUTHZ_REMOTE_TIMEOUT_SECONDS")
        try:
            remote_timeout_seconds = int(remote_timeout_seconds_raw or "3")
        except ValueError:
            remote_timeout_seconds = 3
        return cls(
            policy_path=policy_path,
            remote_policy_url=remote_policy_url,
            remote_timeout_seconds=remote_timeout_seconds,
        )

    def _ensure_policy_loaded(self) -> None:
        path = self.policy_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(DEFAULT_AUTHZ_POLICY_YAML + "\n", encoding="utf-8")
        self.reload_policy_from_disk()

    def _apply_policy_text(self, policy_yaml_text: str, *, source: str) -> None:
        parsed_yaml = yaml.safe_load(policy_yaml_text)
        resolved = _parse_policy(parsed_yaml)
        now = datetime.now(UTC).isoformat()
        with self._state_lock:
            self._policy = resolved
            self._policy_yaml_text = policy_yaml_text
            self._last_loaded_at = now
            self._last_source = source
            self._last_error = ""

    def reload_policy_from_disk(self) -> None:
        content = self.policy_path.read_text(encoding="utf-8")
        self._apply_policy_text(content, source=f"file:{self.policy_path}")

    def set_policy_from_yaml_text(
        self, policy_yaml_text: str, *, persist: bool = False
    ) -> None:
        text = str(policy_yaml_text or "")
        self._apply_policy_text(text, source="inline")
        if persist:
            self.policy_path.parent.mkdir(parents=True, exist_ok=True)
            self.policy_path.write_text(text.rstrip() + "\n", encoding="utf-8")

    def reset_to_default_policy(self) -> None:
        self.set_policy_from_yaml_text(DEFAULT_AUTHZ_POLICY_YAML, persist=True)

    def refresh_from_remote(self) -> bool:
        url = self.remote_policy_url
        if not url:
            return False
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json, text/plain, */*"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.remote_timeout_seconds
            ) as response:
                body_bytes = response.read()
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            with self._state_lock:
                self._last_error = str(exc)
            logger.warning(
                "authz.policy.remote_fetch_failed",
                extra={"event": "authz.policy.remote_fetch_failed", "error": str(exc)},
            )
            return False

        body_text = body_bytes.decode("utf-8", errors="replace")
        policy_text = body_text
        try:
            payload = json.loads(body_text)
            if isinstance(payload, dict):
                maybe = payload.get("policy_yaml")
                if isinstance(maybe, str) and maybe.strip():
                    policy_text = maybe
        except json.JSONDecodeError:
            pass

        try:
            self._apply_policy_text(policy_text, source=f"remote:{url}")
        except Exception as exc:
            with self._state_lock:
                self._last_error = str(exc)
            logger.warning(
                "authz.policy.remote_parse_failed",
                extra={"event": "authz.policy.remote_parse_failed", "error": str(exc)},
            )
            return False
        return True

    def policy_snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            raw = self._policy_yaml_text
            version = self._policy.version
            loaded_at = self._last_loaded_at
            source = self._last_source
            last_error = self._last_error
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else ""
        return {
            "version": version,
            "loaded_at": loaded_at,
            "source": source,
            "sha256": digest,
            "last_error": last_error or None,
            "policy_yaml": raw,
        }

    def _current_policy(self) -> _ResolvedPolicy:
        with self._state_lock:
            return self._policy

    def build_access_context(
        self,
        *,
        user_id: str,
        claims: dict[str, Any] | None,
        authenticated: bool,
    ) -> AccessContext:
        claims_dict = claims if isinstance(claims, dict) else {}
        policy = self._current_policy()

        groups = _claims_groups(claims_dict)
        roles: set[str] = set(
            policy.default_roles_authenticated
            if authenticated
            else policy.default_roles_unauthenticated
        )

        for group in groups:
            for role in policy.role_mappings_groups.get(group, ()):
                roles.add(role)

        # Resolve User-specific mappings
        normalized_user_id = str(user_id or "").strip().lower()
        if normalized_user_id:
            for role in policy.role_mappings_user_ids.get(normalized_user_id, ()):
                roles.add(role)
                
        normalized_email = str(claims_dict.get("email") or "").strip().lower()
        if normalized_email:
            for role in policy.role_mappings_emails.get(normalized_email, ()):
                roles.add(role)

        roles_claim = claims_dict.get("roles")
        for role in _as_lower_set(roles_claim):
            roles.add(role)

        capabilities: set[str] = set()
        for role in roles:
            capabilities.update(policy.role_capabilities.get(role, ()))

        subject = str(claims_dict.get("sub") or user_id or "").strip()
        email = str(claims_dict.get("email") or "").strip().lower()

        return AccessContext(
            user_id=str(user_id or "").strip(),
            subject=subject,
            email=email,
            groups=tuple(sorted(groups)),
            roles=tuple(sorted(roles)),
            capabilities=tuple(sorted(capabilities)),
            authenticated=bool(authenticated),
        )

    def is_feature_allowed(self, context: AccessContext | None, feature: str) -> bool:
        if context is None:
            return False
        policy = self._current_policy()
        normalized = str(feature or "").strip().lower()
        if not normalized:
            return False

        rule = policy.feature_rules.get(normalized)
        if rule is None:
            return True

        return _rule_allows(
            rule,
            roles=set(context.roles),
            capabilities=set(context.capabilities),
        )

    def filter_sandbox_values(
        self,
        context: AccessContext | None,
        *,
        category: str,
        values: list[str],
    ) -> list[str]:
        normalized_category = str(category or "").strip().lower()
        deduped_values = _as_str_list(values)
        if context is None:
            return deduped_values

        policy = self._current_policy()
        if normalized_category == "templates":
            rules = policy.sandbox_template_rules
        elif normalized_category == "modes":
            rules = policy.sandbox_mode_rules
        elif normalized_category == "profiles":
            rules = policy.sandbox_profile_rules
        elif normalized_category == "execution_models":
            rules = policy.sandbox_execution_model_rules
        else:
            return deduped_values

        roles = set(context.roles)
        capabilities = set(context.capabilities)
        allowed: list[str] = []
        for original in deduped_values:
            key = original.lower()
            rule = rules.get(key)
            if rule is None:
                allowed.append(original)
                continue
            if _rule_allows(rule, roles=roles, capabilities=capabilities):
                allowed.append(original)
        return allowed

    def is_sandbox_value_allowed(
        self,
        context: AccessContext | None,
        *,
        category: str,
        value: str,
    ) -> bool:
        if not str(value or "").strip():
            return True
        allowed = self.filter_sandbox_values(
            context,
            category=category,
            values=[value],
        )
        return bool(allowed)
