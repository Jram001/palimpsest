import { Button, Text } from "@mantine/core";
import { Dropzone } from "@mantine/dropzone";
import { notifications } from "@mantine/notifications";
import PageWipe from "./PageWipe.jsx";
import { useAppState } from "../state.jsx";
import { useT } from "../i18n.jsx";
import { MOCK } from "../config.js";
import { UPLOAD_ACCEPT } from "../accept.js";

export default function Sample() {
  const { goto, addUploads, markDropzoneTouched } = useAppState();
  const t = useT();

  async function handleFiles(files) {
    if (MOCK || files.length === 0) {
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
    <div className="pp-page-pad pp-page-pad--sample" style={{ maxWidth: 1200 }}>
      <Button variant="default" size="xs" mb={18} onClick={() => goto("overview")}>
        {t("sample.back")}
      </Button>
      {/* Dropping directly on the hero page counts too, not just the slim
          dropzone bar beneath it -- matches the copy below. */}
      <div
        onDragOver={(e) => e.preventDefault()}
        onDragEnter={markDropzoneTouched}
        onDrop={(e) => {
          e.preventDefault();
          handleFiles(Array.from(e.dataTransfer.files || []));
        }}
      >
        {/* Root-absolute paths (/sample/*.png) 404 once this build is
            published under a subpath (e.g. GitHub Pages' /<repo>/) --
            BASE_URL reflects vite.config.js's own `base` setting, so this
            resolves the same way the built <script>/<link> tags already
            do. */}
        <PageWipe
          baseSrc={`${import.meta.env.BASE_URL}sample/output.png`}
          baseAlt={t("sample.altOut")}
          wipeSrc={`${import.meta.env.BASE_URL}sample/source.png`}
          wipeAlt={t("sample.altSrc")}
          sample
        />
      </div>
      <Text ta="center" ff="monospace" size="xs" c="dimmed" mt={14}>
        {t("sample.caption")}
      </Text>

      <Dropzone
        onDrop={handleFiles}
        onDragEnter={markDropzoneTouched}
        onFileDialogOpen={markDropzoneTouched}
        mt={26}
        accept={UPLOAD_ACCEPT}
        acceptColor="accept"
        rejectColor="flag"
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <Text fw={700} size="sm">
              {t("sample.dropTitle")}
            </Text>
            <Text size="xs" c="dimmed" mt={3}>
              {t("sample.dropSub")}
            </Text>
          </div>
          <Button>{t("common.chooseFiles")}</Button>
        </div>
      </Dropzone>
    </div>
  );
}
