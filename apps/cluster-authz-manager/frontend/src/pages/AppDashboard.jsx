import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Users,
  ShieldCheck,
  Key,
  Code,
  Plus,
  Trash2,
  X,
  Info,
  HelpCircle,
  Pencil,
} from "lucide-react";
import { apiFetchJson } from "../api/client";

export function AppDashboard({ app, onBack }) {
  const [activeTab, setActiveTab] = useState("roles");
  const [roles, setRoles] = useState([]);
  const [permissions, setPermissions] = useState([]);
  const [groupBindings, setGroupBindings] = useState([]);
  const [userBindings, setUserBindings] = useState([]);
  const [knownUsers, setKnownUsers] = useState([]);
  const [showModal, setShowModal] = useState(null);
  const [selectedRole, setSelectedRole] = useState(null);
  const [selectedCapability, setSelectedCapability] = useState(null);
  const [error, setError] = useState("");

  const loadData = async () => {
    setError("");
    try {
      const [r, p, gb, ub, u] = await Promise.all([
        apiFetchJson(`api/apps/${app.slug}/roles`),
        apiFetchJson(`api/apps/${app.slug}/permissions`),
        apiFetchJson(`api/apps/${app.slug}/bindings/groups`),
        apiFetchJson(`api/apps/${app.slug}/bindings/users`),
        apiFetchJson("api/users"),
      ]);
      setRoles(Array.isArray(r) ? r : []);
      setPermissions(Array.isArray(p) ? p : []);
      setGroupBindings(Array.isArray(gb) ? gb : []);
      setUserBindings(Array.isArray(ub) ? ub : []);
      setKnownUsers(Array.isArray(u) ? u : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load app profile data");
    }
  };

  useEffect(() => {
    loadData().catch(() => undefined);
  }, [app.slug]);

  const permissionUsage = useMemo(() => {
    const usage = new Map();
    roles.forEach((role) => {
      (role.permissions || []).forEach((permission) => {
        const existing = usage.get(permission.id) || [];
        existing.push(role.name);
        usage.set(permission.id, existing);
      });
    });
    return usage;
  }, [roles]);

  const closeModal = () => {
    setShowModal(null);
    setSelectedRole(null);
    setSelectedCapability(null);
  };

  const handleDelete = async (type, id) => {
    let url = "";
    if (type === "role") url = `api/apps/${app.slug}/roles/${id}`;
    if (type === "permission") url = `api/apps/${app.slug}/permissions/${id}`;
    if (type === "group") url = `api/apps/${app.slug}/bindings/groups/${id}`;
    if (type === "user") url = `api/apps/${app.slug}/bindings/users/${id}`;

    let prompt = "Are you sure you want to delete this?";
    if (type === "permission") {
      const usedBy = permissionUsage.get(id) || [];
      prompt = usedBy.length
        ? `Delete this capability? It is currently assigned to ${usedBy.length} role(s): ${usedBy.join(", ")}.`
        : "Delete this capability?";
    }

    if (confirm(prompt)) {
      try {
        await apiFetchJson(url, { method: "DELETE" });
        await loadData();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Delete failed");
      }
    }
  };

  const tabContexts = {
    roles: {
      title: "Roles Catalog",
      description: "Define logical groups of permissions. Roles are assigned to users or groups to grant capabilities within the app.",
      help: "Each role contains a list of 'Capabilities' (permissions) that determine what a user assigned to that role can do."
    },
    groups: {
      title: "Group Mappings",
      description: "Connect identity provider groups (from Dex/OIDC) to specific roles.",
      help: "When a user logs in, their group memberships are checked. If a group matches a mapping here, the user automatically inherits the mapped role."
    },
    users: {
      title: "User Mappings",
      description: "Assign roles directly to individual users based on their Subject (ID) or Email.",
      help: "Direct mappings take precedence and are useful for manual overrides or granting specific administrative access to individuals."
    },
    rules: {
      title: "Policy Configuration Rules",
      description: "Advanced application-specific rules and feature gates.",
      help: "These rules determine how high-level features or sandbox resources are gated based on the capabilities held by the user."
    }
  };

  return (
    <div className="flex flex-col h-full gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button onClick={onBack} className="p-2 hover:bg-gray-200 rounded-full transition-colors">
            <ArrowLeft size={20} />
          </button>
          <div>
            <h2 className="text-2xl font-bold text-gray-900">{app.name}</h2>
            <p className="text-gray-500">Managing {app.slug}</p>
          </div>
        </div>
        <button 
          onClick={() => setShowModal(activeTab)} 
          className="btn btn-primary gap-2"
          disabled={activeTab === "rules"}
        >
          <Plus size={18} /> Add {activeTab.slice(0, -1)}
        </button>
      </div>

      <div className="bg-blue-50 border border-blue-100 p-4 rounded-xl flex items-start gap-3">
        <Info className="text-blue-500 mt-0.5" size={20} />
        <div>
          <h4 className="font-bold text-blue-900 text-sm">{tabContexts[activeTab].title}</h4>
          <p className="text-blue-800 text-sm">{tabContexts[activeTab].description}</p>
        </div>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      <div className="flex border-b border-gray-200">
        <TabButton active={activeTab === "roles"} onClick={() => setActiveTab("roles")} icon={<ShieldCheck size={18}/>} label="Roles" />
        <TabButton active={activeTab === "groups"} onClick={() => setActiveTab("groups")} icon={<Users size={18}/>} label="Group Mappings" />
        <TabButton active={activeTab === "users"} onClick={() => setActiveTab("users")} icon={<Key size={18}/>} label="User Mappings" />
        <TabButton active={activeTab === "rules"} onClick={() => setActiveTab("rules")} icon={<Code size={18}/>} label="App Rules" />
      </div>

      <div className="flex-1 overflow-auto bg-white border border-gray-200 rounded-xl p-6 shadow-sm relative">
        <div className="absolute top-4 right-4 group">
           <HelpCircle className="text-gray-300 hover:text-blue-500 transition-colors cursor-help" size={20} />
           <div className="hidden group-hover:block absolute right-0 top-6 w-64 p-3 bg-gray-900 text-white text-xs rounded-lg shadow-xl z-10 animate-in fade-in zoom-in duration-200">
             {tabContexts[activeTab].help}
           </div>
        </div>

        {activeTab === "roles" && (
          <div className="space-y-8">
            <RolesList
              roles={roles}
              onDelete={(id) => handleDelete("role", id)}
              onEdit={(role) => {
                setSelectedRole(role);
                setShowModal("edit-role");
              }}
              onInspectCapabilities={(role) => {
                setSelectedRole(role);
                setShowModal("view-capabilities");
              }}
            />

            <CapabilitiesCatalog
              permissions={permissions}
              permissionUsage={permissionUsage}
              onCreate={() => setShowModal("new-capability")}
              onEdit={(permission) => {
                setSelectedCapability(permission);
                setShowModal("edit-capability");
              }}
              onDelete={(id) => handleDelete("permission", id)}
            />
          </div>
        )}
        {activeTab === "groups" && <GroupBindingsList bindings={groupBindings} roles={roles} onDelete={(id) => handleDelete("group", id)} />}
        {activeTab === "users" && <UserBindingsList bindings={userBindings} roles={roles} onDelete={(id) => handleDelete("user", id)} />}
        {activeTab === "rules" && (
          <div className="space-y-4">
            <h3 className="text-lg font-semibold">Policy Configuration Rules</h3>
            <pre className="bg-gray-50 p-4 rounded-lg border text-sm">{JSON.stringify(app.config_rules, null, 2)}</pre>
          </div>
        )}
      </div>

      {showModal === "roles" && (
        <Modal title="Create New Role" onClose={() => setShowModal(null)}>
          <RoleForm 
            permissions={permissions} 
            onSubmit={async (data) => {
              try {
                await apiFetchJson(`api/apps/${app.slug}/roles`, {
                  method: "POST",
                  body: JSON.stringify(data)
                });
                closeModal();
                await loadData();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to create role");
              }
            }} 
            submitLabel="Create Role"
          />
        </Modal>
      )}

      {showModal === "edit-role" && selectedRole ? (
        <Modal title={`Edit Role: ${selectedRole.name}`} onClose={closeModal}>
          <RoleForm
            permissions={permissions}
            initialRole={selectedRole}
            submitLabel="Save Changes"
            onSubmit={async (data) => {
              try {
                await apiFetchJson(`api/apps/${app.slug}/roles/${selectedRole.id}`, {
                  method: "PATCH",
                  body: JSON.stringify(data)
                });
                closeModal();
                await loadData();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to update role");
              }
            }}
          />
        </Modal>
      ) : null}

      {showModal === "new-capability" ? (
        <Modal title="Add Capability" onClose={closeModal}>
          <CapabilityForm
            submitLabel="Create Capability"
            onSubmit={async (data) => {
              try {
                await apiFetchJson(`api/apps/${app.slug}/permissions`, {
                  method: "POST",
                  body: JSON.stringify(data)
                });
                closeModal();
                await loadData();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to create capability");
              }
            }}
          />
        </Modal>
      ) : null}

      {showModal === "edit-capability" && selectedCapability ? (
        <Modal title={`Edit Capability`} onClose={closeModal}>
          <CapabilityForm
            initialCapability={selectedCapability}
            submitLabel="Save Changes"
            onSubmit={async (data) => {
              try {
                await apiFetchJson(`api/apps/${app.slug}/permissions/${selectedCapability.id}`, {
                  method: "PATCH",
                  body: JSON.stringify(data)
                });
                closeModal();
                await loadData();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to update capability");
              }
            }}
          />
        </Modal>
      ) : null}

      {showModal === "view-capabilities" && selectedRole ? (
        <Modal title={`Capabilities in ${selectedRole.name}`} onClose={closeModal}>
          <RoleCapabilitiesViewer role={selectedRole} />
        </Modal>
      ) : null}

      {showModal === "groups" && (
        <Modal title="Map Group to Role" onClose={closeModal}>
          <BindingForm 
            roles={roles}
            type="group"
            onSubmit={async (data) => {
              try {
                await apiFetchJson(`api/apps/${app.slug}/bindings/groups`, {
                  method: "POST",
                  body: JSON.stringify(data)
                });
                closeModal();
                await loadData();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to create group mapping");
              }
            }} 
          />
        </Modal>
      )}

      {showModal === "users" && (
        <Modal title="Map User to Role" onClose={closeModal}>
          <BindingForm 
            roles={roles}
            type="user"
            knownUsers={knownUsers}
            onSubmit={async (data) => {
              try {
                await apiFetchJson(`api/apps/${app.slug}/bindings/users`, {
                  method: "POST",
                  body: JSON.stringify(data)
                });
                closeModal();
                await loadData();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to create user mapping");
              }
            }} 
          />
        </Modal>
      )}
    </div>
  );
}

function Modal({ title, children, onClose }) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-bold">{title}</h3>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded"><X size={20}/></button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}

