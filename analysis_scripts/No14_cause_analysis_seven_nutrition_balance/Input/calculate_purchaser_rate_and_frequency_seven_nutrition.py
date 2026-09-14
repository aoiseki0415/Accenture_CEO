"""セブンイレブンの栄養バランス対応商品を、購入者率と購入頻度へ分解する。

分析対象
--------
* 男性20代
* 男性30代
* 女性20代
* 女性30代

入力
----
1. このファイル内で用意する、セブンイレブン全体のDataFrame ``data1`` ～ ``data5``
2. No4の ``Output/栄養バランス`` にある商品別CSV
3. 同フォルダの ``product_file_mapping.csv``

出力
----
No14の ``Output`` 直下へ、4属性それぞれのCSVを保存する。

* 男性20代.csv
* 男性30代.csv
* 女性20代.csv
* 女性30代.csv

実データや認証情報はこのファイルへ直接記入しないこと。
"""

from __future__ import annotations

import gc
from pathlib import Path
import re
from typing import Optional

import pandas as pd


# =====================================================================
# 【ユーザー設定欄】
# =====================================================================

SOURCE_PROJECT_DIR_NAME = "No4_extract_confirmed_products_seven"
SOURCE_HEALTH_NEED_DIR_NAME = "栄養バランス"

PURCHASE_DATE_COLUMN = "date"
USER_ID_COLUMN = "user_id"
GENDER_COLUMN = "user_gender"
PURCHASE_AGE_LAYER_COLUMN = "user_age_att_layer"

INDEX_SCALE = 1000

# 原因分析の対象として特定した4属性だけを扱う。
TARGET_SEGMENTS = (
    ("男性", "20代", "男性20代.csv"),
    ("男性", "30代", "男性30代.csv"),
    ("女性", "20代", "女性20代.csv"),
    ("女性", "30代", "女性30代.csv"),
)

OUTPUT_COLUMNS = (
    "商品番号",
    "商品名",
    "最初の記録日",
    "最後の記録日",
    "購買記録数",
    "購入者数",
    "対象者数",
    "購入者率（%）",
    "購入頻度（回/購入者）",
    "個別商品購買指数",
)


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


def age_to_label(value: object) -> Optional[str]:
    """購入時年代表記を20代・30代へ正規化し、それ以外は対象外にする。"""
    if pd.isna(value):
        return None

    text = str(value).strip()
    if not text or "不明" in text:
        return None

    match = re.search(r"(\d+)", text)
    if match is None:
        return None

    numeric_value = int(match.group(1))
    if 20 <= numeric_value < 30:
        return "20代"
    if 30 <= numeric_value < 40:
        return "30代"
    return None


def add_segment_column(
    data: pd.DataFrame,
    source_name: str,
) -> pd.DataFrame:
    """コピーを増やさず、日付変換と分析対象セグメントの付与を行う。"""
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

    gender = data[GENDER_COLUMN].fillna("").astype(str).str.strip()
    age = data[PURCHASE_AGE_LAYER_COLUMN].map(age_to_label)
    valid_gender = gender.isin({"男性", "女性"})
    data["_segment"] = (
        gender.where(valid_gender) + "・" + age
    ).where(valid_gender & age.notna())
    return data


def combine_company_data(dataframes: list[pd.DataFrame]) -> pd.DataFrame:
    """対象者数の計算に必要な4列だけを、5期間分縦結合する。"""
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

    combined = pd.concat(
        [data.loc[:, required_columns] for data in dataframes],
        ignore_index=True,
        sort=False,
        copy=False,
    )
    if len(combined) != expected_rows:
        raise RuntimeError("結合前後でセブン全体データの行数が一致しません。")

    print(f"5期間分の必要4列を結合しました: {len(combined):,}行")
    return combined


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

    if mapping["商品番号"].duplicated().any():
        duplicated = mapping.loc[
            mapping["商品番号"].duplicated(keep=False), "商品番号"
        ].tolist()
        raise ValueError(f"商品番号が重複しています: {duplicated}")
    if mapping["出力ファイル名"].eq("").any():
        raise ValueError("出力ファイル名が空の商品があります。")
    return mapping


