import React, { useEffect, useMemo, useState } from "react";
import { Check, Copy } from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight, vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";

const languageAliases = {
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  py: "python",
  yml: "yaml",
  md: "markdown",
  plaintext: "text",
  txt: "text",
};

function normalizeLanguage(language) {
  if (!language || typeof language !== "string") return "text";
  const normalized = language.trim().toLowerCase();
  return languageAliases[normalized] || normalized;
}

function useThemeStyle() {
  const [theme, setTheme] = useState(() =>
    typeof document !== "undefined" && document.documentElement.getAttribute("data-theme") === "dark"
      ? "dark"
      : "light"
  );

  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const root = document.documentElement;
    const observer = new MutationObserver(() => {
      setTheme(root.getAttribute("data-theme") === "dark" ? "dark" : "light");
    });
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  return theme === "dark" ? vscDarkPlus : oneLight;
}

export function CodeBlock({ code, language, label, className = "" }) {
  const [copied, setCopied] = useState(false);
  const themeStyle = useThemeStyle();
  const normalizedLanguage = useMemo(() => normalizeLanguage(language), [language]);
  const value = typeof code === "string" ? code.replace(/\n$/, "") : "";

  useEffect(() => {
    if (!copied) return undefined;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const handleCopy = async () => {
    if (!navigator.clipboard?.writeText) return;
    await navigator.clipboard.writeText(value);
    setCopied(true);
  };

  return (
    <div className={`code-block-shell ${className}`.trim()}>
      <div className="code-block-header">
        <span className="code-block-meta">{label || normalizedLanguage}</span>
        <button type="button" className="btn btn-subtle tiny code-copy-button" onClick={handleCopy}>
          {copied ? <Check className="icon-svg" aria-hidden="true" strokeWidth={2} /> : <Copy className="icon-svg" aria-hidden="true" strokeWidth={2} />}
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      <SyntaxHighlighter
        language={normalizedLanguage}
        style={themeStyle}
        showLineNumbers
        wrapLongLines={false}
        customStyle={{ margin: 0, background: "transparent", padding: 0 }}
        codeTagProps={{ className: `language-${normalizedLanguage}` }}
        lineNumberStyle={{ minWidth: "2.5rem", paddingRight: "1rem", opacity: 0.55 }}
      >
        {value || " "}
      </SyntaxHighlighter>
    </div>
  );
}

export function MarkdownCode({ inline, className, children, ...props }) {
  const content = String(children || "").replace(/\n$/, "");
  const matchedLanguage = /language-([\w-]+)/.exec(className || "");

  if (inline) {
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  }

  return <CodeBlock code={content} language={matchedLanguage?.[1]} />;
}
