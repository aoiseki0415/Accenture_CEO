"""若年群と比較群で、食事補完型割合の群間差を比較する。

比較する値
----------
* 若年群（20・30代）: 5.4ポイント
* 比較群（40・50代）: 3.7ポイント

ここでの群間差は、次の計算による。

    購買未経験群の食事補完型購買記録割合
    - 購買経験群の食事補完型購買記録割合

出力
----
No24の ``Output`` に次のファイルを保存する。

* ``01_年齢群別_群間差.csv``
* ``02_年齢群別_群間差.png``

値を更新する場合は、``AGE_GROUP_GAPS`` の数値だけを変更する。
"""

from __future__ import annotations

import csv
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_DIR / "Output"

# 単位はパーセントポイント。
AGE_GROUP_GAPS = (
    ("若年群（20・30代）", "Young group (20s-30s)", 5.4),
    ("比較群（40・50代）", "Comparison group (40s-50s)", 3.7),
)

# 若年群を主対象として濃色、比較群を同系統の淡色で示す。
BAR_COLORS = ("#8064A2", "#C6B7D8")
Y_AXIS_MAX = 7.0

JAPANESE_FONT_CANDIDATES = (
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "IPAexGothic",
    "IPAGothic",
    "TakaoGothic",
    "VL Gothic",
    "Yu Gothic",
    "Hiragino Sans",
)


def configure_plot_font() -> bool:
    """日本語フォントを設定し、利用できなければ英語表示へ切り替える。"""
    import matplotlib as mpl
    from matplotlib import font_manager

    for font_name in JAPANESE_FONT_CANDIDATES:
        try:
            font_manager.findfont(
                font_manager.FontProperties(family=font_name),
                fallback_to_default=False,
            )
        except ValueError:
            continue
        mpl.rcParams["font.family"] = font_name
        mpl.rcParams["axes.unicode_minus"] = False
        print(f"グラフ用日本語フォント: {font_name}")
        return True

    mpl.rcParams["font.family"] = "DejaVu Sans"
    mpl.rcParams["axes.unicode_minus"] = False
    print("日本語フォントが見つからないため、英語ラベルで保存します。")
    return False


def save_result_csv(output_path: Path) -> None:
    """Figureに使用した値をCSVでも保存する。"""
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "年齢群",
                "購買未経験群－購買経験群_食事補完型購買記録割合差（ポイント）",
            ]
        )
        for japanese_label, _, value in AGE_GROUP_GAPS:
            writer.writerow([japanese_label, f"{value:.1f}"])


def save_figure(output_path: Path) -> None:
    """2つの年齢群の群間差を縦棒グラフとして保存する。"""
    import matplotlib.pyplot as plt

    use_japanese = configure_plot_font()
    labels = [
        japanese_label if use_japanese else english_label
        for japanese_label, english_label, _ in AGE_GROUP_GAPS
    ]
    values = [value for _, _, value in AGE_GROUP_GAPS]

    if use_japanese:
        title = "食事補完型購買記録割合の群間差"
        y_label = "群間差（ポイント）"
        definition = "群間差 ＝ 購買未経験群 − 購買経験群"
    else:
        title = "Difference in meal-complementing purchase share"
        y_label = "Difference (percentage points)"
        definition = "Difference = no-purchase group - purchase-experienced group"

    positions = (-0.27, 0.27)
    fig, ax = plt.subplots(figsize=(7.2, 5.8))
    bars = ax.bar(
        positions,
        values,
        width=0.40,
        color=BAR_COLORS,
        edgecolor="#333333",
        linewidth=1.2,
    )

    ax.set_xticks(positions)
    ax.set_xticklabels(labels, fontsize=12)
    ax.set_xlim(-0.85, 0.85)
    ax.set_ylim(0, Y_AXIS_MAX)
    ax.set_title(title, fontsize=17, fontweight="bold", pad=15)
    ax.set_ylabel(y_label, fontsize=14, fontweight="bold")
    ax.tick_params(axis="y", labelsize=12, width=1.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_linewidth(1.4)
    ax.spines["bottom"].set_linewidth(1.4)
    ax.grid(
        axis="y",
        linestyle="--",
        color="#B8B8B8",
        linewidth=0.8,
        alpha=0.75,
    )
    ax.set_axisbelow(True)
    ax.bar_label(
        bars,
        labels=[f"{value:.1f} pt" for value in values],
        padding=5,
        fontsize=13,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.015,
        definition,
        ha="center",
        va="bottom",
        fontsize=10,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "01_年齢群別_群間差.csv"
    figure_path = OUTPUT_DIR / "02_年齢群別_群間差.png"

    save_result_csv(csv_path)
    save_figure(figure_path)

    print("\nNo24の年齢群別比較Figureを保存しました。")
    for japanese_label, _, value in AGE_GROUP_GAPS:
        print(f"{japanese_label}: {value:.1f}ポイント")
    print(f"保存先: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
