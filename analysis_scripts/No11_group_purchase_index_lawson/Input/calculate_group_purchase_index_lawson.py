"""ローソンの個別商品購買指数を、健康ニーズ×属性のセルへ集約する。

No8の健康ニーズ別フォルダから「商品別属性別_個別商品購買指数.csv」を読み、
属性ごとに商品の個別商品購買指数を単純平均する。

計算ルール
----------
* 数値の0は有効な購買指数として平均に含める。
* 「算出不能」は平均に含めない。
* 健康ニーズ全体が「算出不能」の場合、対応商品群購買指数も「算出不能」とする。

出力
----
* ローソン_対応商品群購買指数.csv
* ローソン_平均使用商品数.csv
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


# =====================================================================
# 設定
# =====================================================================

SOURCE_PROJECT_DIR_NAME = "No8_purchase_index_lawson"
SOURCE_FILE_NAME = "商品別属性別_個別商品購買指数.csv"

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

PRODUCT_NUMBER_COLUMN = "商品番号"
HEALTH_NEED_COLUMN = "健康ニーズ"
UNCOMPUTABLE_VALUE = "算出不能"

MAIN_OUTPUT_FILE_NAME = "ローソン_対応商品群購買指数.csv"
COUNT_OUTPUT_FILE_NAME = "ローソン_平均使用商品数.csv"


def validate_input_table(
    table: pd.DataFrame,
    source_path: Path,
) -> None:
    """入力表に必要な列がすべてあることを確認する。"""
    required_columns = {PRODUCT_NUMBER_COLUMN, *ATTRIBUTE_ORDER}
    missing = sorted(required_columns - set(table.columns))
    if missing:
        raise ValueError(
            f"入力表に必要な列がありません: {missing}\n入力: {source_path}"
        )
    if table.empty:
        raise ValueError(
            f"入力表が空です。No8の出力を確認してください: {source_path}"
        )


def is_need_uncomputable(table: pd.DataFrame) -> bool:
    """健康ニーズ全体が算出不能の1行で表されているか確認する。"""
    product_numbers = (
        table[PRODUCT_NUMBER_COLUMN]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    return len(table) == 1 and product_numbers.iloc[0] == UNCOMPUTABLE_VALUE


def aggregate_one_need(
    health_need: str,
    source_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    """1健康ニーズの商品間平均と、平均に使用した商品数を返す。"""
    if not source_path.exists():
        raise FileNotFoundError(f"No8の入力表が見つかりません: {source_path}")

    table = pd.read_csv(
        source_path,
        dtype=str,
        encoding="utf-8-sig",
    )
    validate_input_table(table, source_path)

    group_index_row: dict[str, object] = {
        HEALTH_NEED_COLUMN: health_need,
    }
    used_product_count_row: dict[str, object] = {
        HEALTH_NEED_COLUMN: health_need,
    }

    if is_need_uncomputable(table):
        for attribute in ATTRIBUTE_ORDER:
            group_index_row[attribute] = UNCOMPUTABLE_VALUE
            used_product_count_row[attribute] = 0
        print(f"{health_need}: 個別商品購買指数が算出不能のため、集約も算出不能")
        return group_index_row, used_product_count_row

    # 商品番号が「算出不能」の行が実商品と混在していれば、入力不整合とする。
    product_numbers = (
        table[PRODUCT_NUMBER_COLUMN]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    if product_numbers.eq(UNCOMPUTABLE_VALUE).any():
        raise ValueError(
            f"実商品と算出不能行が混在しています: {source_path}"
        )

    for attribute in ATTRIBUTE_ORDER:
        # 0は数値のまま残る。「算出不能」や空欄だけがNaNになる。
        numeric_values = pd.to_numeric(
            table[attribute],
            errors="coerce",
        )
        valid_values = numeric_values.dropna()

        if valid_values.empty:
            group_index_row[attribute] = UNCOMPUTABLE_VALUE
            used_product_count_row[attribute] = 0
        else:
            group_index_row[attribute] = float(valid_values.mean())
            used_product_count_row[attribute] = int(valid_values.count())

    total_products = len(table)
    count_values = [
        int(used_product_count_row[attribute])
        for attribute in ATTRIBUTE_ORDER
    ]
    print(
        f"{health_need}: 商品{total_products:,}件を読み込み / "
        f"属性別の平均使用商品数={min(count_values)}～{max(count_values)}件"
    )
    return group_index_row, used_product_count_row


def run() -> tuple[Path, Path]:
    """3健康ニーズを集約し、メイン表と確認用表を保存する。"""
    project_dir = Path(__file__).resolve().parents[1]
    workspace_dir = project_dir.parent
    source_output_dir = workspace_dir / SOURCE_PROJECT_DIR_NAME / "Output"
    output_dir = project_dir / "Output"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not source_output_dir.exists():
        raise FileNotFoundError(
            f"No8のOutputが見つかりません: {source_output_dir}"
        )

    group_index_rows: list[dict[str, object]] = []
    used_product_count_rows: list[dict[str, object]] = []

    for health_need in HEALTH_NEEDS:
        source_path = (
            source_output_dir
            / health_need
            / SOURCE_FILE_NAME
        )
        group_index_row, used_product_count_row = aggregate_one_need(
            health_need,
            source_path,
        )
        group_index_rows.append(group_index_row)
        used_product_count_rows.append(used_product_count_row)

    output_columns = [HEALTH_NEED_COLUMN, *ATTRIBUTE_ORDER]
    group_index_table = pd.DataFrame(
        group_index_rows,
        columns=output_columns,
    )
    used_product_count_table = pd.DataFrame(
        used_product_count_rows,
        columns=output_columns,
    )

    main_output_path = output_dir / MAIN_OUTPUT_FILE_NAME
    count_output_path = output_dir / COUNT_OUTPUT_FILE_NAME

    # 「算出不能」を残すため、表全体をobject型のまま保存する。
    group_index_table.to_csv(
        main_output_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
    )
    used_product_count_table.to_csv(
        count_output_path,
        index=False,
        encoding="utf-8-sig",
    )

    if group_index_table[HEALTH_NEED_COLUMN].tolist() != list(HEALTH_NEEDS):
        raise RuntimeError("対応商品群購買指数表の健康ニーズ順が一致しません。")
    if used_product_count_table[HEALTH_NEED_COLUMN].tolist() != list(
        HEALTH_NEEDS
    ):
        raise RuntimeError("平均使用商品数表の健康ニーズ順が一致しません。")

    print(f"対応商品群購買指数を保存しました: {main_output_path}")
    print(f"平均使用商品数を保存しました: {count_output_path}")
    print("ローソンの商品群計算が完了しました。")
    return main_output_path, count_output_path


def main() -> None:
    run()


if __name__ == "__main__":
    main()
