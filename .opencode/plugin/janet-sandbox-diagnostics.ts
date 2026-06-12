import type { Plugin } from "@opencode-ai/plugin"
import { tool } from "@opencode-ai/plugin"
import { spawn } from "node:child_process"

const z = tool.schema

type CommandResult = {
  command: string
  code: number | null
  stdout: string
  stderr: string
  timedOut: boolean
}

type ToolOptions = {
  namespace: string
  backendDeploy: string
  frontendDeploy: string
  routerDeploy: string
  routerService: string
  since: string
  tail: number
}

const DEFAULTS: ToolOptions = {
  namespace: "alt-default",
  backendDeploy: "sandboxed-react-agent-backend",
  frontendDeploy: "sandboxed-react-agent-frontend",
  routerDeploy: "sandbox-router-deployment",
  routerService: "sandbox-router-svc",
  since: "60m",
  tail: 300,
}

const SHELL_META_CHARS = /[\s"'`$\\]/

function shellQuote(value: string) {
  if (!SHELL_META_CHARS.test(value)) return value
  return `'${value.replaceAll("'", `'\\''`)}'`
}

function commandLine(command: string, args: string[]) {
  return [command, ...args.map(shellQuote)].join(" ")
}

function normalizeOptions(args: Partial<ToolOptions>): ToolOptions {
  return {
    namespace: args.namespace || DEFAULTS.namespace,
    backendDeploy: args.backendDeploy || DEFAULTS.backendDeploy,
    frontendDeploy: args.frontendDeploy || DEFAULTS.frontendDeploy,
    routerDeploy: args.routerDeploy || DEFAULTS.routerDeploy,
    routerService: args.routerService || DEFAULTS.routerService,
    since: args.since || DEFAULTS.since,
    tail: args.tail || DEFAULTS.tail,
  }
}

async function run(command: string, args: string[], signal: AbortSignal, timeoutMs = 30_000): Promise<CommandResult> {
  const line = commandLine(command, args)

  return await new Promise((resolve) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] })
    let stdout = ""
    let stderr = ""
    let settled = false
    let timedOut = false

    const finish = (code: number | null) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      signal.removeEventListener("abort", abort)
      resolve({ command: line, code, stdout, stderr, timedOut })
    }

    const abort = () => {
      timedOut = true
      child.kill("SIGTERM")
      setTimeout(() => child.kill("SIGKILL"), 2_000).unref()
    }

    const timer = setTimeout(abort, timeoutMs)
    signal.addEventListener("abort", abort, { once: true })

    child.stdout.on("data", (chunk) => {
      stdout += String(chunk)
    })
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk)
    })
    child.on("error", (error) => {
      stderr += `${error.name}: ${error.message}\n`
      finish(null)
    })
    child.on("close", finish)
  })
}

async function kubectl(args: string[], signal: AbortSignal, timeoutMs = 30_000) {
  return await run("kubectl", args, signal, timeoutMs)
}

function cap(text: string, maxChars = 18_000) {
  if (text.length <= maxChars) return text.trimEnd()
  return `${text.slice(0, maxChars).trimEnd()}\n\n[truncated ${text.length - maxChars} chars]`
}

function section(title: string, comment: string, body: string) {
  return [`## ${title}`, comment, "", body].join("\n")
}

function resultBlock(result: CommandResult, maxChars?: number) {
  const status = result.timedOut ? "timed out" : result.code === 0 ? "ok" : `exit ${result.code ?? "unknown"}`
  const output = [result.stdout.trimEnd(), result.stderr.trimEnd()].filter(Boolean).join("\n--- stderr ---\n")
  return [`Command: \`${result.command}\` (${status})`, "", "```text", cap(output || "<no output>", maxChars), "```"].join("\n")
}

function parseJson<T>(result: CommandResult): T | null {
  if (result.code !== 0 || !result.stdout.trim()) return null
  try {
    return JSON.parse(result.stdout) as T
  } catch {
    return null
  }
}

function filterLines(text: string, patterns: RegExp[], maxLines = 220) {
  const lines = text.split(/\r?\n/).filter((line) => patterns.some((pattern) => pattern.test(line)))
  return lines.slice(-maxLines).join("\n")
}

function sandboxPodNames(pods: any) {
  const items = Array.isArray(pods?.items) ? pods.items : []
  return items
    .map((item: any) => String(item?.metadata?.name || ""))
    .filter((name: string) => name.startsWith("sandbox-claim-"))
    .slice(0, 6)
}

function detectSignals(inputs: {
  nodesJson?: any
  sandboxText?: string
  podsText?: string
  eventsText?: string
  backendLogText?: string
  routerText?: string
}) {
  const text = [inputs.sandboxText, inputs.podsText, inputs.eventsText, inputs.backendLogText, inputs.routerText]
    .filter(Boolean)
    .join("\n")
  const nodes = Array.isArray(inputs.nodesJson?.items) ? inputs.nodesJson.items : []
  const gvisorNodes = nodes.filter((node: any) => node?.metadata?.labels?.["workload-isolation"] === "gvisor")
  const findings: string[] = []

  if (/SandboxNotReady|Ready=False|Sandbox is not ready/i.test(text)) {
    findings.push("SandboxClaims are present but not Ready, so Janet can wait before tool execution ever starts.")
  }
  if (/Pod exists with phase: Pending|\bPending\b/i.test(text)) {
    findings.push("Sandbox runtime pods are Pending; inspect scheduling before debugging Python execution or router calls.")
  }
  if (/didn'?t match Pod'?s node affinity\/selector|node\(s\) didn'?t match Pod'?s node affinity\/selector/i.test(text)) {
    findings.push("Scheduler reports node affinity/selector mismatch for sandbox runtime pods.")
  }
  if (/max node group size reached/i.test(text)) {
    findings.push("Cluster autoscaler says a relevant node group is already at max size.")
  }
  if (/Insufficient cpu/i.test(text)) {
    findings.push("Cluster autoscaler/scheduler reports insufficient CPU for at least one pending sandbox pod.")
  }
  if (nodes.length > 0 && gvisorNodes.length === 0) {
    findings.push("No current node has label `workload-isolation=gvisor`, while Agent Sandbox runtimes require that selector.")
  }
  if (/lease\.acquire\.watch_failed|pending_released|SandboxNotReady|DependenciesNotReady/i.test(inputs.backendLogText || "")) {
    findings.push("Janet backend logs show sandbox lease acquisition/watch failures or stale pending lease cleanup.")
  }
  if (/sandbox-router-deployment\s+0\/|sandbox router has no ready endpoints|no ready endpoints|connection refused|Request to gateway router failed|Read timed out/i.test(inputs.routerText || "")) {
    findings.push("Router evidence is unhealthy; claims may still create, but execution/file operations will fail through the router.")
  }

  let rootCause = "No single root cause was detected from the collected evidence. Review Pending pods, router readiness, and backend lease logs above."
  if (findings.some((finding) => finding.includes("No current node has label`") || finding.includes("No current node has label")) || /node affinity\/selector/i.test(text)) {
    rootCause = "Most likely root cause: sandbox runtime pods cannot schedule onto a gVisor node. Janet will appear to hang while it waits for sandbox readiness."
  } else if (/sandbox-router-deployment\s+0\/|no ready endpoints|Request to gateway router failed|Read timed out/i.test(inputs.routerText || inputs.backendLogText || "")) {
    rootCause = "Most likely root cause: sandbox router path is unhealthy. Claims may exist, but Janet tool execution cannot reach the runtime."
  } else if (/lease\.acquire\.watch_failed|pending_released/i.test(inputs.backendLogText || "")) {
    rootCause = "Most likely root cause: Janet backend is timing out while waiting for sandbox lease acquisition; inspect the SandboxClaim/Sandbox and pending runtime pod events."
  }

  return { findings, rootCause }
}

async function collectWorkload(options: ToolOptions, signal: AbortSignal) {
  const ns = options.namespace
  const [workloads, pods, routerLogs] = await Promise.all([
    kubectl(["-n", ns, "get", "deploy,svc,ingress"], signal),
    kubectl(["-n", ns, "get", "pods", "-o", "wide"], signal),
    kubectl(["-n", ns, "logs", `deploy/${options.routerDeploy}`, `--tail=${options.tail}`], signal),
  ])
  return { workloads, pods, routerLogs }
}

async function collectScheduling(options: ToolOptions, signal: AbortSignal) {
  const ns = options.namespace
  const [sandboxResources, podsJsonResult, events, nodes, nodesJsonResult] = await Promise.all([
    kubectl(["-n", ns, "get", "sandboxclaim,sandbox,sandboxtemplate,sandboxwarmpool"], signal),
    kubectl(["-n", ns, "get", "pods", "-o", "json"], signal),
    kubectl(["-n", ns, "get", "events", "--sort-by=.lastTimestamp"], signal),
    kubectl(["get", "nodes", "-L", "cloud.google.com/gke-nodepool,workload-isolation"], signal),
    kubectl(["get", "nodes", "-o", "json"], signal),
  ])
  const podsJson = parseJson<any>(podsJsonResult)
  const names = sandboxPodNames(podsJson)
  const podDescribes = await Promise.all(names.map((name) => kubectl(["-n", ns, "describe", "pod", name], signal)))
  const claimYamls = await Promise.all(names.slice(0, 3).map((name) => kubectl(["-n", ns, "get", "sandboxclaim", name, "-o", "yaml"], signal)))
  const sandboxYamls = await Promise.all(names.slice(0, 3).map((name) => kubectl(["-n", ns, "get", "sandbox", name, "-o", "yaml"], signal)))
  return { sandboxResources, podsJsonResult, events, nodes, nodesJsonResult, podDescribes, claimYamls, sandboxYamls, podNames: names }
}

async function collectBackendLogs(options: ToolOptions, signal: AbortSignal, sessionId?: string, claimName?: string) {
  const patterns = [
    /lease\.|sandbox|Sandbox|claim|Claim|tool|execute|timeout|timed out|error|exception|failed|pending_released|watch_failed/i,
  ]
  if (sessionId) patterns.push(new RegExp(sessionId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"))
  if (claimName) patterns.push(new RegExp(claimName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"))
  const logs = await kubectl(["-n", options.namespace, "logs", `deploy/${options.backendDeploy}`, `--since=${options.since}`, `--tail=${options.tail}`], signal, 45_000)
  const filtered = filterLines(logs.stdout, patterns)
  return { logs, filtered }
}

const commonArgs = {
  namespace: z.string().optional().describe("Kubernetes namespace to inspect. Defaults to alt-default."),
  backendDeploy: z.string().optional().describe("Janet backend deployment name."),
  frontendDeploy: z.string().optional().describe("Janet frontend deployment name."),
  routerDeploy: z.string().optional().describe("Sandbox router deployment name."),
  routerService: z.string().optional().describe("Sandbox router service name."),
  since: z.string().optional().describe("Backend log lookback, e.g. 30m, 1h. Defaults to 60m."),
  tail: z.number().int().positive().max(2000).optional().describe("Log tail line count. Defaults to 300."),
}

export default (async () => {
  return {
    tool: {
      janet_sandbox_triage: tool({
        description:
          "Run all read-only Janet sandbox hang diagnostics at once, including app workload health, sandbox scheduling, node labels, events, backend lease logs, and router logs. Returns contextual comments and likely root cause.",
        args: {
          ...commonArgs,
          sessionId: z.string().optional().describe("Optional Janet session UUID to correlate in backend logs."),
          claimName: z.string().optional().describe("Optional SandboxClaim name to correlate in backend logs."),
        },
        async execute(args, context) {
          const options = normalizeOptions(args)
          const [workload, scheduling, backend] = await Promise.all([
            collectWorkload(options, context.abort),
            collectScheduling(options, context.abort),
            collectBackendLogs(options, context.abort, args.sessionId, args.claimName),
          ])
          const nodesJson = parseJson<any>(scheduling.nodesJsonResult)
          const signals = detectSignals({
            nodesJson,
            sandboxText: scheduling.sandboxResources.stdout,
            podsText: `${workload.pods.stdout}\n${scheduling.podDescribes.map((r) => r.stdout).join("\n")}`,
            eventsText: scheduling.events.stdout,
            backendLogText: backend.filtered,
            routerText: `${workload.routerLogs.stdout}\n${workload.workloads.stdout}`,
          })

          const parts = [
            "# Janet Sandbox Triage",
            "This tool mirrors the manual diagnostics for Janet chats that hang while an agent tries to start or use a sandbox. It only runs read-only `kubectl get`, `kubectl describe`, and `kubectl logs` commands.",
            "",
            section("Likely Root Cause", "Derived from scheduling events, SandboxClaim/Sandbox status, node labels, and backend lease logs.", `${signals.rootCause}\n\n${signals.findings.map((finding) => `- ${finding}`).join("\n") || "- No high-confidence signal detected."}`),
            section("Janet Workloads", "Backend/frontend/router readiness and services show whether the app and router are available before looking at sandbox lifecycle.", [resultBlock(workload.workloads), resultBlock(workload.pods)].join("\n\n")),
            section("Sandbox Resources", "Claims and Sandboxes show whether lifecycle has reached Ready. Ready=False with Pending pods points to scheduling or runtime readiness, not chat model output.", resultBlock(scheduling.sandboxResources)),
            section("Nodes", "Agent Sandbox runtime pods normally require gVisor node labels/selectors. If no node has `workload-isolation=gvisor`, runtime pods cannot schedule.", resultBlock(scheduling.nodes)),
            section("Recent Events", "Scheduler/autoscaler events are usually the clearest source for Pending sandbox pods.", resultBlock(scheduling.events, 24_000)),
            section("Sandbox Pod Describes", "Per-pod describes include node selectors, tolerations, runtimeClass, and exact FailedScheduling messages.", scheduling.podDescribes.length ? scheduling.podDescribes.map((r) => resultBlock(r, 16_000)).join("\n\n") : "No current sandbox-claim pods found."),
            section("Claim And Sandbox Status", "YAML status confirms whether the controller created the Sandbox and what dependency is blocking Ready.", [...scheduling.claimYamls, ...scheduling.sandboxYamls].map((r) => resultBlock(r, 14_000)).join("\n\n") || "No current claims/sandboxes found."),
            section("Backend Log Correlation", "Filtered Janet backend logs focus on sandbox lease acquisition, session status polling, timeouts, and errors.", backend.filtered ? `Command: \`${backend.logs.command}\` filtered locally\n\n\`\`\`text\n${cap(backend.filtered, 24_000)}\n\`\`\`` : resultBlock(backend.logs)),
            section("Router Logs", "Router health matters after a sandbox is Ready. If claims are Pending, router logs may only show probes.", resultBlock(workload.routerLogs, 12_000)),
            section("Next Checks", "Use these only if the likely root cause is still unclear.", [
              `- Check gVisor node pool capacity and autoscaling limits for namespace \`${options.namespace}\`.`,
              `- If router is unhealthy, inspect \`kubectl -n ${options.namespace} get endpoints ${options.routerService}\` and router deployment logs.`,
              `- If a specific session is hanging, rerun with \`sessionId\` set to that UUID.`,
            ].join("\n")),
          ]

          return { title: "Janet sandbox triage", output: parts.join("\n\n") }
        },
      }),

      janet_workload_snapshot: tool({
        description: "Read-only snapshot of Janet backend/frontend/router deployments, services, ingress, pods, and router logs with contextual comments.",
        args: commonArgs,
        async execute(args, context) {
          const options = normalizeOptions(args)
          const workload = await collectWorkload(options, context.abort)
          const output = [
            "# Janet Workload Snapshot",
            section("Deployments, Services, Ingress", "These resources establish whether the Janet app and sandbox router are deployed and addressable.", resultBlock(workload.workloads)),
            section("Pods", "Pod readiness, restart counts, and node placement show whether the app itself is healthy.", resultBlock(workload.pods)),
            section("Router Logs", "Mostly health probes are normal. Execution errors here matter only after a sandbox is Ready.", resultBlock(workload.routerLogs, 16_000)),
          ].join("\n\n")
          return { title: "Janet workload snapshot", output }
        },
      }),

      sandbox_runtime_scheduling: tool({
        description: "Read-only Agent Sandbox runtime scheduling diagnostics: claims, sandboxes, pods, node labels, events, and per-pod describes.",
        args: commonArgs,
        async execute(args, context) {
          const options = normalizeOptions(args)
          const scheduling = await collectScheduling(options, context.abort)
          const nodesJson = parseJson<any>(scheduling.nodesJsonResult)
          const signals = detectSignals({
            nodesJson,
            sandboxText: scheduling.sandboxResources.stdout,
            podsText: scheduling.podDescribes.map((r) => r.stdout).join("\n"),
            eventsText: scheduling.events.stdout,
          })
          const output = [
            "# Sandbox Runtime Scheduling",
            section("Scheduling Interpretation", "This summary is derived from Sandbox status, pod phases, node labels, and scheduler/autoscaler events.", `${signals.rootCause}\n\n${signals.findings.map((finding) => `- ${finding}`).join("\n") || "- No high-confidence scheduling signal detected."}`),
            section("Sandbox Resources", "Ready=False or DependenciesNotReady means the controller is blocked before execution can happen.", resultBlock(scheduling.sandboxResources)),
            section("Nodes", "Sandbox runtime pods often require `runtimeClassName=gvisor`, `workload-isolation=gvisor`, and gVisor tolerations.", resultBlock(scheduling.nodes)),
            section("Events", "Look for FailedScheduling, NotTriggerScaleUp, affinity/selector mismatch, max node group size, and insufficient resources.", resultBlock(scheduling.events, 24_000)),
            section("Sandbox Pod Describes", "These show exact selectors/tolerations and the current scheduler reason for each sandbox pod.", scheduling.podDescribes.length ? scheduling.podDescribes.map((r) => resultBlock(r, 18_000)).join("\n\n") : "No current sandbox-claim pods found."),
            section("Claim And Sandbox YAML", "Status fields explain whether the Sandbox object exists and which dependency is not ready.", [...scheduling.claimYamls, ...scheduling.sandboxYamls].map((r) => resultBlock(r, 14_000)).join("\n\n") || "No current claims/sandboxes found."),
          ].join("\n\n")
          return { title: "Sandbox runtime scheduling", output }
        },
      }),

      janet_backend_log_correlation: tool({
        description: "Filter Janet backend logs for sandbox lease, session, claim, timeout, tool execution, and repeated sandbox status polling evidence.",
        args: {
          ...commonArgs,
          sessionId: z.string().optional().describe("Optional Janet session UUID to prioritize in filtered logs."),
          claimName: z.string().optional().describe("Optional SandboxClaim name to prioritize in filtered logs."),
        },
        async execute(args, context) {
          const options = normalizeOptions(args)
          const backend = await collectBackendLogs(options, context.abort, args.sessionId, args.claimName)
          const signals = detectSignals({ backendLogText: backend.filtered })
          const output = [
            "# Janet Backend Log Correlation",
            section("Interpretation", "Lease/watch failures, stale pending leases, and repeated long `/sandbox/status` requests are the backend-side evidence of a chat waiting on sandbox readiness.", `${signals.rootCause}\n\n${signals.findings.map((finding) => `- ${finding}`).join("\n") || "- No high-confidence backend log signal detected."}`),
            section("Filtered Logs", "The command below is run once and then filtered locally for relevant sandbox/session/tool/error terms.", backend.filtered ? `Command: \`${backend.logs.command}\` filtered locally\n\n\`\`\`text\n${cap(backend.filtered, 30_000)}\n\`\`\`` : resultBlock(backend.logs)),
          ].join("\n\n")
          return { title: "Janet backend log correlation", output }
        },
      }),
    },
  }
}) satisfies Plugin
