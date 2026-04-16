import React from "react";
import { Shield } from "lucide-react";

export function Layout({ children }) {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3">
        <Shield className="text-blue-600" size={24} />
        <h1 className="text-xl font-semibold text-gray-900">Cluster Authz Manager</h1>
      </header>
      <main className="flex-1 overflow-auto p-6">
        <div className="max-w-6xl mx-auto h-full">
          {children}
        </div>
      </main>
    </div>
  );
}
