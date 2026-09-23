import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";
const root = "/Users/aoiseki/GitHub/Accenture_CEO";
const dir = path.join(root, "提出物一覧");
const files = await fs.readdir(dir);
const copyName = files.find((name) => name.normalize("NFC") === "アクセンチュア_最終報告（作成中）のコピー.pptx");
const p = await PresentationFile.importPptx(await FileBlob.load(path.join(dir, copyName)));
for (const n of [8,9,10,11]) {
  const slide = p.slides.getItem(n-1);
  const layout = await slide.export({format:"layout"});
  await fs.writeFile(path.join(root,".codex-pptx-work",`slide-${n}.layout.json`), await layout.text());
  const preview = await slide.export({format:"png",scale:1.5});
  await fs.writeFile(path.join(root,".codex-pptx-work",`slide-${n}.png`), new Uint8Array(await preview.arrayBuffer()));
}
const snap = await p.inspect({target:{id:"sl/jetc3ut0",beforeLines:0,afterLines:80},kind:"slide,textbox,shape,layout",maxChars:20000});
console.log(snap.ndjson);
