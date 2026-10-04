import { useEffect, useRef } from "react";
import { ActionIcon, Alert, Anchor, AppShell, Burger, Group, ScrollArea, Text, Tooltip, UnstyledButton } from "@mantine/core";
import { useDisclosure, useLocalStorage } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconLayoutSidebarLeftExpand } from "@tabler/icons-react";
import { AppStateProvider, useAppState } from "./state.jsx";
import { T, useT } from "./i18n.jsx";
import { MOCK } from "./config.js";
import { serveCommand } from "./serveCommand.js";
import Logo from "./components/Logo.jsx";
import ThemeToggle from "./components/ThemeToggle.jsx";
import LangToggle from "./components/LangToggle.jsx";
import Rail from "./components/Rail.jsx";
import Overview from "./components/Overview.jsx";
import Sample from "./components/Sample.jsx";
import Setup from "./components/Setup.jsx";
import Queue from "./components/Queue.jsx";
import Estimate from "./components/Estimate.jsx";
import Running from "./components/Running.jsx";
import Results from "./components/Results.jsx";
import DevSwitcher from "./components/DevSwitcher.jsx";

const SCREEN_COMPONENTS = {
  overview: Overview,
  sample: Sample,
  setup: Setup,
  queue: Queue,
  estimate: Estimate,
  running: Running,
  results: Results,
};

function Shell() {
  const { screen, goto, apiError, setApiError, healthError, dropzoneTouched } = useAppState();
  const t = useT();
  const [mobileOpen, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopCollapsed, setDesktopCollapsed] = useLocalStorage({ key: "pp-rail-collapsed", defaultValue: false });
  const ScreenComponent = SCREEN_COMPONENTS[screen] ?? Overview;
  const showSuggested = screen !== "overview" && screen !== "sample" && screen !== "setup";

  // Fires once -- the first time a visitor who has touched the dropzone
  // turns out to have no reachable server -- rather than on every health
  // re-probe, so it reads as a one-time nudge toward setup, not a nag.
  const setupHintShown = useRef(false);
  useEffect(() => {
    if (MOCK || !dropzoneTouched || !healthError || setupHintShown.current) return;
    setupHintShown.current = true;
    notifications.show({
      title: t("app.setupHintTitle"),
      message: t("app.setupHintBody"),
      color: "flag",
      autoClose: 8000,
    });
  }, [dropzoneTouched, healthError, t]);

  return (
    <AppShell
      header={{ height: 58 }}
      navbar={{ width: 296, breakpoint: "md", collapsed: { mobile: !mobileOpen, desktop: desktopCollapsed } }}
      footer={{ height: 40 }}
      padding={0}
    >
      <AppShell.Header>
        <Group h="100%" px={20} justify="space-between">
          <Group gap={14}>
            <Burger opened={mobileOpen} onClick={toggleMobile} hiddenFrom="md" size="sm" aria-label={t("app.toggleSettings")} />
            <UnstyledButton
              onClick={() => goto("overview")}
              aria-label={t("app.brandAria")}
              className="pp-brand"
              style={{ display: "flex", alignItems: "center", gap: 9, fontFamily: '"Archivo Expanded", "Arial Narrow", sans-serif', fontWeight: 800, fontStretch: "118%", fontSize: 16.5 }}
            >
              <Logo />
              palimpsest
            </UnstyledButton>
          </Group>
          <Group gap={10}>
            <LangToggle />
            <ThemeToggle />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar>
        <AppShell.Section grow component={ScrollArea}>
          <Rail showSuggested={showSuggested} onCollapse={() => setDesktopCollapsed(true)} />
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        {!MOCK && apiError && (
          <Alert
            icon={<IconAlertTriangle size={16} />}
            color="flag"
            variant="light"
            withCloseButton
            onClose={() => setApiError(null)}
            m={20}
            title={t("app.backendUnreachable")}
          >
            {apiError.message}{" "}
            <Anchor component="button" type="button" size="sm" onClick={() => goto("setup")}>
              {t("app.setupLink")}
            </Anchor>
          </Alert>
        )}
        {/* Only when apiError isn't already showing -- both are driven by
            the same underlying "can't reach the server" fact and
            stacking them would just repeat it. This one is health-probe
            driven (state.jsx), so unlike apiError it doesn't need a user
            action to appear -- it's live the moment the probe resolves.
            Gated on dropzoneTouched so a brand-new visitor who hasn't
            interacted with the dropzone yet isn't instantly greeted with
            a warning before they've done anything (see state.jsx's
            setup-hint toast, which fires once at the same trigger). Not
            dismissible: it reflects current health, not a one-time event,
            and disappears on its own the moment a probe succeeds. */}
        {!MOCK && !apiError && healthError && dropzoneTouched && (
          <Alert
            icon={<IconAlertTriangle size={16} />}
            color="flag"
            variant="light"
            m={20}
            title={t("app.backendUnreachable")}
          >
            <T k="app.serverUnreachableBody" params={{ cmd: serveCommand() }} />{" "}
            <Anchor component="button" type="button" size="sm" onClick={() => goto("setup")}>
              {t("app.setupLink")}
            </Anchor>
          </Alert>
        )}
        <ScreenComponent />
      </AppShell.Main>

      <AppShell.Footer>
        <Group h="100%" px={20} justify="center" wrap="wrap" gap={4}>
          <Text size="11px" ff="monospace" c="dimmed">
            <Anchor href="https://github.com/ianperaltahirujo/palimpsest" target="_blank" rel="noopener" size="11px" ff="monospace">
              {t("footer.github")}
            </Anchor>
            {" · "}
            <Anchor href="https://pypi.org/project/palimpsest-translate/" target="_blank" rel="noopener" size="11px" ff="monospace">
              {t("footer.pypi")}
            </Anchor>
            {" · "}
            <Anchor
              href="https://github.com/ianperaltahirujo/palimpsest/blob/main/LICENSE"
              target="_blank" rel="noopener" size="11px" ff="monospace"
            >
              {t("footer.license")}
            </Anchor>
          </Text>
        </Group>
      </AppShell.Footer>

      {/* The sidebar's own collapse button is unreachable once it's
          hidden -- this small edge tab is the only way back in, same
          idiom as the pass-2 prototype's .rail-reveal. */}
      {desktopCollapsed && (
        <Tooltip label={t("app.showSidebar")} position="right">
          <ActionIcon
            variant="default"
            onClick={() => setDesktopCollapsed(false)}
            visibleFrom="md"
            aria-label={t("app.showSidebar")}
            style={{ position: "fixed", left: 0, top: 70, zIndex: 200, borderRadius: "0 6px 6px 0", borderLeft: "none" }}
          >
            <IconLayoutSidebarLeftExpand size={16} />
          </ActionIcon>
        </Tooltip>
      )}

      {MOCK && <DevSwitcher />}
    </AppShell>
  );
}

export default function App() {
  return (
    <AppStateProvider>
      <Shell />
    </AppStateProvider>
  );
}
