import { getApiBase } from "./config.js";

// The exact command to fix "unreachable" -- only names --allow-origin
// when this page's own origin genuinely differs from the API's (the
// standalone/GitHub Pages build; see config.js's VITE_STANDALONE). A
// same-origin production build (palimpsest serve) or the npm run dev
// proxy both resolve getApiBase() to "" and need no flag at all.
export function serveCommand() {
  const apiBase = getApiBase();
  const pageOrigin = window.location.origin;
  const apiOrigin = apiBase ? new URL(apiBase, pageOrigin).origin : pageOrigin;
  return apiOrigin === pageOrigin ? "palimpsest serve" : `palimpsest serve --allow-origin ${pageOrigin}`;
}
