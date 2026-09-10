"""ローソンの3健康ニーズについて、商品別・属性別の購買指数を算出する。

入力
----
1. このファイル内で用意する、ローソン全体のDataFrame ``data1`` ～ ``data5``
2. No5のOutputに保存済みの商品別CSVと ``product_file_mapping.csv``

出力
----
No7のOutput配下に健康ニーズ別フォルダを作り、各フォルダへ次の3表を保存する。

* 商品別属性別_購買記録数.csv
* 商品別属性別_対象者数.csv
* 商品別属性別_個別商品購買指数.csv

実データや認証情報はこのファイルへ直接記入しないこと。
"""

from __future__ import annotations

import gc
from pathlib import Path
import re
from typing import Optional

import numpy as np
import pandas as pd


# =====================================================================
# 【ユーザー設定欄】
# =====================================================================

# No5で作成した商品別CSVの保存フォルダ名。
SOURCE_PROJECT_DIR_NAME = "No5_extract_confirmed_products_lawson"

HEALTH_NEEDS = (
    "栄養バランス",
    "脂質",
    "エネルギー",
)

# 購買データ内の列名。
PURCHASE_DATE_COLUMN = "date"
USER_ID_COLUMN = "user_id"
GENDER_COLUMN = "user_gender"
PURCHASE_AGE_LAYER_COLUMN = "user_age_att_layer"

# 性別は文字列の「男性」「女性」だけを使用する。
# 「その他・不明」や欠損は属性不明として除外する。
VALID_GENDERS = ("男性", "女性")

# 今回は20歳未満を分析対象外とするため、これらの年代表記は明示的に除外する。
EXCLUDED_AGE_LABELS = (
    "10歳未満",
    "10代",
)

# 今回の本分析では、20代から70代までを対象にする。
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

# 個別商品購買指数を「対象者1,000人当たり」にするための倍率。
INDEX_SCALE = 1000


# =====================================================================
# 【ユーザー記入欄】S3読込テンプレートで data1～data5 を作成する
# =====================================================================
# この位置に、会社環境で用意されたS3読込コードを貼り付ける。
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


def age_to_label(value: object) -> Optional[str]:
    """「20代」などの購入時年代表記を、分析用の6区分へ変換する。"""
    if pd.isna(value):
        return None

    text = str(value).strip()
    if (
        not text
        or "不明" in text
        or text in EXCLUDED_AGE_LABELS
    ):
        return None

    # 「20代」「70代」などから先頭の年代を取得する。
    match = re.search(r"(\d+)", text)
    if match is None:
        return None
    numeric_value = int(match.group(1))

    # 20歳未満は、上の明示表記以外の形式であってもすべて除外する。
    if numeric_value < 20:
        return None
    if numeric_value < 30:
        return "20代"
    if 30 <= numeric_value < 40:
        return "30代"
    if 40 <= numeric_value < 50:
        return "40代"
    if 50 <= numeric_value < 60:
        return "50代"
    if 60 <= numeric_value < 70:
        return "60代"
    if 70 <= numeric_value < 80:
        return "70代"
    return None


def add_attribute_column(
    data: pd.DataFrame,
    source_name: str,
) -> pd.DataFrame:
    """コピーを作らず、日付変換と性別×購入時年代の属性付与を行う。"""
    required_columns = {
        PURCHASE_DATE_COLUMN,
        USER_ID_COLUMN,
        GENDER_COLUMN,
        PURCHASE_AGE_LAYER_COLUMN,
    }
    require_columns(data, required_columns, source_name)

    data[PURCHASE_DATE_COLUMN] = pd.to_datetime(
        data[PURCHASE_DATE_COLUMN], errors="coerce"
    )

    gender_text = data[GENDER_COLUMN].fillna("").astype(str).str.strip()
    gender_label = gender_text.where(gender_text.isin(VALID_GENDERS))
    age_label = data[PURCHASE_AGE_LAYER_COLUMN].map(age_to_label)

    data["_attribute"] = np.where(
        gender_label.notna() & age_label.notna(),
        gender_label.fillna("") + "・" + age_label.fillna(""),
        None,
    )
    return data


def combine_company_data(dataframes: list[pd.DataFrame]) -> pd.DataFrame:
    """分母計算に必要な4列だけを使い、5期間分を縦結合する。"""
    required_columns = [
        PURCHASE_DATE_COLUMN,
        USER_ID_COLUMN,
        GENDER_COLUMN,
        PURCHASE_AGE_LAYER_COLUMN,
    ]
    expected_rows = 0

    for number, data in enumerate(dataframes, start=1):
        require_columns(data, set(required_columns), f"data{number}")
        expected_rows += len(data)

    # 商品名など、分母の計算に使わない列は巨大な結合データへ引き継がない。
    combined = pd.concat(
        [data.loc[:, required_columns] for data in dataframes],
        ignore_index=True,
        sort=False,
        copy=False,
    )
    if len(combined) != expected_rows:
        raise RuntimeError("結合前後でコンビニ全体データの行数が一致しません。")

    print(f"5期間分の必要4列を結合しました: {len(combined):,}行")
    return combined


