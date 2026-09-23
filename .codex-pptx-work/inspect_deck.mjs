import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const root = "/Users/aoiseki/GitHub/Accenture_CEO";
const dir = path.join(root, "提出物一覧");
const files = await fs.readdir(dir);
const copyName = files.find((name) => name.normalize("NFC") === "アクセンチュア_最終報告（作成中）のコピー.pptx");
if (!copyName) throw new Error(`copy deck not found: ${files.join("\n")}`);
const sourcePath = path.join(dir, copyName);
const p = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const snap = await p.inspect({kind:"deck,slide,textbox,shape,image,table,chart,notes,layout", maxChars:50000});
await fs.mkdir(path.join(root, ".codex-pptx-work"), {recursive:true});
await fs.writeFile(path.join(root, ".codex-pptx-work", "inspect.ndjson"), snap.ndjson);
const montage = await p.export({format:"png", montage:{format:"png", columns:4, slideWidth:420, padding:10, gap:10, background:"#dddddd"}});
await fs.writeFile(path.join(root, ".codex-pptx-work", "montage.png"), new Uint8Array(await montage.arrayBuffer()));
console.log(JSON.stringify({sourcePath, slideCount:p.slides.length, frame:p.slides.getItem(0).frame}, null, 2));
