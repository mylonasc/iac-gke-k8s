import React from "react";

export function SettingsPanel({
  apiBase,
  config,
  setConfig,
  configLoading,
  configSaving,
  configError,
  configMessage,
  adminOpsData,
  adminOpsError,
  adminOpsLoading,
  onReload,
  onLoadAdminOps,
  onSave,
}) {
  const disabled = configLoading || configSaving;
  const workspaceJobs = adminOpsData?.workspaceJobs || null;
  const sandboxIndex = adminOpsData?.sandboxIndex || null;
  const jobRows = Array.isArray(workspaceJobs?.jobs) ? workspaceJobs.jobs.slice(0, 20) : [];

  return (
    <section className="panel settings-panel">
      <div className="panel-header">
        <h3>Backend Configuration</h3>
      </div>
      <p className="settings-base-url">
        API base: <code>{apiBase}</code>
      </p>
      <form className="settings-grid" onSubmit={onSave}>
        <label>
          Model
          <input
            type="text"
            value={config.model}
            onChange={(event) => setConfig((prev) => ({ ...prev, model: event.target.value }))}
            disabled={disabled}
          />
        </label>
        <label>
          Max tool calls per turn
          <input
            type="number"
            min={1}
            max={20}
            value={config.max_tool_calls_per_turn}
            onChange={(event) =>
              setConfig((prev) => ({ ...prev, max_tool_calls_per_turn: event.target.value }))
            }
            disabled={disabled}
          />
        </label>
        <label>
          Sandbox mode
          <select
            value={config.sandbox_mode}
            onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_mode: event.target.value }))}
            disabled={disabled}
          >
            <option value="local">local</option>
            <option value="cluster">cluster</option>
          </select>
        </label>
        <label>
          Sandbox profile
          <select
            value={config.sandbox_profile}
            onChange={(event) =>
              setConfig((prev) => ({ ...prev, sandbox_profile: event.target.value }))
            }
            disabled={disabled}
          >
            <option value="persistent_workspace">persistent_workspace</option>
            <option value="transient">transient</option>
          </select>
        </label>
        <label>
          Sandbox API URL
          <input
            type="text"
            value={config.sandbox_api_url}
            onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_api_url: event.target.value }))}
            disabled={disabled}
          />
        </label>
        <label>
          Template name
          <input
            type="text"
            value={config.sandbox_template_name}
            onChange={(event) =>
              setConfig((prev) => ({ ...prev, sandbox_template_name: event.target.value }))
            }
            disabled={disabled}
          />
        </label>
        {config.sandbox_profile !== "transient" ? (
          <p className="settings-help-text">
            Template is primarily used by transient profile; persistent profile resolves
            user workspace template dynamically.
          </p>
        ) : null}
        <label>
          Namespace
          <input
            type="text"
            value={config.sandbox_namespace}
            onChange={(event) => setConfig((prev) => ({ ...prev, sandbox_namespace: event.target.value }))}
            disabled={disabled}
          />
        </label>
        <label>
          Sandbox server port
          <input
            type="number"
            min={1}
            max={65535}
            value={config.sandbox_server_port}
            onChange={(event) =>
              setConfig((prev) => ({ ...prev, sandbox_server_port: event.target.value }))
            }
            disabled={disabled}
          />
        </label>
        <label>
          Max output chars
          <input
            type="number"
            min={100}
            max={100000}
            value={config.sandbox_max_output_chars}
            onChange={(event) =>
              setConfig((prev) => ({ ...prev, sandbox_max_output_chars: event.target.value }))
            }
            disabled={disabled}
          />
        </label>
        <label>
          Local timeout seconds
          <input
            type="number"
            min={1}
            max={600}
            value={config.sandbox_local_timeout_seconds}
            onChange={(event) =>
              setConfig((prev) => ({ ...prev, sandbox_local_timeout_seconds: event.target.value }))
            }
            disabled={disabled}
          />
        </label>
        <div className="settings-actions">
          <button type="button" className="btn btn-subtle" onClick={onReload} disabled={disabled}>
            {configLoading ? "Loading..." : "Reload"}
          </button>
          <button type="submit" className="btn btn-primary" disabled={disabled}>
            {configSaving ? "Saving..." : "Save"}
          </button>
        </div>
      </form>
      {configError ? <p className="feedback feedback-error">{configError}</p> : null}
      {configMessage ? <p className="feedback feedback-success">{configMessage}</p> : null}

      <section className="admin-ops-section">
        <div className="admin-ops-header">
          <h4>Admin Ops</h4>
          <button
            type="button"
            className="btn btn-subtle"
            onClick={onLoadAdminOps}
            disabled={adminOpsLoading}
          >
            {adminOpsLoading ? "Loading..." : "Load Ops Snapshot"}
          </button>
        </div>

        {adminOpsError ? <p className="feedback feedback-error">{adminOpsError}</p> : null}

        {workspaceJobs ? (
          <div className="admin-ops-grid">
            <div className="admin-ops-card">
              <h5>Workspace Jobs</h5>
              <p>
                total: <strong>{workspaceJobs?.summary?.total_jobs ?? 0}</strong> | queued: <strong>{workspaceJobs?.summary?.queued_jobs ?? 0}</strong> | running: <strong>{workspaceJobs?.summary?.running_jobs ?? 0}</strong> | failed: <strong>{workspaceJobs?.summary?.failed_jobs ?? 0}</strong>
              </p>
              <p>
                stale running: <strong>{workspaceJobs?.summary?.stale_running_jobs ?? 0}</strong>
              </p>
            </div>
            <div className="admin-ops-card">
              <h5>Sandbox Leases</h5>
              <p>
                active: <strong>{sandboxIndex?.summary?.active_leases ?? 0}</strong> | unhealthy: <strong>{sandboxIndex?.summary?.unhealthy_active_leases ?? 0}</strong>
              </p>
              <p>
                workspace total: <strong>{sandboxIndex?.summary?.workspace_total ?? 0}</strong>
              </p>
            </div>
          </div>
        ) : null}

        {jobRows.length > 0 ? (
          <div className="admin-jobs-table-wrap">
            <table className="admin-jobs-table">
              <thead>
                <tr>
                  <th>job</th>
                  <th>status</th>
                  <th>user</th>
                  <th>workspace</th>
                  <th>attempts</th>
                  <th>age(s)</th>
                  <th>error</th>
                </tr>
              </thead>
              <tbody>
                {jobRows.map((job) => (
                  <tr key={job.job_id}>
                    <td><code>{job.job_id}</code></td>
                    <td>{job.status}</td>
                    <td>{job.user_id || "-"}</td>
                    <td>{job.workspace_status || "-"}</td>
                    <td>{job.attempt_count ?? 0}</td>
                    <td>{job.age_seconds ?? "-"}</td>
                    <td className="admin-jobs-error">{job.last_error || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </section>
  );
}
