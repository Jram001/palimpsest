import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, cancelJob, downloadUrl, estimate, getEntities, getLayout, pageUrl } from "./api.js";

function mockFetchOnce(response) {
  global.fetch = vi.fn().mockResolvedValue(response);
}

function jsonResponse(body, { ok = true, status = 200, statusText = "OK" } = {}) {
  return {
    ok, status, statusText,
    headers: { get: () => "application/json" },
    json: async () => body,
  };
}

function htmlResponse(html = "<!doctype html><html></html>") {
  return {
    ok: true, status: 200, statusText: "OK",
    headers: { get: () => "text/html" },
    json: async () => {
      throw new SyntaxError("Unexpected token '<'");
    },
    text: async () => html,
  };
}

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("network-level failure", () => {
  it("wraps a rejected fetch in an ApiError with status 0", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(getEntities()).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
    });
  });

  it("mentions `palimpsest serve` in a network-failure message -- the one thing a user actually needs to do", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(getEntities()).rejects.toThrow(/palimpsest serve/);
  });
});

describe("HTTP-level failure", () => {
  it("surfaces the server's `detail` field as the ApiError message", async () => {
    mockFetchOnce(
      jsonResponse({ detail: "unknown file_id 'nope'" }, { ok: false, status: 404, statusText: "Not Found" }),
    );
    await expect(getEntities()).rejects.toThrow("unknown file_id 'nope'");
  });

  it("falls back to statusText when the error body isn't JSON", async () => {
    mockFetchOnce({
      ok: false, status: 500, statusText: "Internal Server Error",
      json: async () => {
        throw new SyntaxError("Unexpected token");
      },
    });
    await expect(getEntities()).rejects.toThrow("Internal Server Error");
  });

  it("is an instance of ApiError, not a bare Error", async () => {
    mockFetchOnce(jsonResponse({ detail: "boom" }, { ok: false, status: 400 }));
    try {
      await getEntities();
      throw new Error("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.status).toBe(400);
    }
  });

  it("unpacks a dict-shaped `detail` ({message, job_id}) -- POST /api/jobs' 429", async () => {
    mockFetchOnce(
      jsonResponse(
        { detail: { message: "you already have 1 job(s) in progress -- wait for one to finish", job_id: "job-123" } },
        { ok: false, status: 429, statusText: "Too Many Requests" },
      ),
    );
    try {
      await getEntities();
      throw new Error("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.status).toBe(429);
      expect(e.message).toBe("you already have 1 job(s) in progress -- wait for one to finish");
      expect(e.jobId).toBe("job-123");
    }
  });

  it("leaves `jobId` undefined for every ordinary string-`detail` error", async () => {
    mockFetchOnce(jsonResponse({ detail: "unknown job 'nope'" }, { ok: false, status: 404 }));
    try {
      await getEntities();
      throw new Error("should have thrown");
    } catch (e) {
      expect(e.jobId).toBeUndefined();
    }
  });
});

describe("non-JSON 200 response (no /api proxy behind the dev server)", () => {
  it("rejects with an ApiError instead of an opaque JSON parse error", async () => {
    mockFetchOnce(htmlResponse());
    await expect(getEntities()).rejects.toMatchObject({ name: "ApiError", status: 0 });
  });

  it("names the real problem so it isn't confused with a missing API key", async () => {
    mockFetchOnce(htmlResponse());
    await expect(getEntities()).rejects.toThrow(/palimpsest serve/);
  });
});

describe("success path", () => {
  it("returns the parsed JSON body", async () => {
    mockFetchOnce(jsonResponse({ companies: ["Acme"], people: [], places: [], other: [] }));
    const result = await getEntities();
    expect(result.companies).toEqual(["Acme"]);
  });

  it("POSTs file_ids as JSON for estimate()", async () => {
    mockFetchOnce(jsonResponse([]));
    await estimate(["a", "b"]);
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toContain("/api/estimate");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ file_ids: ["a", "b"], targets: {} });
  });

  it("estimate() sends each file's target language", async () => {
    mockFetchOnce(jsonResponse([]));
    await estimate(["a", "b"], { b: "es" });
    const [, options] = global.fetch.mock.calls[0];
    expect(JSON.parse(options.body)).toEqual({ file_ids: ["a", "b"], targets: { b: "es" } });
  });

  it("cancelJob POSTs to /api/jobs/{id}/cancel with no body", async () => {
    mockFetchOnce(jsonResponse({ id: "job1", status: "cancelled" }));
    await cancelJob("job1");
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toContain("/api/jobs/job1/cancel");
    expect(options.method).toBe("POST");
  });
});

describe("URL builders (no network)", () => {
  it("downloadUrl always carries the visitor id, and the file param only when given", () => {
    expect(downloadUrl("job1", "replica")).toMatch(/^\/api\/jobs\/job1\/download\/replica\?visitor=/);
    expect(downloadUrl("job1", "replica")).not.toContain("file=");
    expect(downloadUrl("job1", "replica", "file1")).toContain("file=file1");
  });

  it("pageUrl defaults side to output and encodes params", () => {
    const url = pageUrl("job1", 2, { fileId: "f 1" });
    expect(url).toContain("/api/jobs/job1/pages/2.png?");
    expect(url).toContain("side=output");
    expect(url).toContain("file=f+1");
    expect(url).toContain("visitor=");
  });

  it("getLayout issues a plain GET (no method/body) with page/file query params", async () => {
    mockFetchOnce(jsonResponse({ schema: 1, pages: [] }));
    await getLayout("job1", { fileId: "f1", page: 3 });
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toContain("/api/jobs/job1/layout?");
    expect(url).toContain("page=3");
    expect(url).toContain("file=f1");
    // request()'s default -- no method/body means GET, but the visitor
    // header is always attached.
    expect(options.method).toBeUndefined();
    expect(options.body).toBeUndefined();
    expect(options.headers["X-Palimpsest-Visitor"]).toBeTruthy();
  });
});

describe("visitor id header", () => {
  it("is attached on every request and stable across calls", async () => {
    mockFetchOnce(jsonResponse({ companies: [], people: [], places: [], other: [] }));
    await getEntities();
    const first = global.fetch.mock.calls[0][1].headers["X-Palimpsest-Visitor"];
    expect(first).toBeTruthy();

    mockFetchOnce(jsonResponse({ companies: [], people: [], places: [], other: [] }));
    await getEntities();
    const second = global.fetch.mock.calls[0][1].headers["X-Palimpsest-Visitor"];
    expect(second).toBe(first);
  });
});
