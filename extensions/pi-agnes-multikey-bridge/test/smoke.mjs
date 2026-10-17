/**
 * Smoke test for the pi-agnes-multikey-bridge extension.
 *
 * Run: node test/smoke.mjs   (Node >= 22.18, or `node --experimental-strip-types`)
 *
 * Exercises the real extension source (../pi-agnes-multikey-bridge.ts) with a
 * stub `pi` object, a fake global fetch, and a fixture multikey.json (via the
 * PI_AGNES_BRIDGE_MULTIKEY_CONFIG seam). Covers both bridge mechanisms:
 *   ① tool_execution_start — round-robins AGNES_API_KEY across pool keys
 *   ② fetch interception    — 401/403/429 on pool-host media endpoints
 *                             retries with the next pool key
 */
import { fileURLToPath } from "node:url";

const K = ["sk-test-key-1", "sk-test-key-2", "sk-test-key-3", "sk-test-key-4"];

// Point the bridge at the fixture BEFORE the module loads.
process.env.PI_AGNES_BRIDGE_MULTIKEY_CONFIG = fileURLToPath(
	new URL("./fixtures/multikey.json", import.meta.url),
);
delete process.env.AGNES_API_KEY;
delete process.env.AGNES_CN_API_KEY;

// Fake "real" fetch: K0 rate-limits media submits; everything else is healthy.
const calls = [];
const fakeReal = async (url, init) => {
	const u = String(url);
	const rawHeaders = (init && init.headers) || {};
	const readHeader = (n) =>
		rawHeaders instanceof Headers ? (rawHeaders.get(n) || "") : rawHeaders[n] || "";
	const key = readHeader("Authorization").replace(/^Bearer /, "");
	const method = (init && init.method) || "GET";
	calls.push({ method, url: u, key });
	const base = "https://apihub.agnes-ai.com";
	if (u.startsWith(`${base}/v1/images/generations`)) {
		if (process.env.FORCE_400) return new Response("{}", { status: 400 });
		if (key === K[0]) return new Response(JSON.stringify({ error: { message: "rate limited" } }), { status: 429 });
		if (key === "sk-not-in-pool") return new Response(JSON.stringify({ error: { message: "invalid key" } }), { status: 401 });
		return new Response(JSON.stringify({ data: [{ b64_json: "AAAA", mime_type: "image/png" }] }), { status: 200 });
	}
	if (u.startsWith(`${base}/v1/videos`)) {
		if (key === K[0]) return new Response(JSON.stringify({ error: { message: "rate limited" } }), { status: 429 });
		return new Response(JSON.stringify({ video_id: "v-1", status: "processing" }), { status: 200 });
	}
	if (u.startsWith(`${base}/agnesapi?`)) {
		if (key === K[0]) return new Response(JSON.stringify({ error: { message: "rate limited" } }), { status: 429 });
		return new Response(JSON.stringify({ status: "completed", url: "https://fake.local/v.mp4" }), { status: 200 });
	}
	if (u === "https://fake.local/v.mp4") return new Response("FAKE-MP4", { status: 200 });
	if (u.startsWith("https://api.groq.com/")) return new Response("{}", { status: 429 });
	throw new Error(`unexpected fetch: ${u}`);
};
globalThis.fetch = fakeReal;

const m = await import(new URL("../pi-agnes-multikey-bridge.ts", import.meta.url).href);
const factory = m.default?.default ?? m.default;
if (typeof factory !== "function") throw new Error("extension has no factory export");

const handlers = [];
factory({
	registerTool() {},
	registerProvider() {},
	registerCommand() {},
	on(event, handler) {
		if (event === "tool_execution_start") handlers.push(handler);
	},
});
if (handlers.length !== 1) throw new Error(`expected 1 tool_execution_start handler, got ${handlers.length}`);
if (!globalThis.fetch.__agnesMultikeyBridge) throw new Error("fetch interception was not installed");

let pass = 0;
let fail = 0;
function check(name, cond, extra) {
	console.log(`${cond ? "PASS" : "FAIL"}  ${name}${extra && !cond ? ` — ${extra}` : ""}`);
	cond ? pass++ : fail++;
}
const fire = (toolName, args = {}) =>
	Promise.all(handlers.map((h) => h({ type: "tool_execution_start", toolCallId: "x", toolName, args })));
