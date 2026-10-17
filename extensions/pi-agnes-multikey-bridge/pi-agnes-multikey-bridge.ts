/**
 * pi-agnes-multikey-bridge
 *
 * Bridges pi-agnes-tools' `agnes_image` / `agnes_video` tools onto a
 * pi-multikey key pool WITHOUT modifying pi-agnes-tools or any settings.
 *
 * Requires (both pre-installed as pi packages on this machine):
 *   - pi-agnes-tools   (provides the agnes_image / agnes_video tools)
 *   - pi-multikey      (owns ~/.pi/agent/multikey.json pools)
 *
 * Two mechanisms, both inside this one extension:
 *
 * 1) tool_execution_start hook — before each agnes_image/agnes_video call,
 *    set AGNES_API_KEY / AGNES_CN_API_KEY to the next multikey pool key
 *    (round-robin). pi-agnes-tools' key resolution consults the env var
 *    FIRST, so every generation call — concurrent calls included — cycles
 *    over the whole pool instead of a single /login-stored key. The env
 *    var is only written if it was NOT set at process start (an explicit
 *    env var always wins; deterministic single-key behavior is preserved).
 *
 * 2) global fetch interception — media-generation requests to a pool host
 *    (POST /v1/images/*, POST /v1/videos, GET /agnesapi status) that fail
 *    with 401/403/429 are transparently retried with the next pool key.
 *    The original request is always sent first, unchanged; retries go to
 *    the underlying fetch, never back through the wrapper (no recursion).
 *    Out-of-scope URLs (chat pipelines, other hosts) pass through.
 *
 * pi-agnes-tools stays fully enabled (its tools, providers, skill and the
 * before_provider_request sanitizer keep running); this extension registers
 * no tools, so there is no name conflict.
 *
 * Testing seam: PI_AGNES_BRIDGE_MULTIKEY_CONFIG points the pool lookup at
 * an alternate multikey.json (used by test/smoke.mjs; unset = the real
 * ~/.pi/agent/multikey.json).
 * Debug seam: PI_AGNES_BRIDGE_DEBUG logs key swaps/rotations to stderr.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

// ── Pool key loading ───────────────────────────────────────────────────

function multikeyConfigPath() {
  return process.env.PI_AGNES_BRIDGE_MULTIKEY_CONFIG || join(homedir(), ".pi", "agent", "multikey.json");
}

function loadPoolKeysForBaseUrl(baseUrl) {
  try {
    const raw = JSON.parse(readFileSync(multikeyConfigPath(), "utf8"));
    const host = new URL(baseUrl).host;
    const keys = [];
    for (const pool of (raw && raw.pools) || []) {
      if (!pool || typeof pool.baseUrl !== "string" || pool.baseUrl.indexOf(host) === -1) continue;
      for (const k of pool.keys || []) {
        if (k && typeof k.key === "string" && k.key.trim() !== "" && k.enabled !== false) {
          keys.push(k.key.trim());
        }
      }
    }
    return keys;
  } catch {
    return [];
  }
}

const AGNES_ENDPOINTS = {
  agnes: { baseUrl: "https://apihub.agnes-ai.com/v1", apiKeyEnv: "AGNES_API_KEY" },
  "agnes-cn": { baseUrl: "https://api.agnes-ai.cn/v1", apiKeyEnv: "AGNES_CN_API_KEY" },
};

const MEDIA_TOOL_NAMES = new Set(["agnes_image", "agnes_video"]);

function debugLog(msg) {
  if (process.env.PI_AGNES_BRIDGE_DEBUG) {
    try {
      console.error("[pi-agnes-multikey-bridge] " + msg);
    } catch {
      // best-effort
    }
  }
}

/** Env vars that existed at process start are never clobbered. */
const envLocked = {
  AGNES_API_KEY: Boolean(process.env.AGNES_API_KEY),
  AGNES_CN_API_KEY: Boolean(process.env.AGNES_CN_API_KEY),
};

const cursors = { agnes: 0, "agnes-cn": 0 };

