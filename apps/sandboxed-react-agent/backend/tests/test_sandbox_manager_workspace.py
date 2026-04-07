from app.sandbox_manager import SandboxManager


def test_cluster_command_defaults_to_workspace() -> None:
    manager = SandboxManager()

    command = manager._cluster_command_with_workspace(
        "python -c 'print(1)'",
        runtime_config={"workspace_path": "/workspace"},
    )

    assert "export HOME=/workspace" in command
    assert "mkdir -p /workspace" in command
    assert "cd /workspace" in command


def test_python_script_sets_workspace_home_and_cwd() -> None:
    manager = SandboxManager()

    script = manager._build_python_script(
        "print('hello')",
        runtime_config={"workspace_path": "/workspace"},
    )

    assert 'os.environ["HOME"] = _workspace_path' in script
    assert "os.chdir(_workspace_path)" in script
