"""3社の対応商品群購買指数を共通閾値で「大・中・小」に分類する。

No10～12で作成した対応商品群購買指数を統合し、算出可能な全セルから
第33.3パーセンタイルと第66.7パーセンタイルを算出する。

分類ルール
----------
* 指数 < 下側閾値: 小
* 下側閾値 <= 指数 < 上側閾値: 中
* 上側閾値 <= 指数: 大
* 算出不能: 算出不能のまま保持

有効な指数0は閾値計算へ含め、「算出不能」は除外する。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


# =====================================================================
# 設定
# =====================================================================

COMPANY_INPUTS = {
    "セブン": {
        "project_dir": "No10_group_purchase_index_seven",
        "file_name": "セブン_対応商品群購買指数.csv",
        "category_output": "セブン_対応商品群購買指数_大中小.csv",
    },
    "ローソン": {
        "project_dir": "No11_group_purchase_index_lawson",
        "file_name": "ローソン_対応商品群購買指数.csv",
        "category_output": "ローソン_対応商品群購買指数_大中小.csv",
    },
    "ファミリーマート": {
        "project_dir": "No12_group_purchase_index_familymart",
        "file_name": "ファミリーマート_対応商品群購買指数.csv",
        "category_output": "ファミリーマート_対応商品群購買指数_大中小.csv",
    },
}

HEALTH_NEEDS = (
    "栄養バランス",
    "脂質",
    "エネルギー",
)

AGE_LABELS = (
    "20代",
    "30代",
    "40代",
    "50代",
    "60代",
    "70代",
)

ATTRIBUTE_ORDER = tuple(
    f"{gender}・{age}"
    for gender in ("男性", "女性")
    for age in AGE_LABELS
)

HEALTH_NEED_COLUMN = "健康ニーズ"
UNCOMPUTABLE_VALUE = "算出不能"

LOW_QUANTILE = 1 / 3
HIGH_QUANTILE = 2 / 3

COMBINED_OUTPUT_FILE_NAME = "3社統合_対応商品群購買指数.csv"
THRESHOLD_OUTPUT_FILE_NAME = "対応商品群購買指数_三段階閾値.csv"


def validate_and_parse_table(
    table: pd.DataFrame,
    company: str,
    source_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """入力形式を検証し、元表と数値変換表を返す。"""
    required_columns = {HEALTH_NEED_COLUMN, *ATTRIBUTE_ORDER}
    missing = sorted(required_columns - set(table.columns))
    if missing:
        raise ValueError(
            f"{company}の入力表に必要な列がありません: {missing}"
            f"\n入力: {source_path}"
        )

    if table[HEALTH_NEED_COLUMN].duplicated().any():
        duplicated = table.loc[
            table[HEALTH_NEED_COLUMN].duplicated(keep=False),
            HEALTH_NEED_COLUMN,
        ].tolist()
        raise ValueError(f"{company}で健康ニーズが重複しています: {duplicated}")

    actual_needs = table[HEALTH_NEED_COLUMN].tolist()
    if actual_needs != list(HEALTH_NEEDS):
        raise ValueError(
            f"{company}の健康ニーズまたは順序が想定と異なります。"
            f"\n想定: {list(HEALTH_NEEDS)}"
            f"\n実際: {actual_needs}"
        )

    original = table.loc[:, [HEALTH_NEED_COLUMN, *ATTRIBUTE_ORDER]].copy()
    numeric = pd.DataFrame(index=original.index)

    for attribute in ATTRIBUTE_ORDER:
        raw_values = original[attribute].fillna("").astype(str).str.strip()
        numeric_values = pd.to_numeric(raw_values, errors="coerce")

        allowed_uncomputable = raw_values.eq(UNCOMPUTABLE_VALUE)
        invalid = numeric_values.isna() & ~allowed_uncomputable
        if invalid.any():
            invalid_rows = (
                original.loc[invalid, HEALTH_NEED_COLUMN].astype(str).tolist()
            )
            raise ValueError(
                f"{company}・{attribute}に、数値でも算出不能でもない値があります。"
                f"\n健康ニーズ: {invalid_rows}"
            )

        if numeric_values.dropna().lt(0).any():
            raise ValueError(
                f"{company}・{attribute}に負の購買指数があります。"
            )
        numeric[attribute] = numeric_values

    numeric.insert(0, HEALTH_NEED_COLUMN, original[HEALTH_NEED_COLUMN])
    return original, numeric


def read_company_tables(
    workspace_dir: Path,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """3社の対応商品群購買指数表を読み、検証する。"""
    original_tables: dict[str, pd.DataFrame] = {}
    numeric_tables: dict[str, pd.DataFrame] = {}

    for company, config in COMPANY_INPUTS.items():
        source_path = (
            workspace_dir
            / config["project_dir"]
            / "Output"
            / config["file_name"]
        )
        if not source_path.exists():
            raise FileNotFoundError(
                f"{company}の対応商品群購買指数が見つかりません: {source_path}"
            )

        table = pd.read_csv(
            source_path,
            dtype=str,
            encoding="utf-8-sig",
        )
        original, numeric = validate_and_parse_table(
            table,
            company,
            source_path,
        )
        original_tables[company] = original
        numeric_tables[company] = numeric
        numeric_count = int(
            numeric.loc[:, list(ATTRIBUTE_ORDER)].count().sum()
        )
        print(f"{company}: 算出可能なセルを{numeric_count:,}件読み込みました。")

    return original_tables, numeric_tables


def make_combined_long_table(
    original_tables: dict[str, pd.DataFrame],
    numeric_tables: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """3社の指数を、1セル1行の縦長表へ統合する。"""
    rows: list[dict[str, object]] = []

    for company in COMPANY_INPUTS:
        original = original_tables[company]
        numeric = numeric_tables[company]

        for row_index, health_need in enumerate(HEALTH_NEEDS):
            for attribute in ATTRIBUTE_ORDER:
                numeric_value = numeric.at[row_index, attribute]
                output_value: object
                if pd.isna(numeric_value):
                    output_value = UNCOMPUTABLE_VALUE
                else:
                    output_value = float(numeric_value)

                rows.append(
                    {
                        "コンビニ": company,
                        HEALTH_NEED_COLUMN: health_need,
                        "消費者属性": attribute,
                        "対応商品群購買指数": output_value,
                    }
                )

    return pd.DataFrame(
        rows,
        columns=[
            "コンビニ",
            HEALTH_NEED_COLUMN,
            "消費者属性",
            "対応商品群購買指数",
        ],
    )


def calculate_thresholds(
    numeric_tables: dict[str, pd.DataFrame],
) -> tuple[pd.Series, float, float]:
    """全社共通の下側・上側閾値を算出する。"""
    value_parts = []
    for numeric in numeric_tables.values():
        stacked = numeric.loc[:, list(ATTRIBUTE_ORDER)].stack(dropna=True)
        value_parts.append(stacked.astype("float64"))

    valid_values = pd.concat(value_parts, ignore_index=True)
    if valid_values.empty:
        raise ValueError("算出可能な対応商品群購買指数が1件もありません。")

    lower_threshold = float(valid_values.quantile(LOW_QUANTILE))
    upper_threshold = float(valid_values.quantile(HIGH_QUANTILE))
    if lower_threshold > upper_threshold:
        raise RuntimeError("下側閾値が上側閾値を上回っています。")

    return valid_values, lower_threshold, upper_threshold


def classify_value(
    numeric_value: float,
    lower_threshold: float,
    upper_threshold: float,
) -> str:
    """1つの数値を共通閾値に基づいて分類する。"""
    if pd.isna(numeric_value):
        return UNCOMPUTABLE_VALUE
    if numeric_value < lower_threshold:
        return "小"
    if numeric_value < upper_threshold:
        return "中"
    return "大"


def make_category_table(
    numeric_table: pd.DataFrame,
    lower_threshold: float,
    upper_threshold: float,
) -> pd.DataFrame:
    """元の表と同じ形式で、大・中・小の分類表を作る。"""
    category_table = pd.DataFrame(
        {HEALTH_NEED_COLUMN: numeric_table[HEALTH_NEED_COLUMN]}
    )
    for attribute in ATTRIBUTE_ORDER:
        category_table[attribute] = numeric_table[attribute].map(
            lambda value: classify_value(
                value,
                lower_threshold,
                upper_threshold,
            )
        )
    return category_table.loc[:, [HEALTH_NEED_COLUMN, *ATTRIBUTE_ORDER]]


def run() -> None:
    """3社統合・閾値算出・三段階分類を実行して保存する。"""
    project_dir = Path(__file__).resolve().parents[1]
    workspace_dir = project_dir.parent
    output_dir = project_dir / "Output"
    output_dir.mkdir(parents=True, exist_ok=True)

    original_tables, numeric_tables = read_company_tables(workspace_dir)

    combined_table = make_combined_long_table(
        original_tables,
        numeric_tables,
    )
    combined_output_path = output_dir / COMBINED_OUTPUT_FILE_NAME
    combined_table.to_csv(
        combined_output_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
    )

    valid_values, lower_threshold, upper_threshold = calculate_thresholds(
        numeric_tables
    )
    threshold_table = pd.DataFrame(
        [
            {
                "算出対象セル数": int(valid_values.count()),
                "うち指数0のセル数": int(valid_values.eq(0).sum()),
                "下側閾値（第33.3パーセンタイル）": lower_threshold,
                "上側閾値（第66.7パーセンタイル）": upper_threshold,
            }
        ]
    )
    threshold_output_path = output_dir / THRESHOLD_OUTPUT_FILE_NAME
    threshold_table.to_csv(
        threshold_output_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
    )

    print(
        f"共通閾値: 小< {lower_threshold:.6f} / "
        f"中< {upper_threshold:.6f} / それ以上=大"
    )

    for company, config in COMPANY_INPUTS.items():
        category_table = make_category_table(
            numeric_tables[company],
            lower_threshold,
            upper_threshold,
        )
        category_output_path = output_dir / config["category_output"]
        category_table.to_csv(
            category_output_path,
            index=False,
            encoding="utf-8-sig",
        )

        category_counts = (
            category_table.loc[:, list(ATTRIBUTE_ORDER)]
            .stack()
            .value_counts()
            .to_dict()
        )
        print(
            f"{company}: 大中小表を保存しました "
            f"{category_counts} / {category_output_path}"
        )

    print(f"3社統合表を保存しました: {combined_output_path}")
    print(f"閾値表を保存しました: {threshold_output_path}")
    print("3社の大・中・小評価が完了しました。")


def main() -> None:
    run()


if __name__ == "__main__":
    main()
