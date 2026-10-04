import { createContext, useCallback, useContext, useEffect, useState } from "react";
import * as api from "./api.js";
import { MOCK } from "./config.js";
import { CACHEABLE_BACKENDS, getCachedKey, HEALTH_KEY, KEY_FIELD } from "./keys.js";

// The six product states, in order, plus "setup" -- a static instructions
// page reachable from Overview's help box and the unreachable-server
// banners, outside the translate flow itself. "compare" is a sub-view of "results"
// (reached via an issue's "View on page ->"), not a state of its own --
// mirrors the pass-2 prototype's compareView overlay.
export const SCREENS = ["overview", "sample", "queue", "estimate", "running", "results", "setup"];

const AppStateContext = createContext(null);

export function AppStateProvider({ children }) {
  const [screen, setScreenRaw] = useState("overview");
  const [compareOpen, setCompareOpen] = useState(false);
  const [comparePage, setComparePage] = useState(1);
  const [runAnimated, setRunAnimated] = useState(false);

  // ---- real-mode state (MOCK=false) ----------------------------------
  // Absent/unused entirely in MOCK mode -- every screen branches on
  // `MOCK` (imported from config.js) before touching any of this, so
  // the mock path never depends on api.js succeeding or even on a
  // server existing at all.
  const [uploads, setUploads] = useState([]); // [{file_id, name, kind, pages, size}, ...]
  const [estimates, setEstimates] = useState([]); // POST /api/estimate response, parallel to uploads
  // file key -> "en" | "es": which language each queued file is translated
  // INTO, chosen per file in the Queue step. Keyed by file_id in real mode
  // and by name in mock mode; a file with no entry is "en" (the original,
  // Spanish -> English behaviour).
  const [targets, setTargets] = useState({});
  const setTarget = useCallback((key, lang) => setTargets((prev) => ({ ...prev, [key]: lang })), []);
  const [jobId, setJobId] = useState(null);
  const [job, setJob] = useState(null); // latest GET /api/jobs/{id} snapshot
  const [apiError, setApiError] = useState(null); // ApiError | null -- drives the "backend unreachable" banner
  const [selectedBackend, setSelectedBackend] = useState(null); // null = server's configured default

  // Lifted out of BackendSelector.jsx/Estimate.jsx (each used to probe
  // /api/health independently) so there's exactly one probe, consumed by
  // both, plus the app-level unreachable banner and the auto-push below.
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);

  // A brand-new visitor who hasn't touched the dropzone yet shouldn't be
  // instantly greeted with "can't reach the server" before they've done
  // anything -- the unreachable banner (App.jsx) only renders once this
  // flips true. App.jsx also fires a one-time hint toast off the same
  // flag, pointing them at setup instead of just leaving them to guess
  // from the banner alone.
  const [dropzoneTouched, setDropzoneTouched] = useState(false);
  const markDropzoneTouched = useCallback(() => setDropzoneTouched(true), []);

  const refreshHealth = useCallback(() => {
    if (MOCK) return Promise.resolve(null);
    setHealthError(null);
    return api
      .health()
      .then((h) => {
        setHealth(h);
        // A key typed into the box while no server was reachable (see
        // keys.js) sits cached in the browser until a server actually
        // answers -- push it the moment one does, so the user never has
        // to retype it just because they saved it before starting
        // `palimpsest serve`. One attempt per backend per successful
        // probe (not a loop): a failed push just waits for the next
        // explicit Recheck rather than retrying itself.
        for (const backend of CACHEABLE_BACKENDS) {
          const cached = getCachedKey(backend);
          if (cached && !h[HEALTH_KEY[backend]]) {
            api
              .setKeys({ [KEY_FIELD[backend]]: cached })
              .then(setHealth)
              .catch(() => {});
          }
        }
        return h;
      })
      .catch((e) => {
        setHealthError(e);
        throw e;
      });
  }, []);

  useEffect(() => {
    refreshHealth().catch(() => {});
  }, [refreshHealth]);

  // Mirrors the static prototype's goto(): switching screens always closes
  // the compare overlay and resets the "running" animation flag unless the
  // caller explicitly asks for the animated golden path (the one real
  // "Translate N documents ->" button). Every other route to "running"
  // (dev switcher, back/forward) shows the static mid-progress snapshot.
  const goto = useCallback((name, opts = {}) => {
    setScreenRaw(name);
    setCompareOpen(false);
    if (name === "running") setRunAnimated(opts.animate === true);
  }, []);

  const openCompare = useCallback((page) => {
    setComparePage(page);
    setCompareOpen(true);
  }, []);
  const closeCompare = useCallback(() => setCompareOpen(false), []);

  const addUploads = useCallback(async (files) => {
    setApiError(null);
    try {
      const added = [];
      for (const file of files) {
        added.push(await api.uploadFile(file));
      }
      setUploads((prev) => [...prev, ...added]);
      return added;
    } catch (e) {
      setApiError(e);
      throw e;
    }
  }, []);

  const removeUpload = useCallback((fileId) => {
    setUploads((prev) => prev.filter((u) => u.file_id !== fileId));
    setEstimates((prev) => prev.filter((e) => e.file_id !== fileId));
    setTargets((prev) => {
      const { [fileId]: _dropped, ...rest } = prev;
      return rest;
    });
  }, []);

  const runEstimate = useCallback(async () => {
    setApiError(null);
    try {
      const result = await api.estimate(uploads.map((u) => u.file_id), targets);
      setEstimates(result);
      return result;
    } catch (e) {
      setApiError(e);
      throw e;
    }
  }, [uploads, targets]);

  const startJob = useCallback(
    async (opts) => {
      setApiError(null);
      try {
        const { job_id } = await api.createJob(uploads.map((u) => u.file_id), {
          backend: selectedBackend,
          targets,
          ...opts,
        });
        setJobId(job_id);
        setJob(null);
        return job_id;
      } catch (e) {
        setApiError(e);
        throw e;
      }
    },
    [uploads, selectedBackend, targets],
  );

  const resetPipeline = useCallback(() => {
    setUploads([]);
    setEstimates([]);
    setTargets({});
    setJobId(null);
    setJob(null);
    setApiError(null);
  }, []);

  const value = {
    screen,
    goto,
    compareOpen,
    comparePage,
    setComparePage,
    openCompare,
    closeCompare,
    runAnimated,
    // real-mode
    uploads,
    addUploads,
    removeUpload,
    estimates,
    targets,
    setTarget,
    runEstimate,
    jobId,
    job,
    setJob,
    startJob,
    selectedBackend,
    setSelectedBackend,
    apiError,
    setApiError,
    resetPipeline,
    health,
    healthError,
    refreshHealth,
    dropzoneTouched,
    markDropzoneTouched,
  };
  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState() {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error("useAppState must be used within AppStateProvider");
  return ctx;
}

