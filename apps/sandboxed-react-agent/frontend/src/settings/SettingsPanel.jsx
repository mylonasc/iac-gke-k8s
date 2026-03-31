import React from "react";

export function SettingsPanel({
  apiBase,
  config,
  setConfig,
  configLoading,
  configSaving,
  configError,
  configMessage,
  onReload,
  onSave,
}) {
  const disabled = configLoading || configSaving;

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
    </section>
  );
}
