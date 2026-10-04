import { useState } from "react";
import { Alert, Badge, Button, Group, SegmentedControl, Stack, Text, Title } from "@mantine/core";
import { IconAlertTriangle, IconX } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { QUEUE_FILES } from "../state.jsx";
import { useAppState } from "../state.jsx";
import { T, useT } from "../i18n.jsx";
import { MOCK } from "../config.js";

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// The file-type badge used to hardcode "PDF" -- harmless before Office
// uploads existed, misleading now that .docx/.pptx/.xlsx are real
// upload targets (see the root README's Quickstart).
function extLabel(name) {
  const ext = (name || "").split(".").pop();
  return ext ? ext.toUpperCase() : "?";
}

// Endonyms on purpose, same as any language picker: a Spanish reader on the
// English UI (or the reverse) must still be able to find their own language.
const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
];

export default function Queue() {
  const { goto, uploads, removeUpload, runEstimate, targets, setTarget } = useAppState();
  const t = useT();

  // First loading state in this app -- the pattern for the rest. POST
  // /api/estimate is genuinely slow (server-side it is one count_tokens
  // round trip per unique paragraph, serially), so the button has to say
  // something. Mantine's `loading` also sets the real disabled attribute
  // (Button.mjs: disabled || loading), which already blocks a second
  // click; the explicit early return covers a synchronous re-entry that
  // beats the re-render, e.g. a held Enter key.
  const [estimating, setEstimating] = useState(false);

  // MOCK mode keeps its own static fixture list; real mode reads from
  // the uploads the Overview/Sample dropzones actually sent to the
  // server (see state.jsx's addUploads). Shapes are made to line up
  // (name/kind/size/pages) so the JSX below doesn't need to branch.
  const files = MOCK
    ? QUEUE_FILES
    : uploads.map((u) => ({
        id: u.file_id, name: u.name, kind: u.kind,
        size: formatBytes(u.size), pages: u.pages,
      }));
  const hasScan = files.some((f) => f.kind === "scan");
  const scanFile = files.find((f) => f.kind === "scan");

  async function handleNext() {
    if (MOCK) {
      goto("estimate");
      return;
    }
    if (estimating) return;
    setEstimating(true);
    try {
      await runEstimate();
      goto("estimate");
    } catch (e) {
      notifications.show({ message: e.message, color: "flag" });
    } finally {
      // goto() above unmounts Queue on success, so this fires on an
      // unmounted component in the happy path -- a deliberate no-op
      // (React 18 dropped the "can't update unmounted component"
      // warning). Resetting in `finally` rather than only in `catch` is
      // what makes the button recoverable if `goto` itself ever throws.
      setEstimating(false);
    }
  }

  return (
    <div className="pp-state-pad">
      <Text size="xs" tt="uppercase" c="dimmed" ff="monospace" mb={8} style={{ letterSpacing: ".09em" }}>
        {t("common.step1")}
      </Text>
      <Title order={1} className="pp-stage-h1">
        {t("queue.title")}
      </Title>
      <Text c="dimmed" mt={8} maw="60ch">
        {t("queue.body")}
      </Text>

      <Stack gap={10} mt={22}>
        {files.map((f) => (
          <Group key={f.id || f.name} wrap="wrap" gap={14} p="14px 16px" style={{ border: "1px solid var(--pp-rule)", borderRadius: 3, background: "var(--pp-leaf-raised)" }}>
            <div style={{ width: 34, height: 34, border: "1px solid var(--pp-rule)", borderRadius: 3, display: "grid", placeItems: "center", fontFamily: "var(--mantine-font-family-monospace)", fontSize: 9, color: "var(--pp-ink-soft)", flex: "0 0 auto" }}>
              {extLabel(f.name)}
            </div>
            <div style={{ flex: "1 1 180px", minWidth: 0 }}>
              <Text fw={600} size="sm" truncate>
                {f.name}
              </Text>
              <Group gap={10} mt={3}>
                <Badge size="xs" variant="light" color={f.kind === "scan" ? "warn" : "ok"} radius="sm">
                  {t(`queue.kind.${f.kind}`)}
                </Badge>
                <Text size="xs" ff="monospace" c="dimmed">
                  {f.size}
                </Text>
                {f.pages != null && (
                  <Text size="xs" ff="monospace" c="dimmed">
                    {t("queue.pagesUnit", { n: f.pages })}
                  </Text>
                )}
              </Group>
            </div>
            <div style={{ flex: "0 0 auto" }}>
              <Text size="10px" tt="uppercase" c="dimmed" ff="monospace" mb={4} style={{ letterSpacing: ".08em" }}>
                {t("queue.translateTo")}
              </Text>
              <SegmentedControl
                size="xs"
                value={targets[f.id || f.name] ?? "en"}
                onChange={(lang) => setTarget(f.id || f.name, lang)}
                data={LANGUAGE_OPTIONS}
                aria-label={t("queue.translateToAria", { name: f.name })}
              />
            </div>
            <Button
              variant="subtle" color="gray" size="xs" px={6}
              aria-label={t("queue.removeAria", { name: f.name })}
              onClick={() => (MOCK ? null : removeUpload(f.id))}
            >
              <IconX size={14} />
            </Button>
          </Group>
        ))}
      </Stack>

      {hasScan && (
        <Alert icon={<IconAlertTriangle size={16} />} color="warn" mt={14} variant="light">
          <Text size="sm">
            <T k="queue.scanAlert" params={{ name: scanFile?.name }} />
          </Text>
        </Alert>
      )}

      <Group mt={28} gap={10}>
        <Button variant="default" onClick={() => goto("sample")} disabled={estimating}>
          {t("common.back")}
        </Button>
        <Button onClick={handleNext} loading={estimating} disabled={files.length === 0}>
          {t("queue.cta")}
        </Button>
      </Group>
    </div>
  );
}