def calculate_target_users(
    company_data: pd.DataFrame,
    first_date: pd.Timestamp,
    last_date: pd.Timestamp,
) -> pd.Series:
    """商品観測期間内のセブン利用者を、4セグメント別に数える。"""
    period_mask = company_data[PURCHASE_DATE_COLUMN].between(
        first_date,
        last_date,
        inclusive="both",
    )
    eligible = company_data.loc[
        period_mask
        & company_data["_segment"].notna()
        & company_data[USER_ID_COLUMN].notna(),
        ["_segment", USER_ID_COLUMN],
    ]
    segment_order = [
        f"{gender}・{age}"
        for gender, age, _ in TARGET_SEGMENTS
    ]
    return (
        eligible.groupby("_segment")[USER_ID_COLUMN]
        .nunique()
        .reindex(segment_order, fill_value=0)
        .astype("int64")
    )


def make_output_row(
    product_number: str,
    product_name: str,
    first_date: pd.Timestamp,
    last_date: pd.Timestamp,
    purchase_count: int,
    purchaser_count: int,
    target_user_count: int,
) -> dict[str, object]:
    """1商品・1セグメントの購入者率、購入頻度、指数を計算する。"""
    if target_user_count == 0:
        purchaser_rate_percent: object = "算出不能"
        purchase_frequency: object = "算出不能"
        individual_index: object = "算出不能"
    elif purchase_count == 0:
        # 商品全体には記録があるが、この属性の購入が0件なら有効な0とする。
        purchaser_rate_percent = 0.0
        purchase_frequency = 0.0
        individual_index = 0.0
    else:
        if purchaser_count == 0:
            raise ValueError(
                f"商品{product_number}は購買記録がある一方、"
                "購入者をuser_idで特定できません。"
            )
        if purchaser_count > target_user_count:
            raise ValueError(
                f"商品{product_number}の購入者数が対象者数を上回っています。"
                "商品別CSVとセブン全体データの対象期間・抽出条件を確認してください。"
            )
        purchaser_rate = purchaser_count / target_user_count
        purchase_frequency = purchase_count / purchaser_count
        individual_index = purchaser_rate * purchase_frequency * INDEX_SCALE
        purchaser_rate_percent = purchaser_rate * 100

        # 既存の個別商品購買指数と同じ式になることを検算する。
        direct_index = purchase_count / target_user_count * INDEX_SCALE
        if abs(individual_index - direct_index) > 1e-12:
            raise RuntimeError(
                f"商品{product_number}の指数分解が一致しません。"
            )

    return {
        "商品番号": product_number,
        "商品名": product_name,
        "最初の記録日": first_date.strftime("%Y-%m-%d"),
        "最後の記録日": last_date.strftime("%Y-%m-%d"),
        "購買記録数": purchase_count,
        "購入者数": purchaser_count,
        "対象者数": target_user_count,
        "購入者率（%）": purchaser_rate_percent,
        "購入頻度（回/購入者）": purchase_frequency,
        "個別商品購買指数": individual_index,
    }


