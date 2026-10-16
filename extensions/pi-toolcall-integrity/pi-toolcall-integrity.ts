/**
 * pi-toolcall-integrity.ts
 *
 * Mitigates the symptom of a provider stream that dies mid tool-call
 * (pi-ai keeps the in-flight toolCall block with empty arguments when the
 * stream ends without finish_reason; upstream issue:
 * https://github.com/earendil-works/pi/issues/10435).
 *
 * Two hooks, two symptoms:
 *
 * 1. message_end cleanup — when an assistant turn ends with stopReason
 *    "error" or "aborted", its tool-call blocks were never executed and
 *    have no tool results. Tool calls whose arguments are an empty object
 *    are truncated debris; drop them from the persisted message so the
 *    session log no longer records fake empty-argument calls. Text and
 *    thinking blocks are kept as context.
 *
 * 2. tool_call guard — on a SUCCESSFUL turn, an empty-argument call that
 *    slipped through (provider sent finish_reason but args never completed)
 *    would hit TypeBox schema validation and produce a cryptic
 *    "Validation failed for tool ..." error. Block it instead with a
 *    clear "re-issue with complete arguments" message so the model
 *    self-corrects.
 *
 * Known limitation (same as any log-level mitigation): a truncated stream
 * whose partial JSON was auto-completed into a NON-EMPTY object cannot be
 * distinguished from a real call at this layer; only the empty-arguments
 * signature is caught. The durable fix lives in pi-ai itself (argsComplete
 * tracking).
 *
 * Uninstall: delete this file (and its .js, if any) from the extensions
 * directory and reload pi.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** Built-in tools that must never be called with zero arguments.
 *  `ls` is deliberately NOT in this list: `ls` with no args is valid. */
const REQUIRED_ARGS_TOOLS = new Set([
	"bash",
	"powershell",
	"read",
	"edit",
	"write",
	"grep",
	"find",
]);

function isEmptyArgs(input: unknown): boolean {
	if (input == null) return true;
	if (typeof input !== "object" || Array.isArray(input)) return false;
	const obj = input as Record<string, unknown>;
	const keys = Object.keys(obj);
	if (keys.length === 0) return true;
	// bash/powershell with an empty-string command are equally bogus.
	if ((obj.command ?? undefined) !== undefined && typeof obj.command === "string" && obj.command.trim() === "") {
		return keys.length === 1;
	}
	return false;
}

export default function (pi: ExtensionAPI) {
	// ① Drop truncated empty-argument tool calls from errored/aborted
	// assistant turns before they are persisted into the session log.
	pi.on("message_end", (event) => {
		const msg = event.message;
		if (msg.role !== "assistant") return undefined;
		if (msg.stopReason !== "error" && msg.stopReason !== "aborted") return undefined;
		const content = msg.content;
		const filtered = content.filter((block) => !(block.type === "toolCall" && isEmptyArgs(block.arguments)));
		if (filtered.length === content.length) return undefined;
		return { message: { ...msg, content: filtered } };
	});

	// ② Fail fast with a readable message when an empty-argument call
	// survives to execution on a successful turn, instead of the cryptic
	// "Validation failed for tool ..." from schema validation.
	pi.on("tool_call", (event) => {
		if (!REQUIRED_ARGS_TOOLS.has(event.toolName)) return undefined;
		if (!isEmptyArgs(event.input)) return undefined;
		return {
			block: true,
			reason: `Tool call "${event.toolName}" arrived with empty arguments — this usually means the provider stream was cut off mid call and the call was never complete. It was NOT executed. Re-issue the tool call with complete arguments.`,
		};
	});
}
