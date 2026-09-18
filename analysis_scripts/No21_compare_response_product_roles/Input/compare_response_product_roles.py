"""3社の栄養バランス対応商品に占める「食事補完型」の割合を比較する。

主分析
------
Zaim上で商品を確認できた「対応」商品だけを対象にする。
消費者分析（No20）との対象商品の整合性を優先した結果である。

補足分析
--------
Step3で「対応」と判定した全商品を対象にし、商品設計全体の傾向を確認する。

入力
----
Googleスプレッドシート「栄養バランス対応商品_一食完結型分類」の
次の2シートを、CSVとしてInputDataへ保存する。

1. 01_主分析_Zaim確認済み.csv
2. 02_補足分析_全対応商品.csv

各CSVは、シート全体をそのままダウンロードした形式でよい。

出力
----
主分析・補足分析のそれぞれについて、会社別集計CSVと、
食事補完型商品の割合を示す3社比較FigureをOutputへ保存する。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
INPUT_DATA_DIR = PROJECT_DIR / "InputData"
OUTPUT_DIR = PROJECT_DIR / "Output"

INPUT_FILES = {
    "主分析_Zaim確認済み": INPUT_DATA_DIR / "01_主分析_Zaim確認済み.csv",
    "補足分析_全対応商品": INPUT_DATA_DIR / "02_補足分析_全対応商品.csv",
}

COMPANY_COLUMN = "コンビニ"
CLASS_COLUMN = "最終分類"
COMPLETE_ROLE = "一食完結型"
SUPPLEMENT_ROLE = "食事補完型"
COMPANY_ORDER = ["セブンイレブン", "ローソン", "ファミリーマート"]
COMPANY_LABELS_EN = ["Seven-Eleven", "Lawson", "FamilyMart"]

# セブンイレブンをワインレッド、比較対象2社をグレーで示す。
# 濃色は食事補完型、淡色は一食完結型を表す。
SUPPLEMENT_COLORS = ["#762A3A", "#626A73", "#626A73"]
COMPLETE_COLORS = ["#D8AFB7", "#D3D6DA", "#D3D6DA"]

# 日本語フォントがない環境でも文字化けしないよう、Figure内は英語表記に統一する。
plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False


def read_sheet_export(path: Path) -> pd.DataFrame:
    """Google Sheetsのシート全体CSVから、明細表のヘッダー位置を自動検出する。"""
    if not path.exists():
        raise FileNotFoundError(
            f"入力CSVが見つかりません: {path}\n"
            "Googleスプレッドシートの該当シートをCSVでダウンロードし、"
            "指定のファイル名でInputDataへ保存してください。"
        )

    raw = pd.read_csv(path, header=None, encoding="utf-8-sig", dtype="string")
    header_rows = raw.index[
        raw.iloc[:, 0].fillna("").eq(COMPANY_COLUMN)
        & raw.iloc[:, 1].fillna("").eq("商品名")
    ].tolist()
    if not header_rows:
        raise ValueError(f"{path.name} に明細表のヘッダー行が見つかりません。")

    data = pd.read_csv(
        path,
        skiprows=header_rows[0],
        encoding="utf-8-sig",
        dtype="string",
    )
    required = {COMPANY_COLUMN, CLASS_COLUMN}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"{path.name} に必要な列がありません: {missing}")

    data = data.copy()
    data[COMPANY_COLUMN] = data[COMPANY_COLUMN].str.strip()
    data[CLASS_COLUMN] = data[CLASS_COLUMN].str.strip()
    data = data[
        data[COMPANY_COLUMN].isin(COMPANY_ORDER)
        & data[CLASS_COLUMN].isin([COMPLETE_ROLE, SUPPLEMENT_ROLE])
    ]
    if data.empty:
        raise ValueError(f"{path.name} に分析対象となる商品行がありません。")
    return data


def summarize(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for company in COMPANY_ORDER:
        company_data = data[data[COMPANY_COLUMN].eq(company)]
        complete_count = int(company_data[CLASS_COLUMN].eq(COMPLETE_ROLE).sum())
        supplement_count = int(company_data[CLASS_COLUMN].eq(SUPPLEMENT_ROLE).sum())
        total_count = complete_count + supplement_count
        share = supplement_count / total_count * 100 if total_count else float("nan")
        rows.append(
            {
                "コンビニ": company,
                "一食完結型商品数": complete_count,
                "食事補完型商品数": supplement_count,
                "対象商品数": total_count,
                "食事補完型割合（%）": share,
            }
        )
    return pd.DataFrame(rows)


def draw_figure(summary: pd.DataFrame, title: str, output_path: Path) -> None:
    supplement_values = summary["食事補完型割合（%）"].fillna(0).to_numpy()
    complete_values = 100.0 - supplement_values

    # 会社間の比較を一目で追えるよう、通常の0, 1, 2より中心間隔を狭くする。
    bar_positions = np.array([0.0, 0.72, 1.44])
    fig, ax = plt.subplots(figsize=(8.2, 6.2), dpi=200)
    supplement_bars = ax.bar(
        bar_positions,
        supplement_values,
        width=0.50,
        color=SUPPLEMENT_COLORS,
        edgecolor=SUPPLEMENT_COLORS,
        linewidth=1.2,
        zorder=3,
    )
    ax.bar(
        bar_positions,
        complete_values,
        width=0.50,
        bottom=supplement_values,
        color=COMPLETE_COLORS,
        edgecolor=SUPPLEMENT_COLORS,
        linewidth=1.2,
        zorder=3,
    )
    ax.set_title(
        f"Meal-role composition of response products\n{title}",
        fontsize=17,
        fontweight="bold",
        pad=18,
    )
    ax.set_ylabel(
        "Share of all response products (%)",
        fontsize=15,
        fontweight="bold",
        labelpad=10,
    )
    ax.set_xticks(bar_positions, COMPANY_LABELS_EN, fontsize=13)
    ax.tick_params(axis="x", labelsize=13, width=1.4, pad=8)
    ax.tick_params(axis="y", labelsize=13, width=1.4)
    ax.set_ylim(0, 100)
    ax.set_yticks(np.arange(0, 101, 20))
    ax.set_xlim(-0.48, 1.92)
    ax.grid(axis="y", linewidth=0.8, color="#D0D0D0", alpha=0.75)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(1.6)
    ax.spines["bottom"].set_linewidth(1.6)

    # 比較対象である食事補完型の割合だけを、濃色バー内へ表示する。
    for bar, value in zip(supplement_bars, supplement_values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value / 2,
            f"{value:.1f}%",
            ha="center",
            va="center",
            fontsize=16,
            fontweight="bold",
            color="white",
            zorder=4,
        )

    # 色相は会社、濃淡は食事上の役割を示す。凡例では濃淡の意味を示す。
    legend_handles = [
        Patch(
            facecolor=SUPPLEMENT_COLORS[0],
            edgecolor=SUPPLEMENT_COLORS[0],
            label="Meal supplement",
        ),
        Patch(
            facecolor=COMPLETE_COLORS[0],
            edgecolor=SUPPLEMENT_COLORS[0],
            label="Complete meal",
        ),
    ]
    ax.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.01),
        ncol=2,
        frameon=False,
        fontsize=12,
        handlelength=1.4,
        columnspacing=1.6,
    )
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # 反転前のFigureが結果フォルダに残り、誤読されることを防ぐ。
    for legacy_filename in (
        "02_主分析_一食完結型割合.png",
        "04_補足分析_一食完結型割合.png",
    ):
        legacy_path = OUTPUT_DIR / legacy_filename
        if legacy_path.exists():
            legacy_path.unlink()

    summaries: dict[str, pd.DataFrame] = {}
    for analysis_name, input_path in INPUT_FILES.items():
        data = read_sheet_export(input_path)
        summaries[analysis_name] = summarize(data)

    output_specs = [
        ("主分析_Zaim確認済み", "01_主分析_会社別集計.csv", "02_主分析_食事補完型割合.png", "Primary analysis: Zaim-matched products"),
        ("補足分析_全対応商品", "03_補足分析_会社別集計.csv", "04_補足分析_食事補完型割合.png", "Supplementary analysis: All eligible products"),
    ]
    for analysis_name, csv_name, figure_name, title in output_specs:
        summary = summaries[analysis_name]
        summary.to_csv(OUTPUT_DIR / csv_name, index=False, encoding="utf-8-sig", float_format="%.1f")
        draw_figure(summary, title, OUTPUT_DIR / figure_name)
        print(f"\n{analysis_name}")
        print(summary.to_string(index=False, float_format=lambda x: f"{x:.1f}"))

    print(f"\n保存先: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
