import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api.js", () => ({
  health: vi.fn(),
  setKeys: vi.fn(),
  getEntities: vi.fn(),
  putEntities: vi.fn(),
}));

import * as api from "./api.js";
import { theme } from "./theme.js";
import { I18nProvider } from "./i18n.jsx";
import App from "./App.jsx";
import { serveCommand } from "./serveCommand.js";

beforeEach(() => {
  vi.clearAllMocks();
  api.getEntities.mockResolvedValue({ companies: [], people: [], places: [], other: [] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("serveCommand()", () => {
  afterEach(() => {
    localStorage.clear();
  });

  it("omits --allow-origin when the API base is same-origin (relative)", () => {
    // config.js's getApiBase() returns "" for same-origin builds --
    // exercised here via the real module (no mock), same-origin means
    // no VITE_STANDALONE/localStorage override is in play, which is the
    // default in this test environment.
    expect(serveCommand()).toBe("palimpsest serve");
  });

  it("names this page's exact origin when the API base is genuinely cross-origin", () => {
    // config.js's setApiBase() persists to the same "pp-api-base"
    // localStorage key getApiBase() reads -- this is exactly the
    // standalone/GitHub Pages scenario (config.js's VITE_STANDALONE).
    localStorage.setItem("pp-api-base", "http://127.0.0.1:8765");
    expect(serveCommand()).toBe(`palimpsest serve --allow-origin ${window.location.origin}`);
  });
});

describe("global unreachable banner", () => {
  function renderApp() {
    return render(
      <MantineProvider theme={theme}>
        <I18nProvider>
          <Notifications />
          <App />
        </I18nProvider>
      </MantineProvider>,
    );
  }

  it("does not appear on load, before any dropzone interaction, even when the health probe fails", async () => {
    // A brand-new visitor who hasn't touched the dropzone yet shouldn't
    // be instantly greeted with a warning before they've done anything.
    api.health.mockRejectedValue(new Error("could not reach the server"));
    renderApp();

    await waitFor(() => expect(api.health).toHaveBeenCalled());
    expect(screen.queryByText("Couldn't reach the server")).not.toBeInTheDocument();
  });

  it("appears, alongside a one-time setup-hint toast, once the user touches the dropzone", async () => {
    api.health.mockRejectedValue(new Error("could not reach the server"));
    renderApp();

    await waitFor(() => expect(api.health).toHaveBeenCalled());
    // react-dropzone only invokes the user's onDragEnter once it sees a
    // "Files" drag type on dataTransfer -- a bare dragEnter with no
    // dataTransfer is silently ignored, same as a drag of plain text.
    fireEvent.dragEnter(await screen.findByText("Drop a file here to start now"), {
      dataTransfer: { types: ["Files"], files: [] },
    });

    expect(await screen.findByText("Couldn't reach the server")).toBeInTheDocument();
    expect(await screen.findByText("Set up a backend first")).toBeInTheDocument();
  });

  it("does not appear once the server is reachable", async () => {
    api.health.mockResolvedValue({
      version: "0", backend: "gemini", anthropic_key_present: false, gemini_key_present: false,
    });
    renderApp();

    await waitFor(() => expect(api.health).toHaveBeenCalled());
    expect(screen.queryByText("Couldn't reach the server")).not.toBeInTheDocument();
  });
});
