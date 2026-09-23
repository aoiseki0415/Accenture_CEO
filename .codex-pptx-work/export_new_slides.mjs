import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const root = "/Users/aoiseki/GitHub/Accenture_CEO";
const input = path.join(root, ".codex-pptx-output", "アクセンチュア_最終報告（原因分析・施策案追加）.pptx");
const outDir = path.join(root, ".codex-pptx-artifact-preview");
await fs.mkdir(outDir, { recursive: true });
const presentation = await PresentationFile.importPptx(await FileBlob.load(input));
for (let index = 11; index <= 13; index += 1) {
  const blob = await presentation.export({ slide: presentation.slides.getItem(index), format: "png", scale: 1.5 });
  const bytes = blob && typeof blob.arrayBuffer === "function"
    ? Buffer.from(await blob.arrayBuffer())
    : Buffer.from(blob);
  await fs.writeFile(path.join(outDir, `slide-${index + 1}.png`), bytes);
}
