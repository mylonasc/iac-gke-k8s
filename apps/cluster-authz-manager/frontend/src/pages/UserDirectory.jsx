import React, { useState, useEffect } from "react";
import { Search, UserPlus, Trash2, UserX, UserCheck, Mail, Fingerprint, Calendar, Info, X } from "lucide-react";
import { apiFetchJson } from "../api/client";

export function UserDirectory({ onBack }) {
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState("");

  const fetchUsers = async () => {
    setLoading(true);
    setError("");
    const url = search ? `api/users?q=${encodeURIComponent(search)}` : "api/users";
    try {
      const data = await apiFetchJson(url);
      setUsers(Array.isArray(data) ? data : []);
    } catch (err) {
      setUsers([]);
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchUsers().catch(() => undefined);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const toggleStatus = async (user) => {
    try {
      await apiFetchJson(`api/users/${user.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !user.is_active })
      });
      await fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update user status");
    }
  };

  const deleteUser = async (user) => {
    if (confirm(`Remove ${user.email || user.subject} from registry? This does NOT delete their OIDC identity, only their local metadata and specific bindings.`)) {
      try {
        await apiFetchJson(`api/users/${user.id}`, { method: "DELETE" });
        await fetchUsers();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to delete user");
      }
    }
  };

  return (
    <div className="flex flex-col h-full gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">User Registry</h2>
          <p className="text-gray-500">Manage cluster-wide identities and access status.</p>
        </div>
        <button onClick={() => setShowModal(true)} className="btn btn-primary gap-2">
          <UserPlus size={18} /> Provision User
        </button>
      </div>

      <div className="bg-blue-50 border border-blue-100 p-4 rounded-xl flex items-start gap-3">
        <Info className="text-blue-500 mt-0.5" size={20} />
        <div>
          <h4 className="font-bold text-blue-900 text-sm">Identity Governance</h4>
          <p className="text-blue-800 text-sm">Users are automatically added when they first log in. Disabling a user here acts as a global kill-switch for all apps using this manager.</p>
        </div>
      </div>

      {error ? (
        <div className="bg-red-50 border border-red-100 p-3 rounded-xl text-sm text-red-700">
          {error}
        </div>
      ) : null}

      <div className="flex items-center gap-4 bg-white p-4 border border-gray-200 rounded-xl shadow-sm">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
          <input 
            value={search} 
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by email, subject, or name..." 
            className="w-full pl-10 pr-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
          />
        </div>
      </div>

      <div className="flex-1 overflow-auto bg-white border border-gray-200 rounded-xl shadow-sm">
        <table className="w-full text-left">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wider sticky top-0">
            <tr>
              <th className="px-6 py-3 font-semibold">User</th>
              <th className="px-6 py-3 font-semibold">Status</th>
              <th className="px-6 py-3 font-semibold">Identifiers</th>
              <th className="px-6 py-3 font-semibold">Activity</th>
              <th className="px-6 py-3 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {loading ? (
               <tr><td colSpan="5" className="px-6 py-10 text-center text-gray-400">Loading registry...</td></tr>
            ) : users.length === 0 ? (
               <tr><td colSpan="5" className="px-6 py-10 text-center text-gray-400">No users found.</td></tr>
            ) : users.map(user => (
              <tr key={user.id} className={`hover:bg-gray-50 transition-colors ${!user.is_active ? "bg-gray-50/50" : ""}`}>
                <td className="px-6 py-4">
                  <div className="font-bold text-gray-900">{user.display_name || "Unknown Name"}</div>
                  <div className="text-xs text-gray-500 flex items-center gap-1 mt-0.5">
                    <Mail size={12}/> {user.email || "No email"}
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className={`px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider flex items-center w-fit gap-1 ${
                    user.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                  }`}>
                    {user.is_active ? <UserCheck size={12}/> : <UserX size={12}/>}
                    {user.is_active ? "Active" : "Disabled"}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <div className="text-xs font-mono text-gray-500 flex items-center gap-1">
                    <Fingerprint size={12}/> {user.subject}
                  </div>
                </td>
                <td className="px-6 py-4">
                  <div className="text-xs text-gray-500 flex items-center gap-1">
                    <Calendar size={12}/> Seen: {new Date(user.last_seen_at).toLocaleString()}
                  </div>
                </td>
                <td className="px-6 py-4 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <button 
                      onClick={() => toggleStatus(user)}
                      title={user.is_active ? "Disable User" : "Enable User"}
                      className={`p-1.5 rounded-lg transition-colors ${user.is_active ? "text-gray-400 hover:text-orange-600 hover:bg-orange-50" : "text-gray-400 hover:text-green-600 hover:bg-green-50"}`}
                    >
                      {user.is_active ? <UserX size={18} /> : <UserCheck size={18} />}
                    </button>
                    <button 
                      onClick={() => deleteUser(user)}
                      title="Delete Metadata"
                      className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                    >
                      <Trash2 size={18} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showModal && (
        <Modal title="Provision New User" onClose={() => setShowModal(false)}>
          <ProvisionUserForm 
            onSubmit={async (data) => {
              try {
                await apiFetchJson("api/users", {
                  method: "POST",
                  body: JSON.stringify(data)
                });
                setShowModal(false);
                await fetchUsers();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to register user");
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

function ProvisionUserForm({ onSubmit }) {
  const [subject, setSubject] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");

  return (
    <form className="space-y-4" onSubmit={e => { e.preventDefault(); onSubmit({ subject, email, display_name: name }); }}>
      <p className="text-xs text-gray-500 mb-4">
        Pre-register a user by their OIDC Subject or Email. They will inherit their configured roles as soon as they log in.
      </p>
      <div className="control-group">
        <label className="block text-sm font-medium mb-1">OIDC Subject (sub) *</label>
        <input value={subject} onChange={e => setSubject(e.target.value)} className="w-full border rounded-lg p-2" required placeholder="Unique ID from provider" />
      </div>
      <div className="control-group">
        <label className="block text-sm font-medium mb-1">Email Address</label>
        <input value={email} onChange={e => setEmail(e.target.value)} type="email" className="w-full border rounded-lg p-2" placeholder="user@example.com" />
      </div>
      <div className="control-group">
        <label className="block text-sm font-medium mb-1">Display Name</label>
        <input value={name} onChange={e => setName(e.target.value)} className="w-full border rounded-lg p-2" placeholder="Full Name" />
      </div>
      <button type="submit" className="btn btn-primary w-full">Register User</button>
    </form>
  );
}
