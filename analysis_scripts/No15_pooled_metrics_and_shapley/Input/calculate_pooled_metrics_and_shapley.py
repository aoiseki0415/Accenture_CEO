"""若年群と比較群のプール集計とシャープレイ分解を再現する。

入力
----
No14の ``Output/02_商品内の属性間比較`` に保存された商品別CSV。
各CSVには、商品×属性ごとの購買記録数・購入者数・対象者数が必要である。

分析条件
--------
* 若年群: 男女20代・30代
* 比較群: 男女40代・50代
* 商品001～011を使用し、商品012は算出不能のため除外する
* 商品009・男性40代は、事前に確認した外れ値のため除外する
* 全体、男性、女性の3通りで集計する

出力
----
No15の ``Output`` に次のCSVを保存する。

* ``01_プール集計結果.csv``
* ``02_シャープレイ分解結果.csv``
* ``03_使用データ確認.csv``
* ``04_除外データ確認.csv``
* ``05_二群比較グラフ/``：3指標 × 全体・男性・女性の9枚
* ``06_シャープレイ分解グラフ/``：全体・男性・女性の3枚

matplotlibが利用できる場合は、全体・男性・女性を別々のFigureとして、
二群比較とシャープレイ分解の図も保存する。
実データや認証情報はこのファイルへ直接記入しないこと。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# =====================================================================
# 【分析条件】
# =====================================================================

SOURCE_PROJECT_DIR_NAME = "No14_cause_analysis_seven_nutrition_balance"
SOURCE_SUBDIR = Path("Output") / "02_商品内の属性間比較"

INDEX_SCALE = 1000.0
INCLUDED_PRODUCT_NUMBERS = tuple(f"{number:03d}" for number in range(1, 12))
EXCLUDED_PRODUCT_NUMBERS = ("012",)

YOUNG_AGES = ("20代", "30代")
CONTROL_AGES = ("40代", "50代")
VALID_GENDERS = ("男性", "女性")
YOUNG_GROUP_NAME = "若年群（20・30代）"
COMPARISON_GROUP_NAME = "比較群（40・50代）"
COMPARISON_GROUPS = (YOUNG_GROUP_NAME, COMPARISON_GROUP_NAME)

# (商品番号, 性別, 年代)
OUTLIER_KEYS = {
    ("009", "男性", "40代"),
}

REQUIRED_COLUMNS = {
    "商品番号",
    "商品名",
    "性別",
    "年代",
    "購買記録数",
    "購入者数",
    "対象者数",
}

NUMERIC_COLUMNS = ("購買記録数", "購入者数", "対象者数")

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


def require_columns(
    data: pd.DataFrame,
    required_columns: set[str],
    source_name: str,
) -> None:
    """必要な列が存在することを確認する。"""
    missing = sorted(required_columns - set(data.columns))
    if missing:
        raise ValueError(f"{source_name} に必要な列がありません: {missing}")


def normalize_product_number(value: object) -> str:
    """商品番号を3桁の文字列へ統一する。"""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(3)


def read_product_tables(source_dir: Path) -> pd.DataFrame:
    """No14の商品別CSVを読み込み、1つの縦長表へまとめる。"""
    if not source_dir.exists():
        raise FileNotFoundError(f"No14の商品別CSV保存先がありません: {source_dir}")

    paths = sorted(source_dir.glob("product_[0-9][0-9][0-9].csv"))
    if not paths:
        raise FileNotFoundError(f"商品別CSVがありません: {source_dir}")

    tables: list[pd.DataFrame] = []
    for path in paths:
        table = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        require_columns(table, REQUIRED_COLUMNS, str(path))
        table = table.copy()
        table["入力ファイル"] = path.name
        tables.append(table)

    data = pd.concat(tables, ignore_index=True, sort=False)
    data["商品番号"] = data["商品番号"].map(normalize_product_number)
    data["性別"] = data["性別"].fillna("").astype(str).str.strip()
    data["年代"] = data["年代"].fillna("").astype(str).str.strip()

    for column in NUMERIC_COLUMNS:
        original = data[column]
        data[column] = pd.to_numeric(original, errors="coerce")
        invalid = original.notna() & data[column].isna()
        if invalid.any():
            examples = original.loc[invalid].astype(str).unique()[:5].tolist()
            raise ValueError(
                f"{column} に数値化できない値があります: {examples}"
            )

    return data


def assign_comparison_group(data: pd.DataFrame) -> pd.Series:
    """年代から若年群・比較群を付与する。"""
    group = pd.Series(pd.NA, index=data.index, dtype="string")
    group.loc[data["年代"].isin(YOUNG_AGES)] = YOUNG_GROUP_NAME
    group.loc[data["年代"].isin(CONTROL_AGES)] = COMPARISON_GROUP_NAME
    return group


def prepare_analysis_data(
    raw_data: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """分析対象を確定し、除外理由を記録する。"""
    data = raw_data.copy()
    data["比較群"] = assign_comparison_group(data)
    data["除外理由"] = ""

    data.loc[
        ~data["商品番号"].isin(INCLUDED_PRODUCT_NUMBERS),
        "除外理由",
    ] = "分析対象商品外（商品012を含む）"
    data.loc[
        ~data["性別"].isin(VALID_GENDERS),
        "除外理由",
    ] = "分析対象外の性別"
    data.loc[
        data["比較群"].isna(),
        "除外理由",
    ] = "分析対象外の年代"

    outlier_mask = pd.Series(False, index=data.index)
    for product_number, gender, age in OUTLIER_KEYS:
        outlier_mask |= (
            data["商品番号"].eq(product_number)
            & data["性別"].eq(gender)
            & data["年代"].eq(age)
        )
    data.loc[outlier_mask, "除外理由"] = "事前に定義した外れ値"

    missing_numeric = data.loc[:, NUMERIC_COLUMNS].isna().any(axis=1)
    data.loc[
        missing_numeric & data["除外理由"].eq(""),
        "除外理由",
    ] = "集計値が算出不能"

    negative_numeric = data.loc[:, NUMERIC_COLUMNS].lt(0).any(axis=1)
    if negative_numeric.any():
        raise ValueError("購買記録数・購入者数・対象者数に負の値があります。")

    impossible_buyers = data["購入者数"].gt(data["購買記録数"])
    if impossible_buyers.any():
        raise ValueError("購入者数が購買記録数を上回る行があります。")

    impossible_targets = data["購入者数"].gt(data["対象者数"])
    if impossible_targets.any():
        raise ValueError("購入者数が対象者数を上回る行があります。")

    zero_target = data["対象者数"].eq(0)
    data.loc[
        zero_target & data["除外理由"].eq(""),
        "除外理由",
    ] = "対象者数が0"

    used = data.loc[data["除外理由"].eq("")].copy()
    excluded = data.loc[~data["除外理由"].eq("")].copy()

    present_products = set(used["商品番号"].unique())
    missing_products = sorted(set(INCLUDED_PRODUCT_NUMBERS) - present_products)
    if missing_products:
        raise ValueError(
            "使用予定の商品CSVまたは有効行が不足しています: "
            + ", ".join(missing_products)
        )

    return used, excluded


def calculate_pooled_metrics(data: pd.DataFrame) -> dict[str, float]:
    """R・B・Nを先に合計し、プール集計の3指標を計算する。"""
    purchase_records = float(data["購買記録数"].sum())
    buyers = float(data["購入者数"].sum())
    target_users = float(data["対象者数"].sum())

    if target_users <= 0:
        raise ValueError("対象者数の合計が0のため、プール集計できません。")
    if buyers <= 0:
        raise ValueError("購入者数の合計が0のため、購入頻度を算出できません。")

    purchaser_rate = buyers / target_users
    purchase_frequency = purchase_records / buyers
    purchase_index = purchase_records / target_users * INDEX_SCALE

    decomposed_index = purchaser_rate * purchase_frequency * INDEX_SCALE
    if not np.isclose(purchase_index, decomposed_index, rtol=0, atol=1e-12):
        raise RuntimeError("購買指数 = 購入者率 × 購入頻度 × 1000 が成立しません。")

    return {
        "購買記録数_R": purchase_records,
        "購入者数_B": buyers,
        "対象者数_N": target_users,
        "購入者率": purchaser_rate,
        "購入者率（%）": purchaser_rate * 100,
        "購入頻度（回/購入者）": purchase_frequency,
        "購買指数": purchase_index,
    }


def aggregate_all_scopes(data: pd.DataFrame) -> pd.DataFrame:
    """全体・男性・女性について、若年群と比較群を集計する。"""
    rows: list[dict[str, object]] = []
    scopes: tuple[tuple[str, Optional[str]], ...] = (
        ("全体", None),
        ("男性", "男性"),
        ("女性", "女性"),
    )

    for scope_name, gender in scopes:
        scope_data = data if gender is None else data.loc[data["性別"].eq(gender)]
        for group_name in COMPARISON_GROUPS:
            group_data = scope_data.loc[scope_data["比較群"].eq(group_name)]
            if group_data.empty:
                raise ValueError(f"{scope_name}・{group_name}の対象行がありません。")
            metrics = calculate_pooled_metrics(group_data)
            rows.append(
                {
                    "集計範囲": scope_name,
                    "比較群": group_name,
                    "使用行数": len(group_data),
                    **metrics,
                }
            )

    return pd.DataFrame(rows)


def shapley_decomposition(
    purchaser_rate_young: float,
    frequency_young: float,
    purchaser_rate_control: float,
    frequency_control: float,
) -> dict[str, float]:
    """指数差を購入者率寄与と購入頻度寄与へ公平に分解する。"""
    index_young = (
        purchaser_rate_young * frequency_young * INDEX_SCALE
    )
    index_control = (
        purchaser_rate_control * frequency_control * INDEX_SCALE
    )
    index_gap = index_control - index_young

    rate_contribution = (
        INDEX_SCALE
        * (purchaser_rate_control - purchaser_rate_young)
        * (frequency_control + frequency_young)
        / 2
    )
    frequency_contribution = (
        INDEX_SCALE
        * (frequency_control - frequency_young)
        * (purchaser_rate_control + purchaser_rate_young)
        / 2
    )

    contribution_sum = rate_contribution + frequency_contribution
    residual = index_gap - contribution_sum
    if not np.isclose(index_gap, contribution_sum, rtol=0, atol=1e-12):
        raise RuntimeError("シャープレイ寄与の合計が購買指数差と一致しません。")

    if np.isclose(index_gap, 0.0, rtol=0, atol=1e-15):
        rate_share = np.nan
        frequency_share = np.nan
    else:
        rate_share = rate_contribution / index_gap * 100
        frequency_share = frequency_contribution / index_gap * 100

    return {
        "若年群_購買指数": index_young,
        "比較群_購買指数": index_control,
        "購買指数差（比較群－若年群）": index_gap,
        "購入者率の寄与": rate_contribution,
        "購入頻度の寄与": frequency_contribution,
        "購入者率の寄与割合（%）": rate_share,
        "購入頻度の寄与割合（%）": frequency_share,
        "検算残差": residual,
    }


def calculate_all_shapley(pooled: pd.DataFrame) -> pd.DataFrame:
    """全体・男性・女性の3範囲でシャープレイ分解を行う。"""
    rows: list[dict[str, object]] = []
    for scope_name in ("全体", "男性", "女性"):
        scope = pooled.loc[pooled["集計範囲"].eq(scope_name)].set_index("比較群")
        young = scope.loc[YOUNG_GROUP_NAME]
        control = scope.loc[COMPARISON_GROUP_NAME]
        result = shapley_decomposition(
            purchaser_rate_young=float(young["購入者率"]),
            frequency_young=float(young["購入頻度（回/購入者）"]),
            purchaser_rate_control=float(control["購入者率"]),
            frequency_control=float(control["購入頻度（回/購入者）"]),
        )
        rows.append({"集計範囲": scope_name, **result})
    return pd.DataFrame(rows)


def configure_plot_font() -> bool:
    """利用可能な日本語フォントを検出し、なければ英語表示へ切り替える。"""
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

    # 日本語を表示できない環境でも文字化けさせず、英語ラベルで保存する。
    mpl.rcParams["font.family"] = "DejaVu Sans"
    mpl.rcParams["axes.unicode_minus"] = False
    print(
        "日本語フォントが見つからないため、グラフ内のラベルを英語で保存します。"
    )
    return False


def save_bar_chart(
    pooled: pd.DataFrame,
    scope_name: str,
    metric: str,
    ylabel_japanese: str,
    ylabel_english: str,
    y_upper: float,
    output_path: Path,
) -> None:
    """指定した1集計範囲について、若年群と比較群を描く。"""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlibがないためグラフ出力をスキップします。")
        return

    # 3つの二群比較グラフで、文字・色・余白を完全に共通化する。
    use_japanese = configure_plot_font()

    groups = COMPARISON_GROUPS
    group_labels = {
        YOUNG_GROUP_NAME: (
            YOUNG_GROUP_NAME if use_japanese else "Young group (20s-30s)"
        ),
        COMPARISON_GROUP_NAME: (
            COMPARISON_GROUP_NAME
            if use_japanese
            else "Comparison group (40s-50s)"
        ),
    }
    colors = ("#484848", "#747474")
    scope_data = pooled.loc[pooled["集計範囲"].eq(scope_name)].set_index(
        "比較群"
    )
    missing_groups = [group for group in groups if group not in scope_data.index]
    if missing_groups:
        raise ValueError(
            f"{scope_name}のグラフに必要な群がありません: {missing_groups}"
        )

    values = [float(scope_data.loc[group, metric]) for group in groups]
    x = np.arange(len(groups))
    fig, ax = plt.subplots(figsize=(6.8, 5.8))
    bars = ax.bar(x, values, width=0.52, color=colors)
    ax.bar_label(
        bars,
        fmt="%.3f",
        padding=5,
        fontsize=15,
        fontweight="bold",
        color="#222222",
    )

    ax.set_xticks(
        x,
        [group_labels[group] for group in groups],
        fontsize=15,
        fontweight="bold",
    )
    ax.set_ylabel(
        ylabel_japanese if use_japanese else ylabel_english,
        fontsize=17,
        fontweight="bold",
        labelpad=12,
    )
    ax.tick_params(axis="y", labelsize=13, width=1.4, length=5)
    ax.tick_params(axis="x", width=1.4, length=5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_linewidth(1.4)
    ax.spines["bottom"].set_linewidth(1.4)
    ax.grid(axis="y", color="#CFCFCF", linewidth=0.8, alpha=0.75)
    ax.set_axisbelow(True)
    ax.set_ylim(0, y_upper)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def save_shapley_chart(
    shapley: pd.DataFrame,
    scope_name: str,
    y_limits: tuple[float, float],
    output_path: Path,
) -> None:
    """指定した1集計範囲の2つの寄与を積み上げ棒グラフへ保存する。"""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return

    use_japanese = configure_plot_font()

    scope = shapley.loc[shapley["集計範囲"].eq(scope_name)]
    if len(scope) != 1:
        raise ValueError(
            f"{scope_name}のシャープレイ分解結果が1行ではありません: {len(scope)}行"
        )
    rate = float(scope["購入者率の寄与"].iloc[0])
    frequency = float(scope["購入頻度の寄与"].iloc[0])

    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    rate_label = (
        "購買者割合の寄与" if use_japanese else "Purchaser-share contribution"
    )
    frequency_label = (
        "購買頻度の寄与" if use_japanese else "Purchase-frequency contribution"
    )
    scope_label_english = {
        "全体": "Overall",
        "男性": "Male",
        "女性": "Female",
    }
    x = np.array([0.0])
    ax.bar(x, [rate], width=0.48, color="#D55E00", label=rate_label)
    ax.bar(
        x,
        [frequency],
        width=0.48,
        bottom=[rate],
        color="#0072B2",
        label=frequency_label,
    )
    ax.set_xticks(
        x,
        [scope_name if use_japanese else scope_label_english[scope_name]],
        fontsize=14,
        fontweight="bold",
    )
    ax.set_ylabel(
        "購買指数差への寄与"
        if use_japanese
        else "Contribution to purchase-index gap"
    )
    ax.axhline(0, color="#333333", linewidth=1)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#D8D8D8", linewidth=0.7, alpha=0.7)
    ax.set_axisbelow(True)
    ax.set_ylim(*y_limits)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def run(
    source_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> list[Path]:
    """プール集計、シャープレイ分解、検算、保存を順に行う。"""
    project_dir = Path(__file__).resolve().parents[1]
    workspace_dir = project_dir.parent

    if source_dir is None:
        source_dir = workspace_dir / SOURCE_PROJECT_DIR_NAME / SOURCE_SUBDIR
    if output_dir is None:
        output_dir = project_dir / "Output"
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_data = read_product_tables(source_dir)
    used, excluded = prepare_analysis_data(raw_data)
    pooled = aggregate_all_scopes(used)
    shapley = calculate_all_shapley(pooled)

    output_paths = [
        output_dir / "01_プール集計結果.csv",
        output_dir / "02_シャープレイ分解結果.csv",
        output_dir / "03_使用データ確認.csv",
        output_dir / "04_除外データ確認.csv",
    ]
    pooled.to_csv(output_paths[0], index=False, encoding="utf-8-sig", float_format="%.12f")
    shapley.to_csv(output_paths[1], index=False, encoding="utf-8-sig", float_format="%.12f")
    used.to_csv(output_paths[2], index=False, encoding="utf-8-sig")
    excluded.to_csv(output_paths[3], index=False, encoding="utf-8-sig")

    chart_specs: tuple[tuple[str, str, str, str], ...] = (
        (
            "購買指数",
            "購買指数",
            "Purchase index",
            "購買指数",
        ),
        (
            "購入者率（%）",
            "購買者割合（%）",
            "Purchaser share (%)",
            "購買者割合",
        ),
        (
            "購入頻度（回/購入者）",
            "購買頻度（回 / 購入者）",
            "Purchase frequency (times/purchaser)",
            "購買頻度",
        ),
    )
    comparison_chart_dir = output_dir / "05_二群比較グラフ"
    comparison_chart_dir.mkdir(parents=True, exist_ok=True)
    for metric, ylabel_japanese, ylabel_english, metric_filename in chart_specs:
        metric_values = pooled[metric].astype(float)
        metric_max = float(metric_values.max())
        y_upper = metric_max * 1.22 if metric_max > 0 else 1.0
        for scope_name in ("全体", "男性", "女性"):
            chart_path = comparison_chart_dir / (
                f"{scope_name}_{metric_filename}_二群比較.png"
            )
            save_bar_chart(
                pooled,
                scope_name,
                metric,
                ylabel_japanese,
                ylabel_english,
                y_upper,
                chart_path,
            )
            if chart_path.exists():
                output_paths.append(chart_path)

    shapley_chart_dir = output_dir / "06_シャープレイ分解グラフ"
    shapley_chart_dir.mkdir(parents=True, exist_ok=True)
    rate_values = shapley["購入者率の寄与"].astype(float).to_numpy()
    frequency_values = shapley["購入頻度の寄与"].astype(float).to_numpy()
    total_values = rate_values + frequency_values
    shapley_min = float(min(0.0, rate_values.min(), frequency_values.min(), total_values.min()))
    shapley_max = float(max(0.0, rate_values.max(), frequency_values.max(), total_values.max()))
    shapley_span = shapley_max - shapley_min
    shapley_padding = shapley_span * 0.15 if shapley_span > 0 else 1.0
    shapley_limits = (
        shapley_min - (shapley_padding if shapley_min < 0 else 0.0),
        shapley_max + shapley_padding,
    )
    for scope_name in ("全体", "男性", "女性"):
        shapley_chart_path = shapley_chart_dir / (
            f"{scope_name}_シャープレイ分解.png"
        )
        save_shapley_chart(
            shapley,
            scope_name,
            shapley_limits,
            shapley_chart_path,
        )
        if shapley_chart_path.exists():
            output_paths.append(shapley_chart_path)

    # 分割前の単一Figureを残すと誤って参照しやすいため、再実行時にだけ除去する。
    for legacy_filename in (
        "05_購買指数_二群比較.png",
        "06_購入者率_二群比較.png",
        "07_購入頻度_二群比較.png",
        "08_シャープレイ分解.png",
    ):
        legacy_path = output_dir / legacy_filename
        if legacy_path.exists():
            legacy_path.unlink()

    print("\nプール集計とシャープレイ分解が完了しました。")
    print(f"使用行数: {len(used):,} / 除外行数: {len(excluded):,}")
    for _, row in shapley.iterrows():
        print(
            f"{row['集計範囲']}: 指数差={row['購買指数差（比較群－若年群）']:.6f}, "
            f"購買者割合寄与={row['購入者率の寄与割合（%）']:.2f}%, "
            f"購買頻度寄与={row['購入頻度の寄与割合（%）']:.2f}%"
        )
    return output_paths


def main() -> None:
    run()


if __name__ == "__main__":
    main()
