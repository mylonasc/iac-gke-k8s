import pytest

ADMIN_HEADERS = {
    "x-auth-request-email": "mylonas.charilaos@gmail.com",
    "x-auth-request-user": "admin-sub",
}


def test_api_list_apps(client):
    response = client.get("/api/apps", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # The startup event should have bootstrapped SRA
    slugs = [a["slug"] for a in data]
    assert "sandboxed-react-agent" in slugs


def test_api_get_policy(client):
    # Policy fetching is PUBLIC in this app (no dependency added to get_app_policy)
    response = client.get("/api/apps/sandboxed-react-agent/policy/current")
    assert response.status_code == 200
    data = response.json()
    assert "policy_yaml" in data
    assert "sha256" in data


def test_roles_and_capabilities_are_editable(client):
    app_slug = "sandboxed-react-agent"

    created_cap = client.post(
        f"/api/apps/{app_slug}/permissions",
        headers=ADMIN_HEADERS,
        json={
            "name": "sandbox.template.python-runtime-template-experimental",
            "description": "Experimental template access",
        },
    )
    assert created_cap.status_code == 200
    cap_id = created_cap.json()["id"]

    created_role = client.post(
        f"/api/apps/{app_slug}/roles",
        headers=ADMIN_HEADERS,
        json={
            "name": "experimental_user",
            "description": "Can use experimental runtime template",
            "permission_ids": [cap_id],
        },
    )
    assert created_role.status_code == 200
    role_payload = created_role.json()
    role_id = role_payload["id"]
    assert role_payload["permissions"][0]["id"] == cap_id

    updated_role = client.patch(
        f"/api/apps/{app_slug}/roles/{role_id}",
        headers=ADMIN_HEADERS,
        json={"description": "Updated role description", "permission_ids": []},
    )
    assert updated_role.status_code == 200
    updated_payload = updated_role.json()
    assert updated_payload["description"] == "Updated role description"
    assert updated_payload["permissions"] == []

    updated_cap = client.patch(
        f"/api/apps/{app_slug}/permissions/{cap_id}",
        headers=ADMIN_HEADERS,
        json={
            "name": "sandbox.template.python-runtime-template-exp-v2",
            "description": "Renamed capability",
        },
    )
    assert updated_cap.status_code == 200
    updated_cap_payload = updated_cap.json()
    assert (
        updated_cap_payload["name"] == "sandbox.template.python-runtime-template-exp-v2"
    )

    deleted_cap = client.delete(
        f"/api/apps/{app_slug}/permissions/{cap_id}",
        headers=ADMIN_HEADERS,
    )
    assert deleted_cap.status_code == 200

    deleted_role = client.delete(
        f"/api/apps/{app_slug}/roles/{role_id}",
        headers=ADMIN_HEADERS,
    )
    assert deleted_role.status_code == 200