// sub below is an i18n key (backend.sub.<id>), resolved with t() in
// BackendSelector.jsx. Real vendor/label data used in BOTH modes -- not a
// mock fixture, just declared here alongside the others.
export const BACKEND_COPY = {
  gemini: { label: "gemini", needsKey: true },
  anthropic: { label: "claude", needsKey: true },
  google: { label: "google machine translation", needsKey: false },
};

// ---------------- mock fixtures ----------------
// Entirely fictional -- the de-identified cast from
// docs/design/protected-entities.md (Grupo Meridian, Banco Litoral, Andres
// Carreno). Never real corpus material -- see tools/scrub_check.py.
//
// MOCK-only, every single one of these -- consumers must gate on `MOCK`
// before touching any fixture below (Rail.jsx's PROTECTED_ENTITIES/
// SUGGESTED_ENTITIES were the one place that didn't, and it leaked fake
// entity names onto the real deployed site with no server reachable --
// worse, a real edit while the fixture was still showing would PUT the
// fictional names into the user's actual entities.toml).

export const QUEUE_FILES = [
  { name: "trust-deed-aurora.pdf", kind: "digital", size: "812 KB", pages: 4 },
  { name: "financial-statement-2026.pdf", kind: "scan", size: "2.1 MB", pages: 12 },
];

export const ESTIMATE = {
  paragraphs: 172,
  uniqueStrings: 154,
  cacheHits: 0,
  tokensIn: "48.3k",
  tokensOut: "48.3k",
  model: "gemini-3.5-flash-lite",
  cost: "~$0.42",
};

// name/detail below are i18n keys (running.phase.<key>.name / .detail),
// resolved with t() at render -- see Running.jsx. detail is null for the
// active phase, which renders a live progress string instead.
export const PHASES = [
  { key: "classify", status: "done" },
  { key: "ocr", status: "done" },
  { key: "extract", status: "done" },
  { key: "translate", status: "active" },
  { key: "render", status: "pending" },
  { key: "save", status: "pending" },
];

// label below is an i18n key (results.stat.<label>), resolved with t().
export const RESULTS_STATS = [
  { n: 154, label: "translated", tone: "ok" },
  { n: 18, label: "skippedProtected", tone: "skip" },
  { n: 3, label: "failed", tone: "fail" },
  { n: 1, label: "refused", tone: "fail" },
  { n: 2, label: "identical", tone: "skip" },
];

// detail below is an i18n key (results.issue.<detail>), resolved with
// t(). text is the Spanish source quotation -- document content, not UI
// copy, so it's never translated.
export const RESULTS_ISSUES = [
  {
    status: "failed",
    text: '"El fideicomitente podra revocar el presente instrumento unicamente..."',
    detail: "failed1",
    page: 2,
  },
  {
    status: "refused",
    text: '"...en caso de fallecimiento del apoderado antes de la firma..."',
    detail: "refused1",
    page: 3,
  },
  {
    status: "failed",
    text: '"RD$48,750,000.00 segun consta en el Anexo B, clausula 4.2..."',
    detail: "failed2",
    page: 1,
  },
  {
    status: "skipped",
    text: '"GRUPO MERIDIAN, S.A.S."',
    detail: "skipped1",
    page: 1,
  },
];

export const FONT_SUBS = [{ from: "Baskerville Old Face", to: "Georgia", count: 3 }];

// title/sub below are i18n keys (results.download.<key>.title / .sub).
export const DOWNLOADS = [
  { icon: "PDF", key: "replica", file: "trust-deed-aurora.en.pdf" },
  { icon: "2x", key: "dual", file: "trust-deed-aurora.dual.pdf" },
  { icon: "{ }", key: "report", file: "trust-deed-aurora.report.json" },
];

export const PROTECTED_ENTITIES = {
  companies: ["Grupo Meridian, S.A.S.", "Banco Litoral, S.A."],
  people: ["Andres Carreno"],
  places: [],
  other: [],
};

export const SUGGESTED_ENTITIES = ["Fideicomiso Aurora Plaza", "Lucia Fernandez Roa"];
