"""比較群の購買経験群・購買未経験群で人数とセブン利用日数を揃える。

目的
----
男女40代・50代を「比較群」とし、セブンイレブンの
「栄養バランスを調整したい」対応商品について、次の2群を作る。

1. 購買経験群: 対応商品を1回以上購買した比較群ユーザー
2. 購買未経験群: セブンは利用したが、対応商品を一度も購買していない比較群ユーザー

購買経験群は全員残し、購買未経験群から同数のユーザーを抽出する。
抽出時には、セブン利用日数の分布が購買経験群へできるだけ近づくようにする。

入力
----
1. このファイル内で用意するセブンイレブン全体のDataFrame
   ``data1`` ～ ``data5``
2. No4の ``Output/栄養バランス`` にある商品別CSV
3. 同フォルダの ``product_file_mapping.csv``

出力
----
No22の ``Output`` に次のファイルを保存する。

* ``01_条件調整後ユーザー一覧.csv``
* ``02_条件調整前後要約.csv``
* ``03_利用日数分布確認.csv``
* ``04_条件調整品質確認.csv``
* ``05_データ品質確認.csv``

Zaimの1行は1商品の購買記録であるため、同じユーザー・同じ日付に
複数行があっても、利用日数は1日として数える。

注意
----
出力にはユーザーIDが含まれる。会社環境内だけで管理し、個人PC、Notion、
GitHub等へ保存・共有しないこと。実データや認証情報もこのファイルへ
直接記入しないこと。
"""

from __future__ import annotations

import gc
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Optional

import pandas as pd


# =====================================================================
# 【分析条件】
# =====================================================================

COMPARISON_AGES = ("40代", "50代")
RANDOM_SEED = 20260918

SOURCE_PRODUCT_PROJECT_DIR_NAME = "No4_extract_confirmed_products_seven"
SOURCE_HEALTH_NEED_DIR_NAME = "栄養バランス"
SOURCE_USAGE_SCRIPT = (
    "No16_compare_seven_usage_days/Input/compare_seven_usage_days.py"
)
SOURCE_BALANCE_SCRIPT = "No17_balance_usage_days/Input/balance_usage_days.py"


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
# 必要列: date, user_id, user_gender, user_age_att_layer
# 認証情報は、このファイルへ直接記入しないこと。
# =====================================================================


def load_module(module_name: str, path: Path) -> ModuleType:
    """既存の検証済み処理を、指定したファイルから読み込む。"""
    if not path.exists():
        raise FileNotFoundError(f"参照する既存スクリプトが見つかりません: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"スクリプトを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(
    dataframes: list[pd.DataFrame],
    product_source_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    random_seed: int = RANDOM_SEED,
) -> list[Path]:
    """比較群を二群へ分け、人数と利用日数を揃えて保存する。"""
    if len(dataframes) != 5:
        raise ValueError("data1～data5の5つのDataFrameを指定してください。")

    project_dir = Path(__file__).resolve().parents[1]
    workspace_dir = project_dir.parent
    usage_module = load_module(
        "no16_usage_days_shared",
        workspace_dir / SOURCE_USAGE_SCRIPT,
    )
    balance_module = load_module(
        "no17_balance_usage_days_shared",
        workspace_dir / SOURCE_BALANCE_SCRIPT,
    )

    # No16で検証済みの抽出処理を、40代・50代へ限定して再利用する。
    usage_module.YOUNG_AGES = COMPARISON_AGES

    product_source_dir = product_source_dir or (
        workspace_dir
        / SOURCE_PRODUCT_PROJECT_DIR_NAME
        / "Output"
        / SOURCE_HEALTH_NEED_DIR_NAME
    )
    output_dir = output_dir or project_dir / "Output"
    if not product_source_dir.exists():
        raise FileNotFoundError(
            "No4の栄養バランス商品フォルダが見つかりません。"
            f"\n確認対象: {product_source_dir}"
        )

    company_data, company_quality = usage_module.combine_company_data(dataframes)
    dataframes.clear()
    gc.collect()
    print("元の5期間分DataFrameをメモリから解放しました。")

    experienced_ids, product_quality = usage_module.collect_experienced_user_ids(
        product_source_dir
    )
    original, group_counts, set_checks = usage_module.classify_users_and_count_days(
        company_data,
        experienced_ids,
    )
    del company_data
    gc.collect()

    selected, internal_match = balance_module.select_balanced_users(
        original,
        random_seed=random_seed,
    )
    output_paths = balance_module.save_outputs(
        original=original,
        selected=selected,
        internal_match=internal_match,
        output_dir=output_dir,
        random_seed=random_seed,
    )

    set_check_table = pd.DataFrame(
        [
            {
                "データ種別": "集合整合性確認",
                "入力元": "比較群全体",
                "確認項目": str(item).replace("若年層", "比較群"),
                "行数": count,
            }
            for item, count in set_checks.items()
        ]
    )
    count_table = group_counts.rename(
        columns={"ユーザー数": "行数", "群": "確認項目"}
    ).copy()
    count_table["データ種別"] = "群別人数"
    count_table["入力元"] = "条件調整前"
    count_table["確認項目"] = count_table["確認項目"].astype(str) + "ユーザー数"
    quality_table = pd.concat(
        [
            company_quality,
            product_quality,
            set_check_table,
            count_table[["データ種別", "入力元", "確認項目", "行数"]],
        ],
        ignore_index=True,
        sort=False,
    )
    quality_path = output_dir / "05_データ品質確認.csv"
    quality_table.to_csv(quality_path, index=False, encoding="utf-8-sig")
    output_paths.append(quality_path)

    before_counts = original[balance_module.GROUP_COLUMN].value_counts()
    after_counts = selected[balance_module.GROUP_COLUMN].value_counts()
    smd = balance_module.standardized_mean_difference(selected)
    print("\n比較群の人数・利用日数の条件調整が完了しました。")
    print(
        "条件調整前: "
        f"購買経験群={int(before_counts[balance_module.EXPERIENCED_GROUP]):,}人 / "
        f"購買未経験群={int(before_counts[balance_module.UNEXPERIENCED_GROUP]):,}人"
    )
    print(
        "条件調整後: "
        f"購買経験群={int(after_counts[balance_module.EXPERIENCED_GROUP]):,}人 / "
        f"購買未経験群={int(after_counts[balance_module.UNEXPERIENCED_GROUP]):,}人"
    )
    print(f"条件調整後の利用日数SMD: {smd:.6f}")
    if not pd.notna(smd) or abs(smd) >= balance_module.SMD_WARNING_THRESHOLD:
        print(
            "注意: 利用日数のSMDが0.10以上です。"
            "02・03・04の確認表を見てからNo23へ進んでください。"
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
