import React from "react";
import { SANDBOX_TEMPLATES } from "../constants/sandboxTemplates";

export function RuntimePicker({ value, onChange, disabled, disabledReason = "" }) {
  return (
    <section className="panel runtime-panel">
      <div className="panel-header">
        <h3>Sandbox Runtime</h3>
      </div>
      {disabledReason ? <p className="runtime-note">{disabledReason}</p> : null}
      <div className="runtime-list" role="radiogroup" aria-label="Sandbox templates">
        {SANDBOX_TEMPLATES.map((template) => (
          <label key={template.value} className={`runtime-option ${value === template.value ? "is-active" : ""}`}>
            <input
              type="radio"
              name="sandbox-template"
              value={template.value}
              checked={value === template.value}
              onChange={() => onChange(template.value)}
              disabled={disabled}
            />
            <span>
              <strong>{template.label}</strong>
              <small>{template.description}</small>
            </span>
          </label>
        ))}
      </div>
    </section>
  );
}
