/**
 * Smoke test for the pi-toolcall-integrity extension.
 *
 * Run: node test/smoke.mjs   (Node >= 22.18, or `node --experimental-strip-types`)
 *
 * Exercises the real extension source (../pi-toolcall-integrity.ts) with a stub
 * `pi` object and synthetic events. Covers both hooks:
 *   ① message_end  — drops empty-arg toolCall blocks from errored/aborted
 *                    assistant turns before session persistence.
 *   ② tool_call    — blocks empty-arg calls on successful turns with a
 *                    readable "re-issue" reason instead of a cryptic
 *                    schema-validation error.
 */

const m = await import(new URL("../pi-toolcall-integrity.ts", import.meta.url).href);
const factory = m.default?.default ?? m.default;
if (typeof factory !== "function") throw new Error("extension has no factory export");

const handlers = {};
factory({ on: (event, handler) => (handlers[event] = handler) });
const registered = Object.keys(handlers).sort();
if (JSON.stringify(registered) !== JSON.stringify(["message_end", "tool_call"])) {
	throw new Error(`unexpected handlers: ${registered.join(", ")}`);
}

let pass = 0;
let fail = 0;
function check(name, cond) {
	console.log(`${cond ? "PASS" : "FAIL"}  ${name}`);
	cond ? pass++ : fail++;
}

const assistant = (stopReason, content) => ({
	role: "assistant",
	api: "openai-completions",
	provider: "x",
	model: "y",
	content,
	stopReason,
	timestamp: 0,
	usage: {},
});
const emptyWrite = { type: "toolCall", id: "call_1", name: "write", arguments: {} };
const fullWrite = { type: "toolCall", id: "call_2", name: "write", arguments: { path: "a.md", content: "x" } };

// --- ① message_end ---------------------------------------------------------
let r = handlers.message_end({ message: assistant("error", [emptyWrite, fullWrite, { type: "text", text: "hi" }]) });
check("① error turn: empty toolCall dropped, real one + text kept",
	r?.message?.content?.length === 2 && r.message.content[0].id === "call_2");
check("① error turn: replacement preserves role/stopReason",
	r?.message?.role === "assistant" && r.message.stopReason === "error");

r = handlers.message_end({ message: assistant("aborted", [emptyWrite]) });
check("① aborted turn: content emptied", r?.message?.content?.length === 0);

r = handlers.message_end({ message: assistant("toolUse", [emptyWrite]) });
check("① toolUse turn: NOT cleaned (② owns that path)", r === undefined);

r = handlers.message_end({ message: assistant("error", [{ type: "text", text: "oops" }]) });
check("① error turn without toolCalls: untouched", r === undefined);

r = handlers.message_end({ message: { role: "user", content: [], timestamp: 0 } });
check("① user message: untouched", r === undefined);

// --- ② tool_call ------------------------------------------------------------
r = handlers.tool_call({ toolName: "write", input: {}, toolCallId: "c1" });
check("② write {}: blocked with re-issue hint", r?.block === true && /re-issue/i.test(r?.reason ?? ""));
check("② write {}: does not terminate the batch", r?.terminate !== true);

r = handlers.tool_call({ toolName: "bash", input: { command: "   " }, toolCallId: "c2" });
check("② bash blank command: blocked", r?.block === true);

r = handlers.tool_call({ toolName: "bash", input: { command: "ls" }, toolCallId: "c3" });
check("② bash with command: passes", r === undefined);

r = handlers.tool_call({ toolName: "ls", input: {}, toolCallId: "c4" });
check("② ls {}: passes (zero-arg call is valid)", r === undefined);

r = handlers.tool_call({ toolName: "edit", input: { path: "x" }, toolCallId: "c5" });
check("② edit partial-but-nonempty args: passes to schema validation", r === undefined);

r = handlers.tool_call({ toolName: "mcp__dodo__do_thing", input: {}, toolCallId: "c6" });
check("② custom/MCP tool {}: not blocked (schema unknown)", r === undefined);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
