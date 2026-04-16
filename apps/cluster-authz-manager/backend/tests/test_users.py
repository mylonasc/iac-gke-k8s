import pytest

def test_user_crud(client):
    admin_headers = {"x-auth-request-email": "mylonas.charilaos@gmail.com", "x-auth-request-user": "admin-sub"}
    
    response = client.post("/api/users", 
        json={"subject": "user-1", "email": "user1@example.com", "display_name": "User One"},
        headers=admin_headers
    )
    assert response.status_code == 200
    user_id = response.json()["id"]

    response = client.get("/api/users?q=User", headers=admin_headers)
    assert response.status_code == 200
    assert any(u["subject"] == "user-1" for u in response.json())

    response = client.patch(f"/api/users/{user_id}", json={"is_active": False}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    response = client.delete(f"/api/users/{user_id}", headers=admin_headers)
    assert response.status_code == 200
    
    response = client.get("/api/users", headers=admin_headers)
    subjects = [u["subject"] for u in response.json()]
    assert "user-1" not in subjects

def test_global_kill_switch(client):
    admin_headers = {"x-auth-request-email": "mylonas.charilaos@gmail.com", "x-auth-request-user": "admin-sub"}
    
    # Create user
    client.post("/api/users", 
        json={"subject": "bad-user", "email": "bad@example.com", "is_active": True},
        headers=admin_headers
    )
    
    user_headers = {"x-auth-request-email": "bad@example.com", "x-auth-request-user": "bad-user"}
    
    # 1. Give them admin role in manager
    response = client.get("/api/apps", headers=admin_headers)
    manager_app = next(a for a in response.json() if a["slug"] == "cluster-authz-manager")
    
    response = client.get(f"/api/apps/{manager_app['slug']}/roles", headers=admin_headers)
    admin_role = next(r for r in response.json() if r["name"] == "admin")
    
    client.post(f"/api/apps/{manager_app['slug']}/bindings/users", 
        json={"user_identifier": "bad@example.com", "identifier_type": "email", "role_id": admin_role["id"]},
        headers=admin_headers
    )
    
    # 2. Verify they CAN access
    response = client.get("/api/users", headers=user_headers)
    assert response.status_code == 200
    
    # 3. DEACTIVATE them
    users = client.get("/api/users", headers=admin_headers).json()
    bad_user_record = next(u for u in users if u["subject"] == "bad-user")
    client.patch(f"/api/users/{bad_user_record['id']}", json={"is_active": False}, headers=admin_headers)
    
    # 4. Verify BLOCKED
    response = client.get("/api/users", headers=user_headers)
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()