function RoleForm({ permissions, initialRole = null, submitLabel = "Save", onSubmit }) {
  const [name, setName] = useState(initialRole?.name || "");
  const [description, setDescription] = useState(initialRole?.description || "");
  const [query, setQuery] = useState("");
  const [selectedPerms, setSelectedPerms] = useState(
    Array.isArray(initialRole?.permissions)
      ? initialRole.permissions.map((permission) => permission.id)
      : []
  );

  useEffect(() => {
    setName(initialRole?.name || "");
    setDescription(initialRole?.description || "");
    setQuery("");
    setSelectedPerms(
      Array.isArray(initialRole?.permissions)
        ? initialRole.permissions.map((permission) => permission.id)
        : []
    );
  }, [initialRole]);

  const filteredPermissions = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return permissions;
    return permissions.filter((permission) => {
      const haystack = `${permission.name} ${permission.description || ""}`.toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [permissions, query]);

  const togglePermission = (permissionId) => {
    if (selectedPerms.includes(permissionId)) {
      setSelectedPerms(selectedPerms.filter((id) => id !== permissionId));
      return;
    }
    setSelectedPerms([...selectedPerms, permissionId]);
  };

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          name,
          description: description || null,
          permission_ids: selectedPerms,
        });
      }}
    >
      <div className="control-group">
        <label className="block text-sm font-medium mb-1">Role Name</label>
        <input value={name} onChange={e => setName(e.target.value)} className="w-full border rounded-lg p-2" required placeholder="e.g. data_scientist" />
      </div>

      <div className="control-group">
        <label className="block text-sm font-medium mb-1">Description</label>
        <textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          className="w-full border rounded-lg p-2 min-h-[80px]"
          placeholder="Optional: describe who should use this role"
        />
      </div>

      <div className="control-group">
        <div className="flex items-center justify-between mb-1">
          <label className="block text-sm font-medium">Capabilities</label>
          <span className="text-xs text-gray-500">{selectedPerms.length} selected</span>
        </div>

        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="w-full border rounded-lg p-2 text-sm mb-2"
          placeholder="Search capabilities..."
        />

        <div className="max-h-64 overflow-y-auto border rounded-lg p-2 space-y-2">
          {filteredPermissions.map((permission) => (
            <label
              key={permission.id}
              className="flex items-start gap-3 text-sm hover:bg-gray-50 p-2 rounded cursor-pointer"
            >
              <input
                className="mt-0.5"
                type="checkbox"
                checked={selectedPerms.includes(permission.id)}
                onChange={() => togglePermission(permission.id)}
              />
              <span className="min-w-0 flex-1">
                <span className="block font-mono text-xs text-gray-800 break-all leading-relaxed">
                  {permission.name}
                </span>
                {permission.description ? (
                  <span className="block text-xs text-gray-500 mt-1 whitespace-pre-wrap break-words leading-relaxed">
                    {permission.description}
                  </span>
                ) : null}
              </span>
            </label>
          ))}

          {filteredPermissions.length === 0 ? (
            <p className="text-xs text-gray-500 px-2 py-3">No capabilities match your search.</p>
          ) : null}
        </div>
      </div>

      <button type="submit" className="btn btn-primary w-full">{submitLabel}</button>
    </form>
  );
}

