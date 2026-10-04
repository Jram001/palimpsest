import { Button, Text, Title, UnstyledButton } from "@mantine/core";
import { IconArrowRight, IconLifebuoy } from "@tabler/icons-react";
import { Dropzone } from "@mantine/dropzone";
import { notifications } from "@mantine/notifications";
import { useAppState } from "../state.jsx";
import { T, useT } from "../i18n.jsx";
import { MOCK } from "../config.js";
import { UPLOAD_ACCEPT } from "../accept.js";

const STEP_KEYS = ["overview.step1", "overview.step2", "overview.step3"];

export default function Overview() {
  const { goto, addUploads, markDropzoneTouched } = useAppState();
  const t = useT();

  async function handleDrop(files) {
    if (MOCK) {
      goto("queue");
      return;
    }
    try {
      await addUploads(files);
      goto("queue");
    } catch (e) {
      notifications.show({ message: e.message, color: "flag" });
    }
  }
  return (
    <div style={{ maxWidth: 640, padding: "56px 40px 80px", margin: "0 auto" }}>
      <Text size="xs" tt="uppercase" c="dimmed" ff="monospace" mb={8} style={{ letterSpacing: ".09em" }}>
        {t("overview.eyebrow")}
      </Text>
      <Title order={1} style={{ fontSize: 34, lineHeight: 1.15 }}>
        {t("overview.title")}
      </Title>
      <Text size="md" c="dimmed" mt={14} style={{ fontSize: 15.5 }}>
        {t("overview.body")}
      </Text>

      <div style={{ display: "flex", flexDirection: "column", gap: 18, marginTop: 32 }}>
        {STEP_KEYS.map((key, i) => (
          <div key={key} style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
            <span
              style={{
                flex: "0 0 auto",
                width: 26,
                height: 26,
                borderRadius: "50%",
                border: "1.5px solid var(--pp-rule)",
                display: "grid",
                placeItems: "center",
                fontFamily: "var(--mantine-font-family-monospace)",
                fontSize: 12,
                color: "var(--pp-ink-soft)",
              }}
            >
              {i + 1}
            </span>
            <Text size="sm" c="dimmed" style={{ lineHeight: 1.55 }}>
              <T k={key} />
            </Text>
          </div>
        ))}
      </div>

      <Button mt={32} onClick={() => goto("sample")}>
        {t("overview.cta")}
      </Button>

      <Dropzone
        onDrop={handleDrop}
        onDragEnter={markDropzoneTouched}
        onFileDialogOpen={markDropzoneTouched}
        mt={40}
        p={28}
        accept={UPLOAD_ACCEPT}
        acceptColor="accept"
        rejectColor="flag"
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap", minHeight: 76 }}>
          <div>
            <Text fw={700} size="sm">
              {t("overview.dropTitle")}
            </Text>
            <Text size="xs" c="dimmed" mt={3}>
              {t("overview.dropExts")}
            </Text>
          </div>
          <Button variant="default">{t("common.chooseFiles")}</Button>
        </div>
      </Dropzone>

      <UnstyledButton
        onClick={() => goto("setup")}
        className="pp-help-card"
        aria-label={t("overview.helpAria")}
        mt={36}
      >
        <span className="pp-help-icon">
          <IconLifebuoy size={18} stroke={1.7} />
        </span>
        <span style={{ flex: 1, minWidth: 0 }}>
          <Text fw={700} size="sm">
            {t("overview.helpTitle")}
          </Text>
          <Text size="xs" c="dimmed" mt={3} style={{ lineHeight: 1.5 }}>
            {t("overview.helpBody")}
          </Text>
        </span>
        <span className="pp-help-cta">
          {t("overview.helpCta")}
          <IconArrowRight size={14} />
        </span>
      </UnstyledButton>
    </div>
  );
}