const POOL_HOSTS = new Set(["apihub.agnes-ai.com", "api.agnes-ai.cn"]);

function nextPoolKey(endpoint) {
  const keys = loadPoolKeysForBaseUrl(AGNES_ENDPOINTS[endpoint].baseUrl);
  if (keys.length === 0) return undefined;
  const start = cursors[endpoint] % keys.length;
  cursors[endpoint] = (cursors[endpoint] + 1) % keys.length;
  return keys[start];
}

// ── Mechanism 1: round-robin via env (upstream reads env first) ────────

function onToolExecutionStart(event) {
  if (!MEDIA_TOOL_NAMES.has(event.toolName)) return;
  const endpoint = (event.args && (event.args.endpoint === "agnes-cn" ? "agnes-cn" : "agnes")) || "agnes";
  const env = AGNES_ENDPOINTS[endpoint].apiKeyEnv;
  if (envLocked[env]) return; // explicit env var owns the channel
  const key = nextPoolKey(endpoint);
  if (key) {
    process.env[env] = key;
    debugLog(`${event.toolName}: ${env} set to pool key ${key.slice(0, 8)}...`);
  }
}

// ── Mechanism 2: 401/403/429 rotation on media endpoints ──────────────

function installFetchInterception() {
  if (globalThis.fetch.__agnesMultikeyBridge) return; // already wrapped
  const realFetch = globalThis.fetch;
  const wrapped = async (input, init) => {
    let parsedUrl = null;
    try {
      parsedUrl = new URL(String(input && input.url ? input.url : input));
    } catch {
      return realFetch(input, init);
    }
    const host = parsedUrl.host;
    const path = parsedUrl.pathname;
    const inScope =
      POOL_HOSTS.has(host) &&
      (path.startsWith("/v1/images/") || path.startsWith("/v1/videos") || path.startsWith("/agnesapi"));
    if (!inScope || !(init && init.headers)) return realFetch(input, init);
    const auth = String(init.headers.Authorization || "");
    if (!auth.startsWith("Bearer ")) return realFetch(input, init);
    const currentKey = auth.slice(7);
    const keys = loadPoolKeysForBaseUrl("https://" + host + "/v1");
    if (keys.length < 2) return realFetch(input, init);

    // Attempt 0: send the original request as-is with the key upstream chose
    // (mechanism 1 already round-robins that key across calls).
    let response = await realFetch(input, init);
    if (response.status !== 401 && response.status !== 403 && response.status !== 429) {
      return response;
    }
    let lastResponse = response;
    // Drain the failed body so it does not leak into the next use.
    try {
      await lastResponse.clone().arrayBuffer();
    } catch {
      // ignore drain failures
    }

    // Rotatable: retry with the OTHER pool keys, in round-robin order after
    // the current key. Retries go to realFetch, never back through the
    // wrapper, so this cannot recurse.
    const startIdx = keys.indexOf(currentKey);
    const rotation =
      startIdx === -1 ? keys : keys.slice(startIdx + 1).concat(keys.slice(0, startIdx + 1));
    for (const key of rotation) {
      if (key === currentKey) break; // already tried the original key
      const headers = new Headers(init.headers);
      headers.set("Authorization", "Bearer " + key);
      response = await realFetch(input, { ...init, headers });
      if (response.status !== 401 && response.status !== 403 && response.status !== 429) {
        debugLog(`${path}: rotated to pool key ${key.slice(0, 8)}... -> HTTP ${response.status}`);
        return response;
      }
      lastResponse = response;
      try {
        await lastResponse.clone().arrayBuffer();
      } catch {
        // ignore drain failures
      }
    }
    return lastResponse;
  };
  wrapped.__agnesMultikeyBridge = true;
  wrapped.__realFetch = realFetch;
  globalThis.fetch = wrapped;
  return wrapped;
}

// ── Extension entry ────────────────────────────────────────────────────

export default function (pi) {
  pi.on("tool_execution_start", onToolExecutionStart);
  installFetchInterception();
}
