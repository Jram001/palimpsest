import { getApiBase } from "./config.js";
import { getVisitorId } from "./visitor.js";

// Thin fetch wrapper for the palimpsest server (src/palimpsest/server/).
// Every function here mirrors one route in server/routes.py 1:1 -- see
// that file for the shapes returned. Errors always throw an ApiError so
// callers get one catch shape regardless of which call failed.

export class ApiError extends Error {
  constructor(message, status, jobId) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    // Set only for the one route whose `detail` is a dict carrying it
    // (POST /api/jobs' 429 -- see request()) -- undefined everywhere
    // else, so `e.jobId` is a safe truthy check for every other caller.
    this.jobId = jobId;
  }
}

const VISITOR_HEADER = "X-Palimpsest-Visitor";

async function request(path, options = {}) {
  const headers = { ...options.headers, [VISITOR_HEADER]: getVisitorId() };
  let res;
  try {
    res = await fetch(`${getApiBase()}${path}`, { ...options, headers });
  } catch (e) {
    // Network-level failure (server not running, refused connection) --
    // distinct from an HTTP error status, which the caller may want to
    // handle differently (e.g. 404 "not ready yet" vs. "no server at all").
    throw new ApiError(`could not reach the server -- is \`palimpsest serve\` running? (${e.message})`, 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    let jobId;
    try {
      const body = await res.json();
      // Every route's `detail` is a plain string except POST /api/jobs'
      // 429 (server/routes.py::create_job), which sends
      // {message, job_id} so the caller can offer to cancel the job
      // that's blocking it (see Estimate.jsx).
      if (body.detail && typeof body.detail === "object") {
        detail = body.detail.message || detail;
        jobId = body.detail.job_id;
      } else {
        detail = body.detail || detail;
      }
    } catch {
      // response wasn't JSON -- keep statusText
    }
    throw new ApiError(detail, res.status, jobId);
  }
  return res;
}

async function requestJson(path, options) {
  const res = await request(path, options);
  // A 200 with an HTML body happens when there's no /api proxy/route at all
  // (e.g. `npm run dev` without a live palimpsest server behind it) and the
  // request falls through to a dev server's or static host's SPA fallback.
  // request() only checks res.ok, so that case reaches here looking like
  // success -- reject it explicitly instead of letting res.json() throw an
  // opaque parse error that callers can't distinguish from "key missing".
  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new ApiError(
      `unreachable server -- is \`palimpsest serve\` running? (got a non-JSON response from ${path})`,
      0,
    );
  }
  return res.json();
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export function health() {
  return requestJson("/api/health");
}

// keys: {anthropic_api_key?, gemini_api_key?} -- an absent/empty field is
// a no-op server-side, not a clear (server/schemas.py's SetKeysRequest).
// Returns the same shape health() does; never echoes the raw value back.
export function setKeys(keys) {
  return requestJson("/api/keys", {
    method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(keys),
  });
}

export function getEntities() {
  return requestJson("/api/entities");
}

export function putEntities(groups) {
  return requestJson("/api/entities", {
    method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(groups),
  });
}

export async function uploadFile(file, onProgress) {
  const form = new FormData();
  form.append("file", file);
  // Plain fetch has no upload-progress event; onProgress is accepted for
  // API-shape symmetry with a future XHR-based version but is a no-op
  // for now -- callers must not rely on it firing.
  void onProgress;
  return requestJson("/api/uploads", { method: "POST", body: form });
}

// `targets` maps file_id -> "en" | "es", the language each file is
// translated INTO. A file with no entry is translated into English.
export function estimate(fileIds, targets = {}) {
  return requestJson("/api/estimate", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ file_ids: fileIds, targets }),
  });
}

export function createJob(fileIds, { backend, dual = true, targets = {} } = {}) {
  return requestJson("/api/jobs", {
    method: "POST", headers: JSON_HEADERS,
    body: JSON.stringify({ file_ids: fileIds, backend: backend || null, dual, targets }),
  });
}

export function getJob(jobId) {
  return requestJson(`/api/jobs/${jobId}`);
}

// Frees the caller's job-limit slot -- see server/jobs.py::JobRegistry.cancel
// for exactly what this does and doesn't interrupt (a file already
// mid-translation keeps running in the background; its result is just
// discarded).
export function cancelJob(jobId) {
  return requestJson(`/api/jobs/${jobId}/cancel`, { method: "POST" });
}

// SSE progress. Returns an unsubscribe function. `onEvent` receives the
// parsed payload for every "progress" message; `onDone` receives
// {status, error} once for the terminal "job-done" message, after which
// the EventSource is closed automatically -- callers never need to
// close it themselves on the happy path, only via the returned
// unsubscribe if they navigate away early.
export function watchJob(jobId, { onEvent, onDone, onError } = {}) {
  // EventSource (unlike fetch) can't set custom headers, so the visitor id
  // travels as a query param here instead -- the server's _visitor_id()
  // helper checks both places for exactly this reason.
  const q = `?visitor=${encodeURIComponent(getVisitorId())}`;
  const source = new EventSource(`${getApiBase()}/api/jobs/${jobId}/events${q}`);
  source.onmessage = (msg) => {
    let payload;
    try {
      payload = JSON.parse(msg.data);
    } catch {
      return;
    }
    if (payload.type === "job-done") {
      onDone?.(payload);
      source.close();
    } else {
      onEvent?.(payload);
    }
  };
  source.onerror = (e) => {
    onError?.(e);
  };
  return () => source.close();
}

// downloadUrl/pageUrl feed an <a href>/<img src> directly rather than
// fetch(), so (like watchJob's EventSource) they can't attach the visitor
// header -- the visitor id rides along as a query param instead.
export function downloadUrl(jobId, artifact, fileId) {
  const params = new URLSearchParams({ visitor: getVisitorId() });
  if (fileId) params.set("file", fileId);
  return `${getApiBase()}/api/jobs/${jobId}/download/${artifact}?${params}`;
}

export function pageUrl(jobId, pageNo, { side = "output", fileId, dpi, v } = {}) {
  const params = new URLSearchParams({ side, visitor: getVisitorId() });
  if (fileId) params.set("file", fileId);
  if (dpi) params.set("dpi", String(dpi));
  // Cache-buster: the browser has no way to know a reflowed page's PNG
  // changed underneath the same URL, since the server route ignores
  // unknown params -- bump `v` (e.g. a save counter) after a successful
  // PATCH /layout so the <img> actually re-fetches.
  if (v !== undefined) params.set("v", String(v));
  return `${getApiBase()}/api/jobs/${jobId}/pages/${pageNo}.png?${params}`;
}

export function getLayout(jobId, { fileId, page = 0 } = {}) {
  const params = new URLSearchParams({ page: String(page) });
  if (fileId) params.set("file", fileId);
  return requestJson(`/api/jobs/${jobId}/layout?${params}`);
}

export function patchLayout(jobId, body, { fileId } = {}) {
  const q = fileId ? `?file=${encodeURIComponent(fileId)}` : "";
  return requestJson(`/api/jobs/${jobId}/layout${q}`, {
    method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body),
  });
}