function CapabilityForm({ initialCapability = null, submitLabel = "Save", onSubmit }) {
  const [name, setName] = useState(initialCapability?.name || "");
  const [description, setDescription] = useState(initialCapability?.description || "");

  useEffect(() => {
    setName(initialCapability?.name || "");
    setDescription(initialCapability?.description || "");
  }, [initialCapability]);

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ name, description: description || null });
      }}
    >
      <div className="control-group">
        <label className="block text-sm font-medium mb-1">Capability Name</label>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          className="w-full border rounded-lg p-2 font-mono text-sm"
          required
          placeholder="e.g. sandbox.template.python-runtime-template-pydata"
        />
      </div>

      <div className="control-group">
        <label className="block text-sm font-medium mb-1">Description</label>
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          className="w-full border rounded-lg p-2 min-h-[80px]"
          placeholder="Optional: explain what this capability enables"
        />
      </div>

      <button type="submit" className="btn btn-primary w-full">{submitLabel}</button>
    </form>
  );
}

function BindingForm({ roles, type, knownUsers = [], onSubmit }) {
  const [identifier, setIdentifier] = useState("");
  const [idType, setIdType] = useState("sub");
  const [roleId, setRoleId] = useState(roles[0]?.id || "");

  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); onSubmit(type === "group" ? { group_name: identifier, role_id: roleId } : { user_identifier: identifier, identifier_type: idType, role_id: roleId }); }}>
      <div className="control-group">
        <label className="block text-sm font-medium mb-1 group relative flex items-center gap-1">
          {type === "group" ? "Dex Group Name" : "User Identifier"}
          <HelpCircle size={14} className="text-gray-400" />
          <div className="hidden group-hover:block absolute left-0 bottom-full mb-1 w-64 p-2 bg-gray-800 text-white text-[10px] rounded shadow-lg z-20">
            {type === "group" ? "The group name as received from the identity provider (e.g. 'admins')" : "The user's unique ID (sub) or email address."}
          </div>
        </label>
        
        {type === "user" && knownUsers.length > 0 ? (
          <div className="space-y-2 mb-3">
            <select 
              className="w-full border rounded-lg p-2 bg-blue-50 border-blue-200 text-sm" 
              onChange={e => {
                const u = knownUsers.find(u => u.id === e.target.value);
                if (u) {
                  setIdentifier(u.subject);
                  setIdType("sub");
                }
              }}
            >
              <option value="">Select a known user...</option>
              {knownUsers.map(u => (
                <option key={u.id} value={u.id}>{u.email || u.subject} ({u.subject.slice(0, 8)}...)</option>
              ))}
            </select>
            <div className="text-xs text-gray-400 text-center uppercase tracking-wider font-bold">OR enter manually</div>
          </div>
        ) : null}

        <input value={identifier} onChange={e => setIdentifier(e.target.value)} className="w-full border rounded-lg p-2" required placeholder={type === "group" ? "e.g. admins" : "e.g. user@example.com"} />
      </div>
      {type === "user" && (
        <div className="control-group">
          <label className="block text-sm font-medium mb-1">Identifier Type</label>
          <select value={idType} onChange={e => setIdType(e.target.value)} className="w-full border rounded-lg p-2">
            <option value="sub">Subject (Sub)</option>
            <option value="email">Email</option>
          </select>
        </div>
      )}
      <div className="control-group">
        <label className="block text-sm font-medium mb-1">Assigned Role</label>
        <select value={roleId} onChange={e => setRoleId(e.target.value)} className="w-full border rounded-lg p-2" required>
          <option value="" disabled>Select a role...</option>
          {roles.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
      </div>
      <button type="submit" className="btn btn-primary w-full">Add Mapping</button>
    </form>
  );
}

