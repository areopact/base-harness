// Internal helpers for the OpenCode plugin bridge (harness/adapters/opencode/plugins/harness-bridge.js).
//
// This file lives outside harness/adapters/opencode/plugins/ on purpose:
// that directory is linked whole into .opencode/plugins/, and OpenCode calls
// every export of every file it finds there as a plugin factory. A helper
// export here (not a plugin factory) throws when OpenCode invokes it with
// the PluginInput object, which is what produced the "paths[0] must be of
// type string, got object" load failure. Keep this module's exports as
// plain functions imported by the plugin, never materialized as a plugin
// itself.

import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import path from "node:path"

export const TOOL_NAMES = {
  bash: "Bash",
  edit: "Edit",
  write: "Write",
  patch: "apply_patch",
  task: "Agent",
  webfetch: "WebFetch",
  websearch: "WebSearch",
}

const DISPATCH_TIMEOUT_MS = 3500

export function normalizeToolInput(args = {}) {
  const normalized = { ...args }
  if (typeof args.filePath === "string" && typeof normalized.file_path !== "string") {
    normalized.file_path = args.filePath
  }
  if (typeof args.notebookPath === "string" && typeof normalized.notebook_path !== "string") {
    normalized.notebook_path = args.notebookPath
  }
  if (typeof args.patchText === "string" && typeof normalized.patch !== "string") {
    normalized.patch = args.patchText
  }
  return normalized
}

function dispatcherCommands(root, event) {
  const hooksDir = path.join(root, "harness", "hooks")
  const sh = path.join(hooksDir, "codex-dispatch.sh")
  const ps1 = path.join(hooksDir, "codex-dispatch.ps1")
  const commands = []
  if (existsSync(sh)) {
    commands.push(["bash", [sh, "--runtime", "opencode", "--event", event]])
  }
  if (process.platform === "win32" && existsSync(ps1)) {
    commands.push([
      "powershell.exe",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Runtime", "opencode", "-Event", event],
    ])
  }
  return commands
}

function firstJsonLine(text) {
  for (const line of (text || "").split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed) continue
    try {
      const value = JSON.parse(trimmed)
      if (value && typeof value === "object") return value
    } catch {
      // not JSON; keep scanning
    }
  }
  return null
}

export function dispatch(root, event, payload) {
  const deadline = Date.now() + DISPATCH_TIMEOUT_MS
  const envelope = { hook_event_name: event, cwd: root, ...payload }
  for (const [executable, args] of dispatcherCommands(root, event)) {
    const remaining = deadline - Date.now()
    if (remaining <= 0) break
    const result = spawnSync(executable, args, {
      cwd: root,
      input: JSON.stringify(envelope),
      encoding: "utf8",
      timeout: remaining,
      windowsHide: true,
    })
    if (result.error) continue
    if (result.status !== 0) return null
    return firstJsonLine(result.stdout)
  }
  return null
}

export function contextOf(result) {
  const specific = result && result.hookSpecificOutput
  if (specific && typeof specific.additionalContext === "string") return specific.additionalContext
  if (result && typeof result.systemMessage === "string") return result.systemMessage
  return ""
}

export function isDeny(result) {
  const specific = result && result.hookSpecificOutput
  return Boolean(specific && specific.permissionDecision === "deny")
}