const imgKeys = () => calls.filter((c) => c.url.includes("/images/generations")).map((c) => c.key);
const short = (k) => (K.includes(k) ? `K${K.indexOf(k) + 1}` : k || "none");

// --- ① tool_execution_start round-robin ---------------------------------
await fire("agnes_image");
check("① first call writes env K1", process.env.AGNES_API_KEY === K[0], short(process.env.AGNES_API_KEY));
await fire("agnes_image");
check("① second call advances to K2", process.env.AGNES_API_KEY === K[1], short(process.env.AGNES_API_KEY));
await fire("agnes_video", { endpoint: "agnes-cn" });
check("① cn endpoint writes AGNES_CN_API_KEY, intl env untouched",
	process.env.AGNES_CN_API_KEY === "sk-cn-key-1" && process.env.AGNES_API_KEY === K[1]);
await fire("bash", { command: "ls" });
check("① non-media tools ignored", process.env.AGNES_CN_API_KEY === "sk-cn-key-1");
delete process.env.AGNES_CN_API_KEY;

// --- ② fetch interception -------------------------------------------------
calls.length = 0;
let res = await globalThis.fetch("https://apihub.agnes-ai.com/v1/images/generations", {
	method: "POST",
	headers: { Authorization: `Bearer ${K[0]}`, "Content-Type": "application/json" },
	body: "{}",
});
check("② 429 on K1 rotates to K2 -> 200", res.status === 200, `HTTP ${res.status}`);
check("② original key first, exactly one retry", JSON.stringify(imgKeys()) === JSON.stringify([K[0], K[1]]), imgKeys().map(short).join(","));
await res.arrayBuffer();

process.env.FORCE_400 = "1";
calls.length = 0;
res = await globalThis.fetch("https://apihub.agnes-ai.com/v1/images/generations", {
	method: "POST",
	headers: { Authorization: `Bearer ${K[1]}`, "Content-Type": "application/json" },
	body: "{}",
});
check("② 400 is not retried (single attempt)", res.status === 400 && calls.length === 1, `HTTP ${res.status} attempts=${calls.length}`);
await res.arrayBuffer();
delete process.env.FORCE_400;

calls.length = 0;
res = await globalThis.fetch("https://api.groq.com/v1/images/whatever", {
	method: "POST",
	headers: { Authorization: `Bearer ${K[0]}`, "Content-Type": "application/json" },
	body: "{}",
});
check("② out-of-scope host passes through untouched", res.status === 429 && calls.length === 1, `attempts=${calls.length}`);
await res.arrayBuffer();

calls.length = 0;
res = await globalThis.fetch("https://apihub.agnes-ai.com/agnesapi?video_id=v-1", {
	headers: { Authorization: `Bearer ${K[0]}` },
});
check("② video status poll rotates K1 -> K2", res.status === 200, `HTTP ${res.status}`);
await res.arrayBuffer();

calls.length = 0;
res = await globalThis.fetch("https://apihub.agnes-ai.com/v1/images/generations", {
	method: "POST",
	headers: { Authorization: `Bearer sk-not-in-pool`, "Content-Type": "application/json" },
	body: "{}",
});
check("② key not in pool: original attempt kept, then pool rotation",
	res.status === 200 && calls.length === 3, `attempts=${calls.length} keys=${calls.map((c) => short(c.key)).join(",")}`);
await res.arrayBuffer();

// --- env lock: a startup env var is never clobbered ----------------------
process.env.AGNES_API_KEY = "sk-pinned";
const m2 = await import(new URL("../pi-agnes-multikey-bridge.ts", import.meta.url).href + "?locked");
const factory2 = m2.default?.default ?? m2.default;
const handlers2 = [];
factory2({ registerTool() {}, registerProvider() {}, registerCommand() {}, on(event, h) { if (event === "tool_execution_start") handlers2.push(h); } });
for (const h of handlers2) {
	await h({ type: "tool_execution_start", toolCallId: "x", toolName: "agnes_image", args: {} });
}
check("env var set at startup is preserved (no clobber)", process.env.AGNES_API_KEY === "sk-pinned");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
