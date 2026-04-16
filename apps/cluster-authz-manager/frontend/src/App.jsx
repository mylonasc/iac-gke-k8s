import React, { useState, useEffect } from "react";
import { apiFetchJson } from "./api/client";
import { Layout } from "./components/Layout";
import { AppSelector } from "./pages/AppSelector";
import { AppDashboard } from "./pages/AppDashboard";
import { UserDirectory } from "./pages/UserDirectory";
import { Users, LayoutGrid } from "lucide-react";

function App() {
  const [view, setView] = useState("apps"); // "apps" or "users"
  const [apps, setApps] = useState([]);
  const [selectedAppSlug, setSelectedAppSlug] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchApps = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiFetchJson("api/apps");
      setApps(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error("Failed to fetch apps", err);
      setApps([]);
      setError(err instanceof Error ? err.message : "Failed to fetch app profiles");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchApps().catch(() => undefined);
  }, []);

  const selectedApp = apps.find(a => a.slug === selectedAppSlug);

  return (
    <Layout>
      <div className="flex flex-col h-full">
        {!selectedAppSlug && (
          <div className="flex gap-4 mb-8 bg-gray-100 p-1 rounded-xl w-fit">
            <button 
              onClick={() => setView("apps")}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold transition-all ${view === "apps" ? "bg-white shadow-sm text-blue-600" : "text-gray-500 hover:text-gray-700"}`}
            >
              <LayoutGrid size={18} /> Applications
            </button>
            <button 
              onClick={() => setView("users")}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold transition-all ${view === "users" ? "bg-white shadow-sm text-blue-600" : "text-gray-500 hover:text-gray-700"}`}
            >
              <Users size={18} /> User Registry
            </button>
          </div>
        )}

        {error ? (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        <div className="flex-1 overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center h-full">
               <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            </div>
          ) : selectedAppSlug ? (
            <AppDashboard 
              app={selectedApp} 
              onBack={() => setSelectedAppSlug(null)} 
            />
          ) : view === "apps" ? (
            <AppSelector apps={apps} onSelect={setSelectedAppSlug} onRefresh={fetchApps} />
          ) : (
            <UserDirectory />
          )}
        </div>
      </div>
    </Layout>
  );
}

export default App;