function TabButton({ active, onClick, icon, label }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-6 py-3 border-b-2 font-medium transition-all ${
        active ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function RolesList({ roles, onDelete, onEdit, onInspectCapabilities }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-700">Roles Catalog</h3>
      </div>
      <div className="overflow-hidden border border-gray-200 rounded-xl shadow-sm">
        <table className="w-full table-fixed text-left bg-white">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wider">
            <tr>
              <th className="px-6 py-3 font-semibold w-[24%]">Role Name</th>
              <th className="px-6 py-3 font-semibold w-[56%]">Capabilities</th>
              <th className="px-6 py-3 font-semibold text-right w-[20%]">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {roles.map(role => (
              <tr key={role.id} className="hover:bg-gray-50 transition-colors">
                <td className="px-6 py-4 align-top">
                  <div className="font-bold text-gray-900">{role.name}</div>
                  {role.description && <div className="text-xs text-gray-500 mt-1">{role.description}</div>}
                </td>
                <td className="px-6 py-4 align-top">
                  <CapabilityPreview permissions={role.permissions || []} onInspect={() => onInspectCapabilities(role)} />
                </td>
                <td className="px-6 py-4 text-right align-top">
                  <div className="inline-flex items-center gap-1">
                    <button
                      onClick={() => onEdit(role)}
                      className="text-gray-400 hover:text-blue-600 transition-colors p-1.5 hover:bg-blue-50 rounded-lg"
                      title="Edit role"
                    >
                      <Pencil size={16} />
                    </button>
                    <button
                      onClick={() => onDelete(role.id)}
                      className="text-gray-400 hover:text-red-500 transition-colors p-1.5 hover:bg-red-50 rounded-lg"
                      title="Delete role"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}

            {roles.length === 0 ? (
              <tr>
                <td className="px-6 py-5 text-sm text-gray-500" colSpan={3}>No roles defined yet.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CapabilityPreview({ permissions, onInspect }) {
  const preview = permissions.slice(0, 4);
  const hiddenCount = Math.max(0, permissions.length - preview.length);

  if (permissions.length === 0) {
    return <span className="text-xs text-gray-400">No capabilities assigned.</span>;
  }

  return (
    <div className="space-y-2 min-w-0">
      <div className="flex flex-wrap gap-2 min-w-0">
        {preview.map((permission) => (
          <span
            key={permission.id}
            className="inline-flex max-w-full items-center px-2 py-1 rounded border border-blue-100 bg-blue-50 text-blue-700 text-xs font-semibold leading-relaxed break-all"
            title={permission.description || permission.name}
          >
            {permission.name}
          </span>
        ))}
      </div>

      {hiddenCount > 0 ? (
        <button
          onClick={onInspect}
          className="text-xs font-medium text-blue-600 hover:text-blue-700"
        >
          +{hiddenCount} more capabilities
        </button>
      ) : null}
    </div>
  );
}

function CapabilitiesCatalog({ permissions, permissionUsage, onCreate, onEdit, onDelete }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-700">Capabilities Catalog</h3>
        <button type="button" className="btn btn-secondary gap-2" onClick={onCreate}>
          <Plus size={16} /> Add capability
        </button>
      </div>

      <div className="overflow-hidden border border-gray-200 rounded-xl shadow-sm">
        <table className="w-full table-fixed text-left bg-white">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wider">
            <tr>
              <th className="px-6 py-3 font-semibold w-[38%]">Capability</th>
              <th className="px-6 py-3 font-semibold w-[34%]">Description</th>
              <th className="px-6 py-3 font-semibold w-[18%]">Used by roles</th>
              <th className="px-6 py-3 font-semibold text-right w-[10%]">Actions</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-gray-200">
            {permissions.map((permission) => {
              const roleNames = permissionUsage.get(permission.id) || [];
              return (
                <tr key={permission.id} className="hover:bg-gray-50 transition-colors align-top">
                  <td className="px-6 py-4">
                    <div className="font-mono text-xs text-gray-900 break-all leading-relaxed">{permission.name}</div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-xs text-gray-600 whitespace-pre-wrap break-words leading-relaxed">
                      {permission.description || "—"}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    {roleNames.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {roleNames.map((roleName) => (
                          <span
                            key={`${permission.id}-${roleName}`}
                            className="px-2 py-0.5 rounded border border-gray-200 bg-gray-100 text-gray-700 text-[10px] font-semibold"
                          >
                            {roleName}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-gray-400">Unused</span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => onEdit(permission)}
                        className="text-gray-400 hover:text-blue-600 transition-colors p-1.5 hover:bg-blue-50 rounded-lg"
                        title="Edit capability"
                      >
                        <Pencil size={16} />
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete(permission.id)}
                        className="text-gray-400 hover:text-red-500 transition-colors p-1.5 hover:bg-red-50 rounded-lg"
                        title="Delete capability"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}

            {permissions.length === 0 ? (
              <tr>
                <td className="px-6 py-5 text-sm text-gray-500" colSpan={4}>No capabilities defined yet.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RoleCapabilitiesViewer({ role }) {
  const permissions = Array.isArray(role.permissions) ? role.permissions : [];

  return (
    <div className="space-y-3 max-h-[60vh] overflow-y-auto">
      {permissions.length === 0 ? (
        <p className="text-sm text-gray-500">No capabilities assigned to this role.</p>
      ) : (
        permissions.map((permission) => (
          <div key={permission.id} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
            <p className="font-mono text-xs text-gray-900 break-all leading-relaxed">{permission.name}</p>
            {permission.description ? (
              <p className="text-xs text-gray-600 mt-2 whitespace-pre-wrap break-words leading-relaxed">
                {permission.description}
              </p>
            ) : null}
          </div>
        ))
      )}
    </div>
  );
}

function GroupBindingsList({ bindings, roles, onDelete }) {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-700">Group to Role Mappings</h3>
      <div className="overflow-hidden border border-gray-200 rounded-xl shadow-sm">
        <table className="w-full text-left bg-white">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wider">
            <tr>
              <th className="px-6 py-3 font-semibold">Dex Group</th>
              <th className="px-6 py-3 font-semibold">Mapped Role</th>
              <th className="px-6 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {bindings.map(b => (
              <tr key={b.id} className="hover:bg-gray-50 transition-colors group">
                <td className="px-6 py-4 font-mono text-sm text-gray-900">{b.group_name}</td>
                <td className="px-6 py-4">
                  <span className="px-2.5 py-1 bg-gray-100 text-gray-700 rounded-lg text-xs font-bold border border-gray-200">
                    {roles.find(r => r.id === b.role_id)?.name}
                  </span>
                </td>
                <td className="px-6 py-4 text-right">
                  <button onClick={() => onDelete(b.id)} className="text-gray-300 hover:text-red-600 opacity-0 group-hover:opacity-100 transition-all p-1.5 hover:bg-red-50 rounded-lg">
                    <Trash2 size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UserBindingsList({ bindings, roles, onDelete }) {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-700">User to Role Mappings</h3>
      <div className="overflow-hidden border border-gray-200 rounded-xl shadow-sm">
        <table className="w-full text-left bg-white">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wider">
            <tr>
              <th className="px-6 py-3 font-semibold">Identifier</th>
              <th className="px-6 py-3 font-semibold">Type</th>
              <th className="px-6 py-3 font-semibold">Mapped Role</th>
              <th className="px-6 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {bindings.map(b => (
              <tr key={b.id} className="hover:bg-gray-50 transition-colors group">
                <td className="px-6 py-4 font-mono text-sm text-gray-900">{b.user_identifier}</td>
                <td className="px-6 py-4 text-xs text-gray-500 uppercase font-bold tracking-tight">{b.identifier_type}</td>
                <td className="px-6 py-4">
                  <span className="px-2.5 py-1 bg-gray-100 text-gray-700 rounded-lg text-xs font-bold border border-gray-200">
                    {roles.find(r => r.id === b.role_id)?.name}
                  </span>
                </td>
                <td className="px-6 py-4 text-right">
                  <button onClick={() => onDelete(b.id)} className="text-gray-300 hover:text-red-600 opacity-0 group-hover:opacity-100 transition-all p-1.5 hover:bg-red-50 rounded-lg">
                    <Trash2 size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
