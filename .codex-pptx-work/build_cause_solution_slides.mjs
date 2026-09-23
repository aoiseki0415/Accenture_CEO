import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const root = "/Users/aoiseki/GitHub/Accenture_CEO";
const skillDir = "/Users/aoiseki/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations";
const buildDir = path.join(root, ".codex-pptx-work");
const stagingDir = path.join(root, ".codex-finalizer");
const outputDir = path.join(root, ".codex-pptx-output");
const dir = path.join(root, "提出物一覧");
const files = await fs.readdir(dir);
const copyName = files.find((name) => name.normalize("NFC") === "アクセンチュア_最終報告（作成中）のコピー.pptx");
if (!copyName) throw new Error("コピー版PowerPointが見つかりません");
const sourcePath = path.join(dir, copyName);
const finalPath = path.join(outputDir, "アクセンチュア_最終報告（原因分析・施策案追加）.pptx");

await fs.mkdir(buildDir, { recursive: true });
await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(outputDir, { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
// Use a macOS-native Japanese gothic font for the newly authored text. It is
// visually close to the deck's Source Han Sans JP styling and renders reliably
// in both PowerPoint and LibreOffice.
const FONT = "Hiragino Kaku Gothic ProN";
const C = {
  navy: "#42577F",
  text: "#37343A",
  muted: "#6F6B70",
  border: "#DDD8D5",
  panel: "#F7F3F1",
  blush: "#F9E8E5",
  red: "#C00000",
  paleRed: "#FCE8E6",
  green: "#58A977",
  paleGreen: "#E8F3EB",
  orange: "#E98A35",
  paleOrange: "#FAE9D8",
  purple: "#7C5AA6",
  pink: "#D68AA3",
  gray: "#88848A",
  paleGray: "#EFEEEE",
  white: "#FFFFFF",
  darkNavy: "#1E3A5F",
};

function addText(slide, text, x, y, w, h, opts = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name: opts.name,
    position: { left: x, top: y, width: w, height: h },
    fill: opts.fill ?? "none",
    line: opts.line ?? { style: "solid", fill: "none", width: 0 },
    borderRadius: opts.borderRadius,
  });
  if (Array.isArray(text)) shape.text.set(text);
  else shape.text = text;
  shape.text.style = {
    typeface: FONT,
    fontSize: opts.fontSize ?? 18,
    bold: opts.bold ?? false,
    color: opts.color ?? C.text,
    alignment: opts.align ?? "left",
    verticalAlignment: opts.valign ?? "middle",
    autoFit: opts.autoFit ?? "shrinkText",
    wrap: "square",
    insets: opts.insets ?? { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function addBox(slide, x, y, w, h, fill, line = C.border, radius = 12) {
  return slide.shapes.add({
    geometry: "roundRect",
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill: line, width: 1 },
    borderRadius: radius,
  });
}

function addHeader(slide, section, title, pageNumber) {
  addText(slide, section, 14, 10, 300, 30, { fontSize: 14, color: "#111111" });
  addText(slide, title, 45, 58, 1185, 64, { fontSize: 29, bold: true, color: C.navy, valign: "top" });
  addText(slide, String(pageNumber), 1210, 682, 40, 22, { fontSize: 12, color: "#111111", align: "right" });
}

function addBottomCallout(slide, text, opts = {}) {
  addBox(slide, 50, opts.y ?? 596, 1180, opts.h ?? 80, opts.fill ?? C.paleRed, opts.line ?? opts.fill ?? C.paleRed, 10);
  addText(slide, text, 72, (opts.y ?? 596) + 10, 1136, (opts.h ?? 80) - 20, {
    fontSize: opts.fontSize ?? 19,
    bold: true,
    color: opts.color ?? C.red,
    align: "center",
  });
}

function addDivider(slide, x1, y1, x2, y2, color = C.border, width = 1) {
  return slide.shapes.add({
    geometry: "line",
    position: { left: x1, top: y1, width: x2 - x1, height: y2 - y1 },
    fill: "none",
    line: { style: "solid", fill: color, width },
  });
}

function addStackedBar(slide, x, y, w, h, bottomPct, bottomColor, topColor, labels) {
  const bottomH = h * bottomPct / 100;
  const topH = h - bottomH;
  const top = slide.shapes.add({
    geometry: "rect",
    position: { left: x, top: y, width: w, height: topH },
    fill: topColor,
    line: { style: "solid", fill: C.white, width: 1 },
  });
  const bottom = slide.shapes.add({
    geometry: "rect",
    position: { left: x, top: y + topH, width: w, height: bottomH },
    fill: bottomColor,
    line: { style: "solid", fill: C.white, width: 1 },
  });
  if (labels?.top) addText(slide, labels.top, x + 4, y + 2, w - 8, Math.max(26, topH - 4), { fontSize: labels.topSize ?? 14, bold: true, color: labels.topColor ?? C.text, align: "center" });
  if (labels?.bottom) addText(slide, labels.bottom, x + 4, y + topH + 2, w - 8, Math.max(28, bottomH - 4), { fontSize: labels.bottomSize ?? 17, bold: true, color: labels.bottomColor ?? C.white, align: "center" });
  return { top, bottom };
}

// Insert three slides immediately after the current problem-summary slide (slide 11).
const anchor = presentation.slides.getItem(10);
// Imported decks currently only accept an existing imported slide as the relative
// insertion anchor. Insert in reverse order after slide 11 so the final order is
// s1 -> s2 -> s3.
presentation.slides.insert({ after: anchor, layoutId: "/ppt/slideLayouts/slideLayout62.xml" });
presentation.slides.insert({ after: anchor, layoutId: "/ppt/slideLayouts/slideLayout62.xml" });
presentation.slides.insert({ after: anchor, layoutId: "/ppt/slideLayouts/slideLayout62.xml" });
const s1 = presentation.slides.getItem(11);
const s2 = presentation.slides.getItem(12);
const s3 = presentation.slides.getItem(13);

// Slide 12: bottleneck identification.
addHeader(s1, "原因分析｜ボトルネックの特定", "若年層では、「対応」商品を購入したことのある人の少なさがボトルネックである", 12);

addBox(s1, 50, 150, 560, 250, C.panel);
addText(s1, "購買記録数は、購入の「広がり」と「深さ」に分けられる", 75, 168, 510, 40, { fontSize: 19, bold: true });
addBox(s1, 78, 230, 210, 92, C.paleGreen, C.green, 10);
addText(s1, "購入経験者の割合", 92, 238, 182, 34, { fontSize: 18, bold: true, color: C.green, align: "center" });
addText(s1, "どれだけ多くの人に\n購入が広がったか", 94, 272, 178, 40, { fontSize: 14, color: C.text, align: "center" });
addText(s1, "×", 296, 246, 36, 56, { fontSize: 30, bold: true, color: C.muted, align: "center" });
addBox(s1, 340, 230, 236, 92, C.paleOrange, C.orange, 10);
addText(s1, "購入経験者1人あたりの購入回数", 352, 236, 212, 40, { fontSize: 16, bold: true, color: C.orange, align: "center" });
addText(s1, "購入した人が\nどれだけ繰り返したか", 358, 274, 200, 38, { fontSize: 14, color: C.text, align: "center" });
addText(s1, "購買記録数（件／1,000人）＝ 上記2要素 × 1,000", 96, 344, 468, 35, { fontSize: 16, bold: true, color: C.navy, align: "center" });

addBox(s1, 640, 150, 590, 250, C.white, C.border, 12);
addText(s1, "若年層と中高年層の差をシャープレイ分解", 670, 168, 530, 38, { fontSize: 19, bold: true });
addText(s1, "購買記録数：1.208 → 1.953件／1,000人", 670, 210, 530, 28, { fontSize: 15, color: C.muted });
addText(s1, "差への寄与", 670, 255, 110, 28, { fontSize: 15, bold: true, color: C.text });
const barX = 785, barY = 252, barW = 395, barH = 55;
s1.shapes.add({ geometry: "rect", position: { left: barX, top: barY, width: barW * 0.669, height: barH }, fill: C.green, line: { style: "solid", fill: C.white, width: 1 } });
s1.shapes.add({ geometry: "rect", position: { left: barX + barW * 0.669, top: barY, width: barW * 0.331, height: barH }, fill: C.orange, line: { style: "solid", fill: C.white, width: 1 } });
addText(s1, "購入経験者の割合\n66.9%", barX + 8, barY + 3, barW * 0.669 - 16, barH - 6, { fontSize: 16, bold: true, color: C.white, align: "center" });
addText(s1, "1人あたり回数\n33.1%", barX + barW * 0.669 + 4, barY + 3, barW * 0.331 - 8, barH - 6, { fontSize: 14, bold: true, color: C.white, align: "center" });
addText(s1, "男女別でも、購入経験者の割合の寄与が6割超", 670, 330, 530, 34, { fontSize: 16, bold: true, color: C.red, align: "center" });

addBox(s1, 85, 438, 310, 95, C.white, C.border, 10);
addText(s1, "若年層", 105, 451, 100, 30, { fontSize: 18, bold: true, color: "#3B73B9" });
addText(s1, "1.208", 225, 442, 145, 48, { fontSize: 30, bold: true, color: C.navy, align: "right" });
addText(s1, "件／1,000人", 235, 491, 135, 22, { fontSize: 13, color: C.muted, align: "right" });
addText(s1, "→", 418, 452, 58, 54, { fontSize: 34, bold: true, color: C.muted, align: "center" });
addBox(s1, 500, 438, 310, 95, C.white, C.border, 10);
addText(s1, "中高年層", 520, 451, 120, 30, { fontSize: 18, bold: true, color: C.gray });
addText(s1, "1.953", 650, 442, 135, 48, { fontSize: 30, bold: true, color: C.navy, align: "right" });
addText(s1, "件／1,000人", 650, 491, 135, 22, { fontSize: 13, color: C.muted, align: "right" });
addText(s1, "同じ商品群でも、若年層では購入が広がっていない", 850, 452, 325, 60, { fontSize: 18, bold: true, color: C.red, align: "center" });

addBottomCallout(s1, "若年層の購買記録数を改善するには、まず「一度でも購入する人」を増やす必要がある", { y: 570, h: 78, fontSize: 20 });
s1.speakerNotes.textFrame.setText([
  "出典：Notion Step8（2026-09-19更新）",
  "https://app.notion.com/p/3db161f28097803598a0c827bcd2ed2f",
  "話すポイント：購買記録数を広がりと深さに分ける。若年層と中高年層の差の66.9%が購入経験者の割合による。",
].join("\n"));

// Slide 13: role mismatch.
addHeader(s2, "原因分析｜原因特定", "若年層が求める「食事補完」と、「対応」の商品構成がずれている", 13);
addText(s2, "若年層のなかで、利用日数と人数を揃えて比較", 55, 132, 470, 30, { fontSize: 15, color: C.muted });

addBox(s2, 50, 170, 555, 355, C.white, C.border, 12);
addText(s2, "普段の惣菜類の購買構成", 78, 188, 500, 35, { fontSize: 19, bold: true });
const baseY = 478, totalH = 220, bw = 120;
addStackedBar(s2, 135, baseY - totalH, bw, totalH, 85.0, C.green, C.orange, { top: "15.0%", bottom: "85.0%", bottomSize: 18, topColor: C.white });
addStackedBar(s2, 345, baseY - totalH, bw, totalH, 90.4, C.green, C.orange, { top: "9.6%", bottom: "90.4%", bottomSize: 18, topColor: C.white });
addText(s2, "購入経験群", 105, 490, 180, 30, { fontSize: 17, bold: true, color: C.purple, align: "center" });
addText(s2, "購入未経験群", 315, 490, 180, 30, { fontSize: 17, bold: true, color: C.pink, align: "center" });
addText(s2, "食事完結型", 476, 274, 100, 28, { fontSize: 14, bold: true, color: C.orange, align: "center", fill: C.paleOrange, borderRadius: 8 });
addText(s2, "食事補完型", 476, 393, 100, 28, { fontSize: 14, bold: true, color: C.green, align: "center", fill: C.paleGreen, borderRadius: 8 });
addText(s2, "+5.4pt", 276, 400, 85, 38, { fontSize: 18, bold: true, color: C.red, align: "center" });

addText(s2, "→", 617, 305, 70, 70, { fontSize: 38, bold: true, color: C.muted, align: "center" });

addBox(s2, 690, 170, 540, 355, C.panel, C.border, 12);
addText(s2, "セブンの「対応」商品の構成", 718, 188, 485, 35, { fontSize: 19, bold: true });
addStackedBar(s2, 790, 260, 130, 210, 33.3, C.green, C.orange, { top: "食事完結型\n66.7%", bottom: "食事補完型\n33.3%", topSize: 17, bottomSize: 16, topColor: C.white, bottomColor: C.white });
addText(s2, "購入未経験群ほど\n「軽食として補う」役割を求める", 970, 260, 220, 90, { fontSize: 18, bold: true, color: C.green, align: "center" });
addText(s2, "しかし", 1025, 360, 110, 28, { fontSize: 15, color: C.muted, align: "center" });
addText(s2, "「対応」は\n本格的な食事が中心", 970, 395, 220, 75, { fontSize: 18, bold: true, color: C.orange, align: "center" });

addBottomCallout(s2, "求める食事上の役割と商品構成のずれが、購入経験者の少なさにつながっている", { y: 558, h: 88, fontSize: 20 });
s2.speakerNotes.textFrame.setText([
  "出典：Notion Step9（2026-09-19更新）",
  "https://app.notion.com/p/3dc161f2809780528d9ddb62f53de36a",
  "購入経験群と購入未経験群は、セブン利用日数と人数を揃えて比較。",
  "若年層：購入経験群の食事補完型割合85.0%、購入未経験群90.4%、差5.4pt。",
  "セブンの栄養バランス対応商品：食事完結型66.7%、食事補完型33.3%。",
].join("\n"));

// Slide 14: intervention + effect simulation.
addHeader(s3, "施策立案｜提案と効果試算", "食事補完型へ3商品を置き換えれば、黒字を保ちながらローソンとの差を縮められる", 14);

addBox(s3, 50, 150, 450, 235, C.panel, C.border, 12);
addText(s3, "提案する施策", 78, 168, 390, 34, { fontSize: 20, bold: true });
addBox(s3, 82, 225, 145, 105, C.paleOrange, C.orange, 10);
addText(s3, "低実績の\n食事完結型\n3商品", 94, 237, 121, 80, { fontSize: 18, bold: true, color: C.orange, align: "center" });
addText(s3, "→", 240, 244, 70, 70, { fontSize: 36, bold: true, color: C.muted, align: "center" });
addBox(s3, 322, 225, 145, 105, C.paleGreen, C.green, 10);
addText(s3, "若年層向け\n食事補完型\n新商品3商品", 334, 237, 121, 80, { fontSize: 18, bold: true, color: C.green, align: "center" });
addText(s3, "棚スペースを増やさず、1商品対1商品で置き換える", 82, 342, 385, 26, { fontSize: 14, color: C.muted, align: "center" });

addBox(s3, 530, 150, 700, 235, C.white, C.border, 12);
addText(s3, "3商品を置き換えた場合", 558, 168, 645, 34, { fontSize: 20, bold: true });
addBox(s3, 558, 220, 196, 110, "#F5F7FA", C.border, 10);
addText(s3, "平均の購買記録数", 570, 230, 172, 28, { fontSize: 14, color: C.muted, align: "center" });
addText(s3, "0.831 → 1.424", 570, 262, 172, 38, { fontSize: 23, bold: true, color: C.navy, align: "center" });
addText(s3, "+71.3%", 570, 301, 172, 24, { fontSize: 14, bold: true, color: C.green, align: "center" });
addBox(s3, 780, 220, 196, 110, C.paleRed, "#E5C0BC", 10);
addText(s3, "ローソンとの差", 792, 230, 172, 28, { fontSize: 14, color: C.muted, align: "center" });
addText(s3, "21.1%", 792, 262, 172, 38, { fontSize: 27, bold: true, color: C.red, align: "center" });
addText(s3, "縮小", 792, 301, 172, 24, { fontSize: 14, bold: true, color: C.red, align: "center" });
addBox(s3, 1002, 220, 196, 110, C.paleGreen, "#B9D7C2", 10);
addText(s3, "1年間の簡易収支", 1014, 230, 172, 28, { fontSize: 14, color: C.muted, align: "center" });
addText(s3, "+15万円", 1014, 262, 172, 38, { fontSize: 27, bold: true, color: C.green, align: "center" });
addText(s3, "黒字", 1014, 301, 172, 24, { fontSize: 14, bold: true, color: C.green, align: "center" });

addText(s3, "置き換える商品数を1〜5商品で比較", 55, 418, 510, 36, { fontSize: 18, bold: true });
const cases = [
  { n: "1", gap: "7.3%", pnl: "+17万円", fill: C.white, line: C.border, pnlColor: C.green },
  { n: "2", gap: "14.3%", pnl: "+20万円", fill: C.white, line: C.border, pnlColor: C.green },
  { n: "3", gap: "21.1%", pnl: "+15万円", fill: C.paleGreen, line: C.green, pnlColor: C.green },
  { n: "4", gap: "27.7%", pnl: "−4万円", fill: C.paleRed, line: "#E5C0BC", pnlColor: C.red },
  { n: "5", gap: "33.8%", pnl: "−41万円", fill: C.paleRed, line: "#E5C0BC", pnlColor: C.red },
];
const cardW = 210, cardGap = 20, startX = 55;
for (let i = 0; i < cases.length; i++) {
  const d = cases[i];
  const x = startX + i * (cardW + cardGap);
  addBox(s3, x, 468, cardW, 112, d.fill, d.line, 10);
  addText(s3, `${d.n}商品`, x + 10, 478, 65, 30, { fontSize: 17, bold: true, color: d.n === "3" ? C.green : C.text, align: "center" });
  addText(s3, `差の縮小 ${d.gap}`, x + 72, 478, 126, 30, { fontSize: 15, bold: true, color: C.navy, align: "right" });
  addDivider(s3, x + 14, 514, x + cardW - 14, 514, C.border, 1);
  addText(s3, `簡易収支 ${d.pnl}`, x + 14, 526, cardW - 28, 34, { fontSize: 16, bold: true, color: d.pnlColor, align: "center" });
  if (d.n === "3") addText(s3, "最適", x + 70, 574, 70, 24, { fontSize: 14, bold: true, color: C.white, align: "center", fill: C.green, borderRadius: 10 });
}

addBottomCallout(s3, "黒字を最低条件とすると、差を最も縮められる3商品の置き換えが最適", { y: 610, h: 62, fill: C.paleGreen, line: C.paleGreen, color: C.green, fontSize: 19 });
addText(s3, "※ 1年間の第一段階として試算。新商品は既存の食事補完型成功商品の実績、粗利率32%、開発関連費250万円／商品を使用。", 58, 683, 1140, 22, { fontSize: 10, color: C.muted });
s3.speakerNotes.textFrame.setText([
  "出典：Notion Step10（2026-09-20更新）",
  "https://app.notion.com/p/3e0161f28097806a8e42f5d04462ad38",
  "提案：低実績の食事完結型3商品を、若年層向け食事補完型新商品3商品へ置換。",
  "3商品ケース：平均購買記録数0.831→1.424、現状比+71.3%、ローソンとの差21.1%縮小、1年間簡易収支+15万円。",
].join("\n"));

// Existing reference slides use fixed page numbers in their custom layouts.
// Cover those fixed numbers and replace them with the new slide order (15–18).
for (let idx = 14; idx < 18; idx++) {
  const slide = presentation.slides.getItem(idx);
  slide.shapes.add({
    geometry: "rect",
    position: { left: 1198, top: 673, width: 82, height: 47 },
    fill: C.white,
    line: { style: "solid", fill: C.white, width: 0 },
  });
  addText(slide, String(idx + 1), 1212, 684, 42, 25, { fontSize: 12, color: "#111111", align: "right" });
}

const candidatePath = path.join(stagingDir, "candidate-cause-solution.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const sourceSha256 = crypto.createHash("sha256").update(await fs.readFile(sourcePath)).digest("hex");
const { finalizePresentation } = await import(pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href);
const requirements = {
  explicitTotalSlideCount: 18,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [],
};
const result = await finalizePresentation({
  ...requirements,
  workspaceDir: root,
  candidatePath,
  finalPath,
  pythonExecutable: "/usr/bin/python3",
  integrityValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", "12192000,6858000",
    "--validate-heading-fit",
  ],
  fontPolicy: {
    basis: "design",
    families: [FONT, "Source Han Sans JP", "源ノ角ゴシック JP", "Calibri"],
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "cause-solution.validation.json"),
});
console.log(JSON.stringify({ sourcePath, candidatePath, finalPath, result }, null, 2));
