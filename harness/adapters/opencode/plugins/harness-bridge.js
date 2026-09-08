// OpenCode plugin bridge for the shared hook dispatcher.
//
// tool.execute.before   -> PreToolUse through harness/hooks/codex-dispatch
// experimental.chat.system.transform -> SessionStart identity context (once per process)
//
// The bridge spawns the dispatcher, reads one JSON line from its stdout, and
// throws when the JSON carries permissionDecision == "deny". Any malfunction
// (dispatcher missing, shell missing, non-zero exit, unparseable output) fails
// open: the tool call proceeds and the contract text governs. The decision
// lives in the JSON, never in the exit code.
//
// OpenCode calls every export of this file as a plugin factory with the
// PluginInput object, so this file exports only the plugin itself; the
// dispatch, normalize, and context helpers live in the sibling lib module
// (harness-bridge-internal.js), in a directory that is not linked into
// .opencode/plugins/.

import { TOOL_NAMES, dispatch, normalizeToolInput, contextOf, isDeny } from "../lib/harness-bridge-internal.js"

export const HarnessBridge = async ({ directory, worktree }) => {
  const root = worktree || directory
  let identityContext
  return {
    "tool.execute.before": async (input, output) => {
      const tool = TOOL_NAMES[input.tool] || input.tool
      const result = dispatch(root, "PreToolUse", {
        tool_name: tool,
        tool_input: normalizeToolInput(output.args || {}),
        session_id: input.sessionID || "",
      })
      if (isDeny(result)) {
        const reason = result.hookSpecificOutput.permissionDecisionReason || contextOf(result)
        throw new Error(reason || "Denied by the harness PreToolUse hook")
      }
    },
    "experimental.chat.system.transform": async (_input, output) => {
      if (identityContext === undefined) {
        const result = dispatch(root, "SessionStart", { source: "startup" })
        identityContext = contextOf(result)
      }
      if (identityContext) output.system.push(identityContext)
    },
  }
}
