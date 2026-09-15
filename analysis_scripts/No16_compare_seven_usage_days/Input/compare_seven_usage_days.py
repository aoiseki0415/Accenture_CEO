"""若年層の購買経験群・購買未経験群でセブン利用日数を比較する。

目的
----
Step8で確認した購買者割合の低さを受け、男女20代・30代の若年層を
「対応」商品の購買経験の有無で分け、セブンイレブンの利用日数を比較する。

入力
----
1. このファイル内で用意する、セブンイレブン全体のDataFrame
   ``data1`` ～ ``data5``
2. No4の ``Output/栄養バランス`` にある商品別CSV
3. 同フォルダの ``product_file_mapping.csv``

出力
----
No16の ``Output`` に次のファイルを保存する。

* ``01_群別ユーザー数.csv``
* ``02_ユーザー別利用日数.csv``
* ``03_群別利用日数要約.csv``
* ``04_データ品質確認.csv``
* ``05_利用日数_箱ひげ図.png``（matplotlibがある場合）
* ``06_利用日数_分布.png``（matplotlibがある場合）

Zaimの1行は1商品の購買記録であるため、同じユーザー・同じ日付に
複数行があっても、利用日数は1日として数える。

実データや認証情報はこのファイルへ直接記入しないこと。
"""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# =====================================================================
# 【分析条件】
# =====================================================================

SOURCE_PROJECT_DIR_NAME = "No4_extract_confirmed_products_seven"
SOURCE_HEALTH_NEED_DIR_NAME = "栄養バランス"

ANALYSIS_START_DATE = pd.Timestamp("2024-01-01")
ANALYSIS_END_DATE = pd.Timestamp("2026-06-30")

PURCHASE_DATE_COLUMN = "date"
USER_ID_COLUMN = "user_id"
GENDER_COLUMN = "user_gender"
AGE_COLUMN = "user_age_att_layer"

VALID_GENDERS = ("男性", "女性")
YOUNG_AGES = ("20代", "30代")

EXPERIENCED_GROUP = "購買経験群"
UNEXPERIENCED_GROUP = "購買未経験群"
GROUP_ORDER = (EXPERIENCED_GROUP, UNEXPERIENCED_GROUP)

REQUIRED_COLUMNS = {
    PURCHASE_DATE_COLUMN,
    USER_ID_COLUMN,
    GENDER_COLUMN,
    AGE_COLUMN,
}


# =====================================================================
# 【ユーザー記入欄】S3読込テンプレートで data1～data5 を作成する
# =====================================================================
# この位置に、会社環境で用意されたセブンイレブンのS3読込コードを貼り付ける。
# 最終的に、各期間のDataFrameが次の5変数へ入っていればよい。
#
# data1 = ...
# data2 = ...
# data3 = ...
# data4 = ...
# data5 = ...
#
# 認証情報は、このファイルへ直接記入しないこと。
# =====================================================================


def require_columns(
    data: pd.DataFrame,
    required_columns: set[str],
    source_name: str,
) -> None:
    """必要な列が存在することを確認する。"""
    missing = sorted(required_columns - set(data.columns))
    if missing:
        raise ValueError(f"{source_name} に必要な列がありません: {missing}")


def normalize_user_ids(values: pd.Series) -> pd.Series:
    """欠損・空欄・不明を除外できる、比較用の文字列IDへ統一する。"""
    normalized = values.astype("string").str.strip()
    invalid = (
        values.isna()
        | normalized.isna()
        | normalized.eq("")
        | normalized.str.lower().isin({"nan", "none", "null"})
        | normalized.str.contains("不明", na=False)
    )
    # CSV読込時に整数IDが ``123.0`` となった場合だけ末尾を揃える。
    normalized = normalized.str.replace(r"\.0$", "", regex=True)
    return normalized.mask(invalid)


def normalize_text(values: pd.Series) -> pd.Series:
    """文字列列の前後空白を除き、欠損は空文字にする。"""
    return values.astype("string").fillna("").str.strip()


