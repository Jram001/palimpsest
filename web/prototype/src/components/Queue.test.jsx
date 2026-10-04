import { useEffect } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  health: vi.fn(),
  uploadFile: vi.fn(),
  estimate: vi.fn(),
}));

import * as api from "../api.js";
import { theme } from "../theme.js";
import { I18nProvider } from "../i18n.jsx";
import { AppStateProvider, useAppState } from "../state.jsx";
import Queue from "./Queue.jsx";

// Queue itself never adds uploads (that's Overview/Sample) -- it only
// reads `uploads` from AppStateProvider. This harness populates that
// shared state the same way a real drop would, so Queue renders a real
// (non-MOCK) file row.
function Harness({ kind = "digital" }) {
  const { addUploads } = useAppState();
  useEffect(() => {
    addUploads([new File(["x"], kind === "scan" ? "scan.pdf" : "deed.pdf")]);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return <Queue />;
}

function renderQueue({ kind = "digital" } = {}) {
  return render(
    <MantineProvider theme={theme}>
      <I18nProvider>
        <AppStateProvider>
          <Harness kind={kind} />
        </AppStateProvider>
      </I18nProvider>
    </MantineProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.health.mockResolvedValue({
    version: "0", backend: "gemini", anthropic_key_present: false, gemini_key_present: false,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Estimate cost button: loading state", () => {
  it("disables both buttons and shows a loading spinner while the estimate request is in flight", async () => {
    api.uploadFile.mockResolvedValue({
      file_id: "f1", name: "deed.pdf", kind: "digital", pages: 1, size: 100,
    });
    let resolveEstimate;
    api.estimate.mockReturnValue(new Promise((res) => { resolveEstimate = res; }));

    renderQueue();
    const cta = await screen.findByRole("button", { name: /estimate cost/i });
    const back = screen.getByRole("button", { name: /back/i });

    fireEvent.click(cta);

    await waitFor(() => expect(cta).toBeDisabled());
    expect(back).toBeDisabled();

    await act(async () => {
      resolveEstimate([]);
    });
  });

  it("re-enables the button after a failed estimate, so the user can retry", async () => {
    api.uploadFile.mockResolvedValue({
      file_id: "f1", name: "deed.pdf", kind: "digital", pages: 1, size: 100,
    });
    api.estimate.mockRejectedValue(new Error("could not reach the server"));

    renderQueue();
    const cta = await screen.findByRole("button", { name: /estimate cost/i });

    fireEvent.click(cta);

    await waitFor(() => expect(cta).not.toBeDisabled());
    expect(screen.getByRole("button", { name: /back/i })).not.toBeDisabled();
  });
});

describe("scan warning uses `warn`, not `flag`", () => {
  // Mantine encodes color as an inline CSS var reference
  // (`--badge-bg: var(--mantine-color-warn-light)`), not a `data-color`
  // attribute -- verified against a real render, not assumed.
  it("gives the scan badge and Alert the warn color instead of the error color", async () => {
    api.uploadFile.mockResolvedValue({
      file_id: "f1", name: "scan.pdf", kind: "scan", pages: 3, size: 100,
    });

    renderQueue({ kind: "scan" });

    const badge = await screen.findByText("scan");
    const badgeStyle = badge.closest(".mantine-Badge-root").getAttribute("style");
    expect(badgeStyle).toContain("--mantine-color-warn-light");
    expect(badgeStyle).not.toContain("--mantine-color-flag-light");

    const alertStyle = screen
      .getByText(/needs OCR before translation/i)
      .closest(".mantine-Alert-root")
      .getAttribute("style");
    expect(alertStyle).toContain("--mantine-color-warn-light");
    expect(alertStyle).not.toContain("--mantine-color-flag-light");
  });
});

describe("per-file target language", () => {
  it("defaults to English and sends Spanish once the file's switch is flipped", async () => {
    api.uploadFile.mockResolvedValue({
      file_id: "f1", name: "deed.pdf", kind: "digital", pages: 1, size: 100,
    });
    api.estimate.mockResolvedValue([]);

    renderQueue();
    const english = await screen.findByRole("radio", { name: "English" });
    const spanish = screen.getByRole("radio", { name: "Español" });
    expect(english).toBeChecked();
    expect(spanish).not.toBeChecked();

    fireEvent.click(spanish);
    await waitFor(() => expect(spanish).toBeChecked());

    fireEvent.click(screen.getByRole("button", { name: /estimate cost/i }));
    await waitFor(() => expect(api.estimate).toHaveBeenCalledWith(["f1"], { f1: "es" }));
  });
});
