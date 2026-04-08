from app.agents.toolkits.sandbox import SandboxToolkitProvider


def test_sandbox_provider_forces_cluster_mode_when_local_disallowed() -> None:
    provider = SandboxToolkitProvider(
        session_sandbox=None,  # type: ignore[arg-type]
        sandbox_manager=None,  # type: ignore[arg-type]
        sandbox_lifecycle=None,  # type: ignore[arg-type]
        allow_local_mode=False,
    )

    merged = provider.merge_config(
        {"runtime": {"mode": "cluster"}, "lifecycle": {}},
        {"runtime": {"mode": "local"}},
    )

    assert merged["runtime"]["mode"] == "cluster"


def test_sandbox_provider_allows_local_mode_when_enabled() -> None:
    provider = SandboxToolkitProvider(
        session_sandbox=None,  # type: ignore[arg-type]
        sandbox_manager=None,  # type: ignore[arg-type]
        sandbox_lifecycle=None,  # type: ignore[arg-type]
        allow_local_mode=True,
    )

    merged = provider.merge_config(
        {"runtime": {"mode": "cluster"}, "lifecycle": {}},
        {"runtime": {"mode": "local"}},
    )

    assert merged["runtime"]["mode"] == "local"


def test_sandbox_provider_rejects_invalid_profile() -> None:
    provider = SandboxToolkitProvider(
        session_sandbox=None,  # type: ignore[arg-type]
        sandbox_manager=None,  # type: ignore[arg-type]
        sandbox_lifecycle=None,  # type: ignore[arg-type]
        allow_local_mode=True,
    )

    try:
        provider.merge_config(
            {"runtime": {"mode": "cluster"}, "lifecycle": {}},
            {"runtime": {"profile": "workspace_auto"}},
        )
    except ValueError as exc:
        assert (
            str(exc) == "sandbox_profile must be 'persistent_workspace' or 'transient'"
        )
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for invalid sandbox profile")


def test_sandbox_provider_apply_updates_accepts_legacy_profile_field() -> None:
    provider = SandboxToolkitProvider(
        session_sandbox=None,  # type: ignore[arg-type]
        sandbox_manager=None,  # type: ignore[arg-type]
        sandbox_lifecycle=None,  # type: ignore[arg-type]
        allow_local_mode=True,
    )

    updated = provider.apply_updates(
        {
            "runtime": {"mode": "cluster", "profile": "persistent_workspace"},
            "lifecycle": {},
        },
        legacy_updates={"sandbox_profile": "transient"},
    )

    assert updated["runtime"]["profile"] == "transient"