def prepare_young_records(
    data: pd.DataFrame,
    source_name: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """期間・性別・年代・ユーザーID・日付が完全な若年層行だけを残す。"""
    require_columns(data, REQUIRED_COLUMNS, source_name)

    selected = data.loc[:, list(REQUIRED_COLUMNS)].copy()
    total_rows = len(selected)

    selected["_purchase_datetime"] = pd.to_datetime(
        selected[PURCHASE_DATE_COLUMN], errors="coerce"
    )
    selected["_purchase_day"] = selected["_purchase_datetime"].dt.normalize()
    selected["_user_id"] = normalize_user_ids(selected[USER_ID_COLUMN])
    selected["_gender"] = normalize_text(selected[GENDER_COLUMN])
    selected["_age"] = normalize_text(selected[AGE_COLUMN])

    valid_date = selected["_purchase_day"].notna()
    in_period = valid_date & selected["_purchase_day"].between(
        ANALYSIS_START_DATE,
        ANALYSIS_END_DATE,
        inclusive="both",
    )
    valid_user = selected["_user_id"].notna()
    valid_gender = selected["_gender"].isin(VALID_GENDERS)
    valid_age = selected["_age"].isin(YOUNG_AGES)
    eligible = in_period & valid_user & valid_gender & valid_age

    quality = {
        "入力行数": total_rows,
        "日付欠損・変換不能行数": int((~valid_date).sum()),
        "期間外行数": int((valid_date & ~in_period).sum()),
        "ユーザーID欠損・不明行数": int((in_period & ~valid_user).sum()),
        "性別対象外・欠損・不明行数": int(
            (in_period & valid_user & ~valid_gender).sum()
        ),
        "年代対象外・欠損・不明行数": int(
            (in_period & valid_user & valid_gender & ~valid_age).sum()
        ),
        "分析対象行数": int(eligible.sum()),
    }

    prepared = selected.loc[
        eligible,
        ["_user_id", "_purchase_day"],
    ].copy()
    return prepared, quality


def combine_company_data(
    dataframes: list[pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """5期間分から条件が完全な若年層のユーザーID・利用日だけを結合する。"""
    prepared_tables: list[pd.DataFrame] = []
    quality_rows: list[dict[str, object]] = []

    for number, data in enumerate(dataframes, start=1):
        prepared, quality = prepare_young_records(data, f"data{number}")
        prepared_tables.append(prepared)
        quality_rows.extend(
            {
                "データ種別": "セブン全購買データ",
                "入力元": f"data{number}",
                "確認項目": item,
                "行数": count,
            }
            for item, count in quality.items()
        )
        print(
            f"data{number}: 入力={quality['入力行数']:,}行 / "
            f"分析対象={quality['分析対象行数']:,}行"
        )

    company_data = pd.concat(
        prepared_tables,
        ignore_index=True,
        sort=False,
        copy=False,
    )
    if company_data.empty:
        raise ValueError(
            "分析期間・性別・年代・ユーザーID・日付の条件を満たす"
            "セブン利用記録がありません。"
        )

    quality_table = pd.DataFrame(quality_rows)
    print(f"若年層の有効なセブン購買記録: {len(company_data):,}行")
    return company_data, quality_table


def read_product_mapping(mapping_path: Path) -> pd.DataFrame:
    """No4の商品番号・商品名・出力ファイル名を読み込む。"""
    if not mapping_path.exists():
        raise FileNotFoundError(f"商品対応表が見つかりません: {mapping_path}")

    mapping = pd.read_csv(
        mapping_path,
        dtype=str,
        encoding="utf-8-sig",
    ).fillna("")
    require_columns(
        mapping,
        {"商品番号", "商品名", "出力ファイル名"},
        str(mapping_path),
    )
    if mapping.empty:
        raise ValueError(f"商品対応表が空です: {mapping_path}")

    mapping["商品番号"] = mapping["商品番号"].str.strip().str.zfill(3)
    mapping["商品名"] = mapping["商品名"].str.strip()
    mapping["出力ファイル名"] = mapping["出力ファイル名"].str.strip()
    if mapping["出力ファイル名"].eq("").any():
        raise ValueError("出力ファイル名が空の商品があります。")
    return mapping


def collect_experienced_user_ids(
    product_source_dir: Path,
) -> tuple[set[str], pd.DataFrame]:
    """No4の商品別CSVから、対象商品を購買した若年ユーザーを集める。"""
    mapping = read_product_mapping(
        product_source_dir / "product_file_mapping.csv"
    )
    experienced_ids: set[str] = set()
    quality_rows: list[dict[str, object]] = []

    for _, row in mapping.iterrows():
        product_number = str(row["商品番号"])
        product_name = str(row["商品名"])
        product_path = product_source_dir / str(row["出力ファイル名"])
        if not product_path.exists():
            raise FileNotFoundError(
                f"商品{product_number}のCSVが見つかりません: {product_path}"
            )

        product_data = pd.read_csv(
            product_path,
            usecols=lambda column: column in REQUIRED_COLUMNS,
            low_memory=False,
            encoding="utf-8-sig",
        )
        prepared, quality = prepare_young_records(
            product_data,
            f"商品{product_number}",
        )
        product_ids = set(prepared["_user_id"].dropna().astype(str).unique())
        experienced_ids.update(product_ids)

        quality_rows.extend(
            {
                "データ種別": "対象商品データ",
                "入力元": f"商品{product_number}｜{product_name}",
                "確認項目": item,
                "行数": count,
            }
            for item, count in quality.items()
        )
        print(
            f"商品{product_number}: 有効記録={quality['分析対象行数']:,}行 / "
            f"若年購買者={len(product_ids):,}人"
        )

    return experienced_ids, pd.DataFrame(quality_rows)


def classify_users_and_count_days(
    company_data: pd.DataFrame,
    product_experienced_ids: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """若年ユーザーを二群に分け、同日重複を除いて利用日数を数える。"""
    all_young_ids = set(
        company_data["_user_id"].dropna().astype(str).unique()
    )
    experienced_ids = all_young_ids & product_experienced_ids
    unexperienced_ids = all_young_ids - experienced_ids
    product_ids_outside_population = product_experienced_ids - all_young_ids

    overlap = experienced_ids & unexperienced_ids
    if overlap:
        raise RuntimeError("購買経験群と購買未経験群に重複があります。")
    if len(experienced_ids) + len(unexperienced_ids) != len(all_young_ids):
        raise RuntimeError("二群の人数合計が若年層の全対象者数と一致しません。")
    if not experienced_ids:
        raise ValueError("購買経験群に該当するユーザーがいません。")
    if not unexperienced_ids:
        raise ValueError("購買未経験群に該当するユーザーがいません。")

    user_day = (
        company_data.groupby("_user_id", sort=False)
        .agg(
            利用日数=("_purchase_day", "nunique"),
            購買記録行数=("_purchase_day", "size"),
            最初の利用日=("_purchase_day", "min"),
            最後の利用日=("_purchase_day", "max"),
        )
        .reset_index()
        .rename(columns={"_user_id": "user_id"})
    )
    user_day["群"] = np.where(
        user_day["user_id"].isin(experienced_ids),
        EXPERIENCED_GROUP,
        UNEXPERIENCED_GROUP,
    )
    user_day["最初の利用日"] = user_day["最初の利用日"].dt.strftime("%Y-%m-%d")
    user_day["最後の利用日"] = user_day["最後の利用日"].dt.strftime("%Y-%m-%d")
    user_day = user_day.loc[
        :,
        [
            "user_id",
            "群",
            "利用日数",
            "購買記録行数",
            "最初の利用日",
            "最後の利用日",
        ],
    ].sort_values(["群", "利用日数", "user_id"], ascending=[True, False, True])

    total_users = len(all_young_ids)
    group_counts = pd.DataFrame(
        [
            {
                "群": EXPERIENCED_GROUP,
                "ユーザー数": len(experienced_ids),
                "構成割合（%）": len(experienced_ids) / total_users * 100,
            },
            {
                "群": UNEXPERIENCED_GROUP,
                "ユーザー数": len(unexperienced_ids),
                "構成割合（%）": len(unexperienced_ids) / total_users * 100,
            },
            {
                "群": "全対象者",
                "ユーザー数": total_users,
                "構成割合（%）": 100.0,
            },
        ]
    )

    checks = {
        "若年層の全対象者数": total_users,
        "購買経験群ユーザー数": len(experienced_ids),
        "購買未経験群ユーザー数": len(unexperienced_ids),
        "対象商品CSVでは有効だが全対象者集合にないユーザー数": len(
            product_ids_outside_population
        ),
    }
    return user_day, group_counts, checks


def summarize_usage_days(user_day: pd.DataFrame) -> pd.DataFrame:
    """二群の利用日数を記述統計で要約する。"""
    rows: list[dict[str, object]] = []
    for group_name in GROUP_ORDER:
        values = user_day.loc[user_day["群"].eq(group_name), "利用日数"].astype(float)
        if values.empty:
            raise ValueError(f"{group_name}の利用日数がありません。")
        rows.append(
            {
                "群": group_name,
                "ユーザー数": len(values),
                "利用日数_平均": values.mean(),
                "利用日数_標準偏差": values.std(ddof=1),
                "利用日数_中央値": values.median(),
                "利用日数_第1四分位": values.quantile(0.25),
                "利用日数_第3四分位": values.quantile(0.75),
                "利用日数_最小": values.min(),
                "利用日数_最大": values.max(),
            }
        )
    return pd.DataFrame(rows)


def configure_japanese_font() -> None:
    """利用できる日本語フォントを優先順で設定する。"""
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [
        "Noto Sans CJK JP",
        "IPAexGothic",
        "Yu Gothic",
        "Hiragino Sans",
        "DejaVu Sans",
    ]


def save_boxplot(user_day: pd.DataFrame, output_path: Path) -> bool:
    """二群の利用日数を箱ひげ図で保存する。"""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlibがないためグラフ出力をスキップします。")
        return False

    configure_japanese_font()
    values = [
        user_day.loc[user_day["群"].eq(group), "利用日数"].astype(float).to_numpy()
        for group in GROUP_ORDER
    ]
    fig, ax = plt.subplots(figsize=(8.0, 5.8))
    boxplot = ax.boxplot(
        values,
        labels=GROUP_ORDER,
        patch_artist=True,
        showfliers=False,
        widths=0.48,
        medianprops={"color": "#111111", "linewidth": 2.0},
        whiskerprops={"color": "#555555", "linewidth": 1.4},
        capprops={"color": "#555555", "linewidth": 1.4},
        boxprops={"color": "#555555", "linewidth": 1.4},
    )
    for patch, color in zip(boxplot["boxes"], ("#4B4B4B", "#8A8A8A")):
        patch.set_facecolor(color)

    ax.set_ylabel("利用日数（日）", fontsize=16, fontweight="bold")
    ax.tick_params(axis="x", labelsize=14, width=1.4)
    ax.tick_params(axis="y", labelsize=13, width=1.4)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_linewidth(1.4)
    ax.spines["bottom"].set_linewidth(1.4)
    ax.grid(axis="y", color="#D0D0D0", linewidth=0.8, alpha=0.75)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return True


def save_distribution_chart(user_day: pd.DataFrame, output_path: Path) -> bool:
    """人数差の影響を避け、利用日数の割合分布を二群で保存する。"""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    configure_japanese_font()
    fig, ax = plt.subplots(figsize=(9.0, 5.8))
    colors = ("#3F3F3F", "#8A8A8A")
    for group, color in zip(GROUP_ORDER, colors):
        values = user_day.loc[user_day["群"].eq(group), "利用日数"].astype(float)
        sorted_values = np.sort(values.to_numpy())
        cumulative = np.arange(1, len(sorted_values) + 1) / len(sorted_values) * 100
        ax.step(
            sorted_values,
            cumulative,
            where="post",
            linewidth=2.2,
            color=color,
            label=group,
        )

    ax.set_xlabel("利用日数（日）", fontsize=16, fontweight="bold")
    ax.set_ylabel("累積ユーザー割合（%）", fontsize=16, fontweight="bold")
    ax.tick_params(axis="both", labelsize=13, width=1.4)
    ax.legend(frameon=False, fontsize=13)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_linewidth(1.4)
    ax.spines["bottom"].set_linewidth(1.4)
    ax.grid(color="#D0D0D0", linewidth=0.8, alpha=0.75)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return True


def save_outputs(
    user_day: pd.DataFrame,
    group_counts: pd.DataFrame,
    usage_summary: pd.DataFrame,
    quality_table: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    """表とグラフをNo16のOutputへ保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [
        output_dir / "01_群別ユーザー数.csv",
        output_dir / "02_ユーザー別利用日数.csv",
        output_dir / "03_群別利用日数要約.csv",
        output_dir / "04_データ品質確認.csv",
    ]

    group_counts.to_csv(
        output_paths[0], index=False, encoding="utf-8-sig", float_format="%.6f"
    )
    user_day.to_csv(output_paths[1], index=False, encoding="utf-8-sig")
    usage_summary.to_csv(
        output_paths[2], index=False, encoding="utf-8-sig", float_format="%.6f"
    )
    quality_table.to_csv(output_paths[3], index=False, encoding="utf-8-sig")

    boxplot_path = output_dir / "05_利用日数_箱ひげ図.png"
    if save_boxplot(user_day, boxplot_path):
        output_paths.append(boxplot_path)

    distribution_path = output_dir / "06_利用日数_分布.png"
    if save_distribution_chart(user_day, distribution_path):
        output_paths.append(distribution_path)
    return output_paths


def run(
    dataframes: list[pd.DataFrame],
    product_source_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> list[Path]:
    """若年層の二群を作り、利用日数を比較して保存する。"""
    project_dir = Path(__file__).resolve().parents[1]
    workspace_dir = project_dir.parent

    if product_source_dir is None:
        product_source_dir = (
            workspace_dir
            / SOURCE_PROJECT_DIR_NAME
            / "Output"
            / SOURCE_HEALTH_NEED_DIR_NAME
        )
    if output_dir is None:
        output_dir = project_dir / "Output"
    if not product_source_dir.exists():
        raise FileNotFoundError(
            "No4の栄養バランス商品フォルダが見つかりません。"
            f"\n確認対象: {product_source_dir}"
        )

    company_data, company_quality = combine_company_data(dataframes)
    dataframes.clear()
    gc.collect()
    print("元の5期間分DataFrameをメモリから解放しました。")

    product_experienced_ids, product_quality = collect_experienced_user_ids(
        product_source_dir
    )
    user_day, group_counts, checks = classify_users_and_count_days(
        company_data,
        product_experienced_ids,
    )
    usage_summary = summarize_usage_days(user_day)

    check_rows = pd.DataFrame(
        [
            {
                "データ種別": "集合整合性確認",
                "入力元": "全体",
                "確認項目": item,
                "行数": count,
            }
            for item, count in checks.items()
        ]
    )
    quality_table = pd.concat(
        [company_quality, product_quality, check_rows],
        ignore_index=True,
        sort=False,
    )

    output_paths = save_outputs(
        user_day=user_day,
        group_counts=group_counts,
        usage_summary=usage_summary,
        quality_table=quality_table,
        output_dir=output_dir,
    )

    print("\n若年層の購買経験群・購買未経験群の利用日数分析が完了しました。")
    for _, row in group_counts.iterrows():
        print(
            f"{row['群']}: {int(row['ユーザー数']):,}人 "
            f"({float(row['構成割合（%）']):.2f}%)"
        )
    for _, row in usage_summary.iterrows():
        print(
            f"{row['群']}: 平均={float(row['利用日数_平均']):.3f}日 / "
            f"中央値={float(row['利用日数_中央値']):.3f}日"
        )
    print(f"保存先: {output_dir}")
    return output_paths


def main() -> None:
    data_names = ["data1", "data2", "data3", "data4", "data5"]
    missing = [name for name in data_names if name not in globals()]
    if missing:
        raise RuntimeError(
            "ユーザー記入欄で次のDataFrameを作成してください: "
            + ", ".join(missing)
        )

    dataframes = [globals().pop(name) for name in data_names]
    run(dataframes)


if __name__ == "__main__":
    main()
