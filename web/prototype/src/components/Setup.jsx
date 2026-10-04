import { useState } from "react";
import { Anchor, Button, CopyButton, Group, Text, Title } from "@mantine/core";
import { IconCheck, IconCopy } from "@tabler/icons-react";
import { useAppState } from "../state.jsx";
import { T, useT } from "../i18n.jsx";
import { MOCK } from "../config.js";
import { serveCommand } from "../serveCommand.js";

function Command({ children }) {
  const t = useT();
  return (
    <div className="pp-cmd">
      <code>{children}</code>
      <CopyButton value={children} timeout={1600}>
        {({ copied, copy }) => (
          <button type="button" className="pp-cmd-copy" onClick={copy} aria-label={t("setup.copy")}>
            {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
            {copied ? t("setup.copied") : t("setup.copy")}
          </button>
        )}
      </CopyButton>
    </div>
  );
}

function Step({ n, title, children }) {
  return (
    <div className="pp-setup-step">
      <span className="pp-setup-num">{n}</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <Text fw={700} size="md" mb={6}>
          {title}
        </Text>
        {children}
      </div>
    </div>
  );
}

function Body({ k }) {
  return (
    <Text size="sm" c="dimmed" style={{ lineHeight: 1.6 }} mb={10}>
      <T k={k} />
    </Text>
  );
}

function Fix({ q, children }) {
  return (
    <div className="pp-fix">
      <Text fw={700} size="sm">
        {q}
      </Text>
      <Text size="sm" c="dimmed" mt={4} style={{ lineHeight: 1.6 }}>
        {children}
      </Text>
    </div>
  );
}

// Static instructions page: reachable from Overview's help card and from
// the "couldn't reach the server" banners. Not part of the translate flow,
// so it never touches uploads/jobs -- only the shared health probe, for the
// "Check connection" button.
export default function Setup() {
  const { goto, health, healthError, refreshHealth } = useAppState();
  const t = useT();
  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState(false);

  async function recheck() {
    setChecking(true);
    try {
      await refreshHealth();
    } catch {
      // healthError carries the failure; nothing more to do here.
    }
    setChecked(true);
    setChecking(false);
  }

  const connected = checked && !healthError && !!health;
  const failed = checked && !!healthError;

  return (
    <div style={{ maxWidth: 680, padding: "40px 40px 80px", margin: "0 auto" }}>
      <Button variant="default" size="xs" mb={22} onClick={() => goto("overview")}>
        {t("setup.back")}
      </Button>

      <Text size="xs" tt="uppercase" c="dimmed" ff="monospace" mb={8} style={{ letterSpacing: ".09em" }}>
        {t("setup.eyebrow")}
      </Text>
      <Title order={1} style={{ fontSize: 32, lineHeight: 1.15 }}>
        {t("setup.title")}
      </Title>
      <Text c="dimmed" mt={12} style={{ fontSize: 15.5, lineHeight: 1.6 }}>
        {t("setup.intro")}
      </Text>

      <div className="pp-setup-steps">
        <Step n={1} title={t("setup.s1.title")}>
          <Body k="setup.s1.body" />
          <Anchor href="https://www.python.org/downloads/" target="_blank" rel="noopener" size="sm">
            {t("setup.s1.link")}
          </Anchor>
        </Step>

        <Step n={2} title={t("setup.s2.title")}>
          <Body k="setup.s2.body" />
          <Command>pip install "palimpsest-translate[server,gemini]"</Command>
        </Step>

        <Step n={3} title={t("setup.s3.title")}>
          <Body k="setup.s3.body" />
          <Command>{serveCommand()}</Command>
          <Text size="xs" c="dimmed" mt={8}>
            {t("setup.s3.note")}
          </Text>
        </Step>

        <Step n={4} title={t("setup.s4.title")}>
          <Body k="setup.s4.body" />
          <Anchor href="https://aistudio.google.com/apikey" target="_blank" rel="noopener" size="sm">
            {t("backend.getKey")}
          </Anchor>
        </Step>
      </div>

      {!MOCK && (
        <div className="pp-check" data-state={connected ? "ok" : failed ? "fail" : "idle"}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Text fw={700} size="sm">
              {t("setup.check.title")}
            </Text>
            <Text size="xs" c="dimmed" mt={3}>
              {connected ? t("setup.check.ok") : failed ? t("setup.check.fail") : t("setup.check.idle")}
            </Text>
          </div>
          <Button size="xs" variant={connected ? "default" : "filled"} loading={checking} onClick={recheck}>
            {t("setup.check.btn")}
          </Button>
        </div>
      )}

      <Title order={2} mt={48} style={{ fontSize: 20 }}>
        {t("setup.opt.title")}
      </Title>
      <Text size="sm" c="dimmed" mt={6} mb={14}>
        {t("setup.opt.intro")}
      </Text>
      <Fix q={t("setup.opt.ocr.q")}>
        <T k="setup.opt.ocr.a" />
      </Fix>
      <Command>pip install "palimpsest-translate[ocr]"</Command>
      <div style={{ height: 14 }} />
      <Fix q={t("setup.opt.office.q")}>
        <T k="setup.opt.office.a" />{" "}
        <Anchor href="https://www.libreoffice.org/download/download/" target="_blank" rel="noopener" size="sm">
          {t("setup.opt.office.link")}
        </Anchor>
      </Fix>
      <div style={{ height: 14 }} />
      <Fix q={t("setup.opt.claude.q")}>
        <T k="setup.opt.claude.a" />
      </Fix>
      <Command>pip install "palimpsest-translate[anthropic]"</Command>

      <Title order={2} mt={48} mb={14} style={{ fontSize: 20 }}>
        {t("setup.fix.title")}
      </Title>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <Fix q={t("setup.fix.unreach.q")}>
          <T k="setup.fix.unreach.a" />
        </Fix>
        <Fix q={t("setup.fix.notfound.q")}>
          <T k="setup.fix.notfound.a" />
        </Fix>
        <Fix q={t("setup.fix.port.q")}>
          <T k="setup.fix.port.a" />
        </Fix>
        <Fix q={t("setup.fix.key.q")}>
          <T k="setup.fix.key.a" />
        </Fix>
        <Fix q={t("setup.fix.scan.q")}>
          <T k="setup.fix.scan.a" />
        </Fix>
      </div>

      <Group mt={40}>
        <Button onClick={() => goto("overview")}>{t("setup.done")}</Button>
        <Anchor href="https://github.com/ianperaltahirujo/palimpsest/issues" target="_blank" rel="noopener" size="sm">
          {t("setup.issues")}
        </Anchor>
      </Group>
    </div>
  );
}
