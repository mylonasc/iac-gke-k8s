import React, { useState } from "react";
import { ChevronRight, Plus, X, Info } from "lucide-react";
import { apiFetchJson } from "../api/client";

export function AppSelector({ apps, onSelect, onRefresh }) {
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState("");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="header">
          <h2 className="text-2xl font-bold text-gray-900">Select an Application</h2>
          <p className="text-gray-500">Manage roles and permissions for your cluster services.</p>
        </div>
        <button onClick={() => setShowModal(true)} className="btn btn-primary gap-2">
          <Plus size={18} /> New App Profile
        </button>
      </div>

      <div className="bg-blue-50 border border-blue-100 p-4 rounded-xl flex items-start gap-3">
        <Info className="text-blue-500 mt-0.5" size={20} />
        <div>
          <h4 className="font-bold text-blue-900 text-sm">Policy Governance</h4>
          <p className="text-blue-800 text-sm">Select an application to define its roles and capabilities. These policies are fetched by the applications at runtime to enforce authorization.</p>
        </div>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {apps.map(app => (
          <button
            key={app.slug}
            onClick={() => onSelect(app.slug)}
            className="flex items-center justify-between p-6 bg-white border border-gray-200 rounded-xl hover:border-blue-500 hover:shadow-md transition-all group"
          >
            <div className="text-left">
              <h3 className="font-semibold text-lg text-gray-900">{app.name}</h3>
              <p className="text-sm text-gray-500">{app.slug}</p>
            </div>
            <ChevronRight className="text-gray-300 group-hover:text-blue-500" />
          </button>
        ))}
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-bold">Create New App Profile</h3>
              <button onClick={() => setShowModal(false)} className="p-1 hover:bg-gray-100 rounded"><X size={20}/></button>
            </div>
            <div className="p-6">
              <CreateAppForm 
                onSubmit={async (data) => {
                  try {
                    await apiFetchJson("api/apps", {
                      method: "POST",
                      body: JSON.stringify(data)
                    });
                    setShowModal(false);
                    setError("");
                    await onRefresh();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Failed to create app profile");
                  }
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CreateAppForm({ onSubmit }) {
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); onSubmit({ slug, name, description }); }}>
      <div className="control-group">
        <label className="block text-sm font-medium mb-1">App Slug (unique ID)</label>
        <input value={slug} onChange={e => setSlug(e.target.value)} className="w-full border rounded-lg p-2" required placeholder="e.g. custom-service" />
      </div>
      <div className="control-group">
        <label className="block text-sm font-medium mb-1">Display Name</label>
        <input value={name} onChange={e => setName(e.target.value)} className="w-full border rounded-lg p-2" required placeholder="e.g. Custom Service" />
      </div>
      <div className="control-group">
        <label className="block text-sm font-medium mb-1">Description</label>
        <textarea value={description} onChange={e => setDescription(e.target.value)} className="w-full border rounded-lg p-2" placeholder="What does this app do?" />
      </div>
      <button type="submit" className="btn btn-primary w-full">Create Profile</button>
    </form>
  );
}