def calculate_all_products(
    company_data: pd.DataFrame,
    product_source_dir: Path,
) -> dict[str, list[dict[str, object]]]:
    """No4の全商品について、4セグメントの結果行を作る。"""
    mapping = read_product_mapping(
        product_source_dir / "product_file_mapping.csv"
    )
    segment_rows: dict[str, list[dict[str, object]]] = {
        f"{gender}・{age}": []
        for gender, age, _ in TARGET_SEGMENTS
    }

    # 同じ観測期間の商品が複数あれば、対象者数を再利用する。
    target_user_cache: dict[tuple[pd.Timestamp, pd.Timestamp], pd.Series] = {}

    for _, mapping_row in mapping.iterrows():
        product_number = str(mapping_row["商品番号"])
        product_name = str(mapping_row["商品名"])
        product_csv_path = product_source_dir / str(
            mapping_row["出力ファイル名"]
        )
        if not product_csv_path.exists():
            raise FileNotFoundError(
                f"商品{product_number}のCSVが見つかりません: {product_csv_path}"
            )

        product_data = pd.read_csv(
            product_csv_path,
            low_memory=False,
            encoding="utf-8-sig",
        )
        if product_data.empty:
            raise ValueError(
                f"商品{product_number}のCSVが空です: {product_csv_path}"
            )

        add_segment_column(product_data, f"商品{product_number}")
        valid_dates = product_data[PURCHASE_DATE_COLUMN].dropna()
        if valid_dates.empty:
            raise ValueError(
                f"商品{product_number}に有効な購入日がありません: {product_csv_path}"
            )

        first_date = valid_dates.min()
        last_date = valid_dates.max()
        period_key = (first_date, last_date)
        if period_key not in target_user_cache:
            target_user_cache[period_key] = calculate_target_users(
                company_data,
                first_date,
                last_date,
            )
        target_users = target_user_cache[period_key]

        for gender, age, _ in TARGET_SEGMENTS:
            segment = f"{gender}・{age}"
            segment_data = product_data.loc[
                product_data["_segment"].eq(segment)
            ]

            missing_user_count = int(
                segment_data[USER_ID_COLUMN].isna().sum()
            )
            if missing_user_count:
                raise ValueError(
                    f"商品{product_number}・{segment}にuser_id欠損の購買記録が"
                    f"{missing_user_count:,}件あります。購入者率と購入頻度を"
                    "正しく分解できないため処理を停止しました。"
                )

            purchase_count = len(segment_data)
            purchaser_count = int(
                segment_data[USER_ID_COLUMN].nunique()
            )
            target_user_count = int(target_users.loc[segment])

            segment_rows[segment].append(
                make_output_row(
                    product_number=product_number,
                    product_name=product_name,
                    first_date=first_date,
                    last_date=last_date,
                    purchase_count=purchase_count,
                    purchaser_count=purchaser_count,
                    target_user_count=target_user_count,
                )
            )

        print(
            f"[{product_number}] {product_name}: "
            f"観測期間={first_date.date()}～{last_date.date()}"
        )

    return segment_rows


def save_segment_outputs(
    segment_rows: dict[str, list[dict[str, object]]],
    output_dir: Path,
) -> list[Path]:
    """4セグメントを、それぞれ独立したCSVとして保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []

    for gender, age, filename in TARGET_SEGMENTS:
        segment = f"{gender}・{age}"
        table = pd.DataFrame(
            segment_rows[segment],
            columns=OUTPUT_COLUMNS,
        )
        output_path = output_dir / filename
        table.to_csv(
            output_path,
            index=False,
            encoding="utf-8-sig",
            float_format="%.6f",
        )
        output_paths.append(output_path)
        print(f"{segment}の結果を保存しました: {output_path}")

    return output_paths


def run(
    dataframes: list[pd.DataFrame],
    product_source_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> list[Path]:
    """セブン・栄養バランスの4セグメントについて分析する。"""
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

    company_data = combine_company_data(dataframes)
    dataframes.clear()
    gc.collect()
    print("結合前の5期間分データをメモリから解放しました。")

    add_segment_column(company_data, "結合後のセブン全体データ")
    print("結合済みデータへ分析対象セグメントを付与しました。")

    segment_rows = calculate_all_products(
        company_data=company_data,
        product_source_dir=product_source_dir,
    )
    output_paths = save_segment_outputs(segment_rows, output_dir)
    print("\nセブン・栄養バランスの原因分析用集計が完了しました。")
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
