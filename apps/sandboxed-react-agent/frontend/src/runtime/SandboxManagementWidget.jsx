import React, { useMemo, useState } from "react";
import { 
  Settings, 
  Activity, 
  Terminal, 
  RefreshCw, 
  Zap, 
  Shield, 
  ChevronDown, 
  ChevronUp,
  Info,
  Box,
  HardDrive,
  Clock,
  AlertTriangle,
  CheckCircle2,
  Database
} from "lucide-react";
import "./SandboxManagementWidget.css";

export function SandboxManagementWidget({
  session,
  config,
  onRefreshStatus,
  onUpdatePolicy,
  onRunAction,
  onOpenTerminal,
  loading,
  error,
  readOnly = false,
  canOpenTerminal = true,
  isMobile = false,
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  const sessionStatus = session?.sandbox_status || null;
  const activeRuntime = sessionStatus?.active_runtime || null;
  const effectiveRuntime = sessionStatus?.effective?.runtime || {};
  const workspace = sessionStatus?.workspace_status?.workspace || null;
  const provisioningPending = sessionStatus?.workspace_status?.provisioning_pending;
  
  const currentProfile = activeRuntime?.profile || effectiveRuntime.profile || config?.sandbox_profile || "persistent_workspace";
  const currentTemplate = activeRuntime?.template_name || effectiveRuntime.template_name || config?.sandbox_template_name || "default";
  const currentExecutionModel = activeRuntime?.execution_model || sessionStatus?.effective?.lifecycle?.execution_model || "session";
  
  const fallbackActive = Boolean(activeRuntime?.fallback_active || sessionStatus?.runtime_resolution?.fallback_active);

  const availableSandboxes = sessionStatus?.available_sandboxes || {};
  const availableProfiles = Array.isArray(availableSandboxes.profiles) ? availableSandboxes.profiles : ["persistent_workspace", "transient"];
  const availableExecutionModels = Array.isArray(availableSandboxes.execution_models) ? availableSandboxes.execution_models : ["session", "ephemeral"];
  
  const availableTemplates = useMemo(() => {
    const names = new Set();
    const templates = Array.isArray(availableSandboxes.templates) ? availableSandboxes.templates : [];
    templates.forEach(t => { if (t?.name) names.add(t.name); });
    [session?.sandbox_policy?.template_name, effectiveRuntime.template_name, config?.sandbox_template_name].forEach(v => {
      if (typeof v === "string" && v.trim()) names.add(v.trim());
    });
    return Array.from(names).sort();
  }, [availableSandboxes.templates, config?.sandbox_template_name, session?.sandbox_policy?.template_name, effectiveRuntime.template_name]);

  if (readOnly) return null;

  const getProfileDescription = (profile) => {
    if (profile === "persistent_workspace") return "Saves files in a dedicated cloud bucket. Slower to start the first time.";
    if (profile === "transient") return "Files are deleted after the session ends. Fast startup.";
    return "";
  };

  const getExecutionDescription = (model) => {
    if (model === "session") return "Keeps the same environment (and variables) across multiple messages.";
    if (model === "ephemeral") return "Each tool call starts with a fresh environment.";
    return "";
  };

  const statusColorClass = fallbackActive ? "status-warning" : (activeRuntime ? "status-success" : "status-neutral");

  // Claim info for consolidation
  const sandbox = session?.sandbox || {};
  const activeClaim = sandbox.has_active_claim ? sandbox.claim_name : null;
  const leaseStatus = sandbox?.status || null;

  return (
    <div className={`sandbox-management-widget ${isExpanded ? "expanded" : "collapsed"} ${isMobile ? "mobile" : ""}`}>
      <div 
        className="widget-header" 
        onClick={() => setIsExpanded(!isExpanded)}
        role="button"
        tabIndex={0}
        aria-expanded={isExpanded}
        aria-label="Sandbox runtime configuration"
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setIsExpanded(!isExpanded);
          }
        }}
      >
        <div className="header-main">
          <div className={`status-icon ${statusColorClass}`} style={{ flexShrink: 0 }}>
            {fallbackActive ? <AlertTriangle size={14} /> : (activeRuntime ? <CheckCircle2 size={14} /> : <Activity size={14} />)}
          </div>
          
          <div className="status-compact-row">
            <span className="compact-value">{currentProfile}</span>
            <span className="compact-sep">/</span>
            <span className="compact-value">{currentTemplate}</span>
            
            {activeClaim && (
              <>
                <span className="compact-sep">|</span>
                <span className="compact-value tiny-dim">{activeClaim}</span>
              </>
            )}
            
            {fallbackActive && (
              <span className="badge badge-warning mini-badge">Fallback</span>
            )}
          </div>
        </div>
        <div className="header-actions">
          {loading && <RefreshCw size={12} className="spin" />}
          <Settings size={14} className={`settings-icon ${isExpanded ? "active" : ""}`} />
        </div>
      </div>

      {isExpanded && (
        <div className="widget-body">
          {error && <div className="widget-error"><AlertTriangle size={14} /> {error}</div>}
          
          <div className="widget-grid">
            {/* Status Section */}
            <section className="widget-section">
              <h4 className="section-title"><Activity size={14} /> Runtime Status</h4>
              <div className="info-grid">
                <div className="info-item">
                  <span className="info-label">Workspace</span>
                  <div className="info-value-wrap">
                    <Database size={12} />
                    <span className={`badge ${workspace?.status === "ready" ? "badge-success" : "badge-neutral"}`}>
                      {workspace?.status || "None"}
                    </span>
                  </div>
                </div>
                <div className="info-item">
                  <span className="info-label">Provisioning</span>
                  <span className={`badge ${provisioningPending ? "badge-warning" : "badge-neutral"}`}>
                    {provisioningPending ? "Pending" : "Ready"}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Execution</span>
                  <div className="info-value-wrap">
                    <Clock size={12} />
                    <span>{currentExecutionModel}</span>
                  </div>
                </div>
              </div>
            </section>

            {/* Configuration Section */}
            <section className="widget-section">
              <h4 className="section-title"><Settings size={14} /> Configuration</h4>
              <div className="policy-controls">
                <div className="control-group">
                  <label>
                    Sandbox Profile
                    <select 
                      value={session?.sandbox_policy?.profile || ""} 
                      onChange={(e) => onUpdatePolicy(session.session_id, { profile: e.target.value || null })}
                      disabled={loading}
                    >
                      <option value="">(Inherit: {config?.sandbox_profile})</option>
                      {availableProfiles.map(p => <option key={p} value={p}>{p}</option>)}
                    </select>
                  </label>
                  <p className="control-hint">{getProfileDescription(currentProfile)}</p>
                </div>

                <div className="control-group">
                  <label>
                    Runtime Template
                    <select 
                      value={session?.sandbox_policy?.template_name || ""} 
                      onChange={(e) => onUpdatePolicy(session.session_id, { template_name: e.target.value || null })}
                      disabled={loading}
                    >
                      <option value="">(Inherit: {config?.sandbox_template_name})</option>
                      {availableTemplates.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </label>
                </div>

                <div className="control-group">
                  <label>
                    Execution Model
                    <select 
                      value={session?.sandbox_policy?.execution_model || ""} 
                      onChange={(e) => onUpdatePolicy(session.session_id, { execution_model: e.target.value || null })}
                      disabled={loading}
                    >
                      <option value="">(Inherit)</option>
                      {availableExecutionModels.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>
                  </label>
                  <p className="control-hint">{getExecutionDescription(currentExecutionModel)}</p>
                </div>
              </div>
            </section>

            {/* Actions Section */}
            <section className="widget-section">
              <h4 className="section-title"><Zap size={14} /> Maintenance</h4>
              <div className="actions-grid">
                <button 
                  className="widget-btn" 
                  onClick={() => onRefreshStatus(session.session_id)}
                  disabled={loading}
                >
                  <RefreshCw size={14} /> Refresh Status
                </button>
                <button 
                  className="widget-btn" 
                  onClick={() => onRunAction(session.session_id, "reconcile_workspace", { wait: false })}
                  disabled={loading}
                >
                  <HardDrive size={14} /> Reconcile Workspace
                </button>
                <button 
                  className="widget-btn widget-btn-danger" 
                  onClick={() => onRunAction(session.session_id, "release_lease", { wait: false })}
                  disabled={loading}
                >
                  <Trash2 size={14} /> Release Lease
                </button>
                {canOpenTerminal && (
                  <button 
                    className="widget-btn widget-btn-primary" 
                    onClick={onOpenTerminal}
                    disabled={!session?.session_id}
                  >
                    <Terminal size={14} /> Open Terminal
                  </button>
                )}
              </div>
            </section>
          </div>
          
          <div className="widget-footer">
            <Info size={12} />
            <span>Changes to policy will apply to the next tool call.</span>
          </div>
        </div>
      )}
    </div>
  );
}

function Trash2({ size, className }) {
  // Re-implementing Trash2 locally if lucide doesn't have it or as a fallback
  return (
    <svg 
      width={size} 
      height={size} 
      viewBox="0 0 24 24" 
      fill="none" 
      stroke="currentColor" 
      strokeWidth="2" 
      strokeLinecap="round" 
      strokeLinejoin="round" 
      className={className}
    >
      <path d="M3 6h18m-2 0v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6m3 0V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
      <line x1="10" y1="11" x2="10" y2="17" />
      <line x1="14" y1="11" x2="14" y2="17" />
    </svg>
  );
}