def read_product_mapping(mapping_path: Path) -> pd.DataFrame:
    """No5の商品番号・ファイル対応表を読み込む。"""
    if not mapping_path.exists():
        raise FileNotFoundError(f"商品対応表が見つかりません: {mapping_path}")

    mapping = pd.read_csv(
        mapping_path,
        dtype=str,
        encoding="utf-8-sig",
    ).fillna("")
    require_columns(
        mapping,
        {"商品番号", "出力ファイル名"},
        str(mapping_path),
    )
    if mapping.empty:
        raise ValueError(f"商品対応表が空です: {mapping_path}")

    mapping["商品番号"] = mapping["商品番号"].str.strip().str.zfill(3)
    mapping["出力ファイル名"] = mapping["出力ファイル名"].str.strip()
    if mapping["商品番号"].duplicated().any():
        duplicated = mapping.loc[
            mapping["商品番号"].duplicated(keep=False), "商品番号"
        ].tolist()
        raise ValueError(f"商品番号が重複しています: {duplicated}")
    return mapping


def save_uncomputable_result_tables(
    output_dir: Path,
    health_need: str,
) -> None:
    """商品別CSVが0件の場合に、算出不能を明示した結果を保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_columns = ["商品番号", *ATTRIBUTE_ORDER]

    # 3表すべてで、全属性について算出できないことを1行で明示する。
    uncomputable_row = {
        column: "算出不能"
        for column in output_columns
    }
    uncomputable_table = pd.DataFrame(
        [uncomputable_row],
        columns=output_columns,
    )
    uncomputable_table.to_csv(
        output_dir / "商品別属性別_購買記録数.csv",
        index=False,
        encoding="utf-8-sig",
    )
    uncomputable_table.to_csv(
        output_dir / "商品別属性別_対象者数.csv",
        index=False,
        encoding="utf-8-sig",
    )
    uncomputable_table.to_csv(
        output_dir / "商品別属性別_個別商品購買指数.csv",
        index=False,
        encoding="utf-8-sig",
    )
    print(
        f"{health_need}: 商品別CSVが0件のため、"
        f"3表を算出不能として保存しました: {output_dir}"
    )


def calculate_target_users(
    company_data: pd.DataFrame,
    first_date: pd.Timestamp,
    last_date: pd.Timestamp,
) -> pd.Series:
    """商品の観測期間における、属性別ユニーク対象者数を算出する。"""
    period_mask = company_data[PURCHASE_DATE_COLUMN].between(
        first_date,
        last_date,
        inclusive="both",
    )
    eligible = company_data.loc[
        period_mask
        & company_data["_attribute"].notna()
        & company_data[USER_ID_COLUMN].notna(),
        ["_attribute", USER_ID_COLUMN],
    ]
    return (
        eligible.groupby("_attribute")[USER_ID_COLUMN]
        .nunique()
        .reindex(ATTRIBUTE_ORDER, fill_value=0)
        .astype("int64")
    )


def calculate_one_need(
    company_data: pd.DataFrame,
    health_need: str,
    product_source_dir: Path,
    output_dir: Path,
) -> None:
    """1健康ニーズについて3種類の2次元表を作成する。"""
    product_csv_paths = sorted(
        product_source_dir.glob("product_[0-9][0-9][0-9].csv")
    )
    if not product_csv_paths:
        save_uncomputable_result_tables(output_dir, health_need)
        return

    mapping_path = product_source_dir / "product_file_mapping.csv"
    mapping = read_product_mapping(mapping_path)

    output_dir.mkdir(parents=True, exist_ok=True)

    purchase_count_rows: list[dict[str, object]] = []
    target_user_rows: list[dict[str, object]] = []
    purchase_index_rows: list[dict[str, object]] = []

    # 同じ観測期間の商品が複数ある場合は、対象者数を再利用する。
    target_user_cache: dict[tuple[pd.Timestamp, pd.Timestamp], pd.Series] = {}

    for _, mapping_row in mapping.iterrows():
        product_number = str(mapping_row["商品番号"]).zfill(3)
        output_filename = str(mapping_row["出力ファイル名"])
        product_csv_path = product_source_dir / output_filename

        if not product_csv_path.exists():
            raise FileNotFoundError(
                f"{health_need}の商品CSVが見つかりません: {product_csv_path}"
            )

        product_data = pd.read_csv(
            product_csv_path,
            low_memory=False,
            encoding="utf-8-sig",
        )
        if product_data.empty:
            raise ValueError(
                f"商品{product_number}のCSVが空のため、観測期間を決められません: "
                f"{product_csv_path}"
            )

        product_data = add_attribute_column(
            product_data,
            f"{health_need}・商品{product_number}",
        )
        valid_dates = product_data[PURCHASE_DATE_COLUMN].dropna()
        if valid_dates.empty:
            raise ValueError(
                f"商品{product_number}に有効な購入日がありません: {product_csv_path}"
            )

        first_date = valid_dates.min()
        last_date = valid_dates.max()

        purchase_counts = (
            product_data.loc[product_data["_attribute"].notna(), "_attribute"]
            .value_counts()
            .reindex(ATTRIBUTE_ORDER, fill_value=0)
            .astype("int64")
        )

        period_key = (first_date, last_date)
        if period_key not in target_user_cache:
            target_user_cache[period_key] = calculate_target_users(
                company_data,
                first_date,
                last_date,
            )
        target_users = target_user_cache[period_key]

        # 対象者が0人の属性だけ算出不能（NaN）とする。
        individual_index = (
            purchase_counts.astype("float64")
            .div(target_users.replace(0, np.nan))
            .mul(INDEX_SCALE)
        )

        purchase_count_rows.append(
            {"商品番号": product_number, **purchase_counts.to_dict()}
        )
        target_user_rows.append(
            {"商品番号": product_number, **target_users.to_dict()}
        )
        purchase_index_rows.append(
            {"商品番号": product_number, **individual_index.to_dict()}
        )

        known_attribute_rows = int(purchase_counts.sum())
        print(
            f"[{health_need} / {product_number}] "
            f"観測期間={first_date.date()}～{last_date.date()} / "
            f"属性判明購買={known_attribute_rows:,}行"
        )

    output_columns = ["商品番号", *ATTRIBUTE_ORDER]
    purchase_count_table = pd.DataFrame(
        purchase_count_rows,
        columns=output_columns,
    )
    target_user_table = pd.DataFrame(
        target_user_rows,
        columns=output_columns,
    )
    purchase_index_table = pd.DataFrame(
        purchase_index_rows,
        columns=output_columns,
    )

    purchase_count_table.to_csv(
        output_dir / "商品別属性別_購買記録数.csv",
        index=False,
        encoding="utf-8-sig",
    )
    target_user_table.to_csv(
        output_dir / "商品別属性別_対象者数.csv",
        index=False,
        encoding="utf-8-sig",
    )
    purchase_index_table.to_csv(
        output_dir / "商品別属性別_個別商品購買指数.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
    )

    if not (
        purchase_count_table["商品番号"].tolist()
        == target_user_table["商品番号"].tolist()
        == purchase_index_table["商品番号"].tolist()
    ):
        raise RuntimeError(f"{health_need}の3表で商品番号の順序が一致しません。")

    print(f"{health_need}の3表を保存しました: {output_dir}")


def run(
    dataframes: list[pd.DataFrame],
) -> None:
    """ローソンの3健康ニーズを順番に処理する。"""
    project_dir = Path(__file__).resolve().parents[1]
    workspace_dir = project_dir.parent
    source_output_dir = workspace_dir / SOURCE_PROJECT_DIR_NAME / "Output"
    output_root = project_dir / "Output"

    if not source_output_dir.exists():
        raise FileNotFoundError(
            "No5の商品別CSV保存先が見つかりません。"
            f"\n確認対象: {source_output_dir}"
        )

    # 実処理前に3つの健康ニーズ用フォルダをすべて作る。
    need_output_dirs = {
        health_need: output_root / health_need
        for health_need in HEALTH_NEEDS
    }
    for need_output_dir in need_output_dirs.values():
        need_output_dir.mkdir(parents=True, exist_ok=True)

    company_data = combine_company_data(dataframes)

    # 結合後は元のdata1～data5を保持する必要がないため、参照を解放する。
    dataframes.clear()
    gc.collect()
    print("結合前の5期間分データをメモリから解放しました。")

    # 結合済みの4列へ属性列を直接追加し、全体コピーは作らない。
    add_attribute_column(company_data, "結合後のコンビニ全体データ")
    print("結合済みデータへ分析属性を付与しました。")

    for health_need in HEALTH_NEEDS:
        product_source_dir = source_output_dir / health_need
        if not product_source_dir.exists():
            raise FileNotFoundError(
                f"No5の健康ニーズ別フォルダが見つかりません: {product_source_dir}"
            )
        calculate_one_need(
            company_data=company_data,
            health_need=health_need,
            product_source_dir=product_source_dir,
            output_dir=need_output_dirs[health_need],
        )

    print("\nローソンの3健康ニーズの処理が完了しました。")


def main() -> None:
    data_names = ["data1", "data2", "data3", "data4", "data5"]
    missing = [name for name in data_names if name not in globals()]
    if missing:
        raise RuntimeError(
            "ユーザー記入欄で次のDataFrameを作成してください: "
            + ", ".join(missing)
        )
    # globalsから取り出して削除し、結合後に元DataFrameを解放できるようにする。
    dataframes = [globals().pop(name) for name in data_names]
    run(dataframes)


if __name__ == "__main__":
    main()
