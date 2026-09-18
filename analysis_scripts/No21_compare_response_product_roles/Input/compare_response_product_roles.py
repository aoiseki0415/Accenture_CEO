"""3社の栄養バランス対応商品に占める「一食完結型」の割合を比較する。

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
一食完結型商品の割合を示す3社比較FigureをOutputへ保存する。
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager


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

JAPANESE_FONT_CANDIDATES = (
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "IPAexGothic",
    "IPAGothic",
    "Yu Gothic",
    "Hiragino Sans",
)


def set_japanese_font() -> str:
    """利用可能な日本語フォントを選び、文字化けを避ける。"""
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in JAPANESE_FONT_CANDIDATES:
        if candidate in installed:
            plt.rcParams["font.family"] = candidate
            plt.rcParams["axes.unicode_minus"] = False
            return candidate
    plt.rcParams["axes.unicode_minus"] = False
    print("警告: 日本語フォントが見つかりません。環境側で日本語フォントを追加してください。")
    return ""


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
        share = complete_count / total_count * 100 if total_count else float("nan")
        rows.append(
            {
                "コンビニ": company,
                "一食完結型商品数": complete_count,
                "食事補完型商品数": supplement_count,
                "対象商品数": total_count,
                "一食完結型割合（%）": share,
            }
        )
    return pd.DataFrame(rows)


def draw_figure(summary: pd.DataFrame, title: str, output_path: Path, y_max: float) -> None:
    values = summary["一食完結型割合（%）"].fillna(0).to_numpy()
    numerators = summary["一食完結型商品数"].to_numpy()
    denominators = summary["対象商品数"].to_numpy()

    fig, ax = plt.subplots(figsize=(9, 6.2), dpi=200)
    bars = ax.bar(
        range(len(COMPANY_ORDER)),
        values,
        width=0.58,
        color=["#4F6D8A", "#7C8A96", "#9A8774"],
        edgecolor="#333333",
        linewidth=1.2,
    )
    ax.set_title(title, fontsize=18, fontweight="bold", pad=18)
    ax.set_ylabel("一食完結型商品の割合（%）", fontsize=15)
    ax.set_xticks(range(len(COMPANY_ORDER)), COMPANY_ORDER, fontsize=13)
    ax.tick_params(axis="y", labelsize=12)
    ax.set_ylim(0, y_max)
    ax.grid(axis="y", linestyle="--", linewidth=0.8, color="#B8B8B8", alpha=0.75)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(1.4)
    ax.spines["bottom"].set_linewidth(1.4)

    for bar, value, numerator, denominator in zip(bars, values, numerators, denominators):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + y_max * 0.025,
            f"{value:.1f}%\n({numerator}/{denominator}商品)",
            ha="center",
            va="bottom",
            fontsize=12,
            fontweight="bold",
        )
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    set_japanese_font()

    summaries: dict[str, pd.DataFrame] = {}
    for analysis_name, input_path in INPUT_FILES.items():
        data = read_sheet_export(input_path)
        summaries[analysis_name] = summarize(data)

    max_share = max(
        float(summary["一食完結型割合（%）"].max())
        for summary in summaries.values()
    )
    shared_y_max = min(100.0, max(20.0, math.ceil((max_share + 10.0) / 10.0) * 10.0))

    output_specs = [
        ("主分析_Zaim確認済み", "01_主分析_会社別集計.csv", "02_主分析_一食完結型割合.png", "主分析：Zaim確認済み対応商品"),
        ("補足分析_全対応商品", "03_補足分析_会社別集計.csv", "04_補足分析_一食完結型割合.png", "補足分析：対応商品すべて"),
    ]
    for analysis_name, csv_name, figure_name, title in output_specs:
        summary = summaries[analysis_name]
        summary.to_csv(OUTPUT_DIR / csv_name, index=False, encoding="utf-8-sig", float_format="%.1f")
        draw_figure(summary, title, OUTPUT_DIR / figure_name, shared_y_max)
        print(f"\n{analysis_name}")
        print(summary.to_string(index=False, float_format=lambda x: f"{x:.1f}"))

    print(f"\n保存先: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
