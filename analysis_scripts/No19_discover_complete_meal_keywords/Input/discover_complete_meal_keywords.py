"""JICFS Lv4「惣菜類」から、一食完結型を抽出するキーワードを探索する。

目的
----
消費者が商品に担わせる役割に基づき、惣菜類を将来的に次の2群へ分ける。

1. 一食完結型: その商品だけで一回の食事を完結させる役割
2. 食事補完型: 家庭内の食事等を補足する役割

No19では最終分類までは行わず、実際のZaim商品名を用いて
「一食完結型」の候補を抽出するキーワードを点検する。

入力
----
このファイル内のユーザー記入欄で、S3から読み込んだ5期間のDataFrame
``data1`` ～ ``data5`` を用意する。

必要列:

* ``date``
* ``name``
* ``item_jicfs_lv4_code``
* ``item_jicfs_lv4_name``
* ``item_jicfs_lv6_code``
* ``item_jicfs_lv6_name``

出力
----
No19の ``Output`` に次のファイルを保存する。

* ``01_Lv4惣菜類の商品一覧.csv``
* ``02_一食完結型キーワード別集計.csv``
* ``03_一食完結型候補商品.csv``
* ``04_要確認商品.csv``
* ``05_未抽出商品_購買記録数順.csv``
* ``06_キーワード抽出カバー率.csv``
* ``07_Lv6カテゴリー別集計.csv``
* ``08_データ品質確認.csv``
* ``09_使用キーワード一覧.csv``

判定の考え方
------------
* 一食完結型キーワードに該当し、要確認表現を含まない商品は
  ``一食完結型候補`` とする。
* 両方を含む商品は ``要確認`` とする。
* 一食完結型キーワードに該当しない商品は ``未抽出`` とする。
* ``未抽出`` を自動的に食事補完型とは判定しない。購買記録数の多い順に
  目視確認し、不足キーワードを追加してから最終分類を行う。

注意
----
* 一つの商品が複数キーワードへ該当することがあるため、キーワード別集計の
  商品数・購買記録数はキーワード間で重複し得る。
* 5期間のローデータは一度に結合しない。期間ごとに惣菜類だけへ絞り、
  商品別に集計した後で統合するため、メモリ使用量を抑えられる。
* 出力には実際の商品名・集計件数が含まれる。会社環境内だけで管理し、
  個人PC、Notion、GitHub等へ保存・共有しないこと。
"""

from __future__ import annotations

import gc
import re
from pathlib import Path

import pandas as pd


# =====================================================================
# 【分析条件】
# =====================================================================

ANALYSIS_START_DATE = pd.Timestamp("2024-01-01")
ANALYSIS_END_DATE = pd.Timestamp("2026-06-30")

DATE_COLUMN = "date"
PRODUCT_NAME_COLUMN = "name"
JICFS_LV4_CODE_COLUMN = "item_jicfs_lv4_code"
JICFS_LV4_NAME_COLUMN = "item_jicfs_lv4_name"
JICFS_LV6_CODE_COLUMN = "item_jicfs_lv6_code"
JICFS_LV6_NAME_COLUMN = "item_jicfs_lv6_name"

# 実データ上の表記が「惣菜」「惣菜類」のどちらでも抽出できるよう部分一致にする。
TARGET_LV4_NAME_KEYWORD = "惣菜"

# 一食完結型の種キーワード。出力を確認しながら追加・削除する。
COMPLETE_MEAL_KEYWORDS = (
    "弁当",
    "幕の内",
    "丼",
    "重",
    "御膳",
    "プレート",
    "うどん",
    "そば",
    "蕎麦",
    "ラーメン",
    "らーめん",
    "タンメン",
    "ちゃんぽん",
    "冷麺",
    "つけ麺",
    "焼そば",
    "焼きそば",
    "パスタ",
    "スパゲティ",
    "スパゲッティ",
    "ナポリタン",
    "ミートソース",
    "カレー",
    "オムライス",
    "ドリア",
    "ビビンバ",
    "チャーハン",
    "炒飯",
    "ピラフ",
    "リゾット",
    "雑炊",
    "おかゆ",
    "粥",
    "タコライス",
    "ガパオ",
    "ロコモコ",
)

# 一食完結型キーワードと同時に含まれる場合、機械判定せず目視確認する。
# 例: 「カレーおにぎり」「パスタサラダ」など。
REVIEW_KEYWORDS = (
    "おにぎり",
    "おむすび",
    "いなり",
    "手巻",
    "細巻",
    "サンド",
    "サラダ",
    "パン",
)

REQUIRED_COLUMNS = {
    DATE_COLUMN,
    PRODUCT_NAME_COLUMN,
    JICFS_LV4_CODE_COLUMN,
    JICFS_LV4_NAME_COLUMN,
    JICFS_LV6_CODE_COLUMN,
    JICFS_LV6_NAME_COLUMN,
}

STATUS_COMPLETE = "一食完結型候補"
STATUS_REVIEW = "要確認"
STATUS_UNMATCHED = "未抽出"


# =====================================================================
# 【ユーザー記入欄】S3読込テンプレートで data1～data5 を作成する
# =====================================================================
# この位置に、会社環境で用意されたS3読込コードを貼り付ける。
# 最終的に、JICFS Lv4・Lv6を含む各期間のDataFrameが次の5変数へ
# 入っていればよい。
#
# data1 = ...  # 2024年1～6月
# data2 = ...  # 2024年7～12月
# data3 = ...  # 2025年1～6月
# data4 = ...  # 2025年7～12月
# data5 = ...  # 2026年1～6月
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


def normalize_text(values: pd.Series) -> pd.Series:
    """商品名・カテゴリー名を照合しやすい表記へ統一する。"""
    return (
        values.astype("string")
        .fillna("")
        .str.normalize("NFKC")
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )


def normalize_jicfs_code(values: pd.Series) -> pd.Series:
    """JICFSコードを比較・出力用の文字列へ統一する。"""
    normalized = values.astype("string").fillna("").str.strip()
    return normalized.str.replace(r"\.0$", "", regex=True)


def matched_keywords(product_name: str, keywords: tuple[str, ...]) -> list[str]:
    """商品名へ部分一致したキーワードを、定義順で返す。"""
    return [keyword for keyword in keywords if keyword in product_name]


def aggregate_one_period(
    data: pd.DataFrame,
    source_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """1期間を惣菜類へ絞り、商品別集計と品質確認表を返す。"""
    require_columns(data, REQUIRED_COLUMNS, source_name)

    working = data.loc[:, sorted(REQUIRED_COLUMNS)].copy()
    input_rows = len(working)

    working[DATE_COLUMN] = pd.to_datetime(working[DATE_COLUMN], errors="coerce")
    valid_date_rows = int(working[DATE_COLUMN].notna().sum())
    in_period = working[DATE_COLUMN].between(
        ANALYSIS_START_DATE,
        ANALYSIS_END_DATE,
        inclusive="both",
    )
    working = working.loc[in_period].copy()
    in_period_rows = len(working)

    working[PRODUCT_NAME_COLUMN] = normalize_text(working[PRODUCT_NAME_COLUMN])
    working[JICFS_LV4_NAME_COLUMN] = normalize_text(
        working[JICFS_LV4_NAME_COLUMN]
    )
    working[JICFS_LV6_NAME_COLUMN] = normalize_text(
        working[JICFS_LV6_NAME_COLUMN]
    )
    working[JICFS_LV4_CODE_COLUMN] = normalize_jicfs_code(
        working[JICFS_LV4_CODE_COLUMN]
    )
    working[JICFS_LV6_CODE_COLUMN] = normalize_jicfs_code(
        working[JICFS_LV6_CODE_COLUMN]
    )

    deli_mask = working[JICFS_LV4_NAME_COLUMN].str.contains(
        TARGET_LV4_NAME_KEYWORD,
        regex=False,
        na=False,
    )
    working = working.loc[deli_mask].copy()
    deli_rows = len(working)

    valid_name_mask = working[PRODUCT_NAME_COLUMN].ne("")
    working = working.loc[valid_name_mask].copy()
    valid_name_rows = len(working)

    group_columns = [
        PRODUCT_NAME_COLUMN,
        JICFS_LV4_CODE_COLUMN,
        JICFS_LV4_NAME_COLUMN,
        JICFS_LV6_CODE_COLUMN,
        JICFS_LV6_NAME_COLUMN,
    ]
    aggregated = (
        working.groupby(group_columns, dropna=False, observed=True)
        .size()
        .rename("購買記録数")
        .reset_index()
    )

    actual_lv4_names = "｜".join(
        sorted(name for name in working[JICFS_LV4_NAME_COLUMN].unique() if name)
    )
    quality = pd.DataFrame(
        [
            {
                "入力元": source_name,
                "入力行数": input_rows,
                "日付有効行数": valid_date_rows,
                "分析期間内行数": in_period_rows,
                "Lv4惣菜類行数": deli_rows,
                "商品名有効行数": valid_name_rows,
                "商品別集計行数": len(aggregated),
                "確認されたLv4名称": actual_lv4_names,
            }
        ]
    )
    return aggregated, quality


def combine_period_aggregates(period_tables: list[pd.DataFrame]) -> pd.DataFrame:
    """期間別の商品集計を、全期間の商品一覧へ統合する。"""
    combined = pd.concat(period_tables, ignore_index=True)
    group_columns = [
        PRODUCT_NAME_COLUMN,
        JICFS_LV4_CODE_COLUMN,
        JICFS_LV4_NAME_COLUMN,
        JICFS_LV6_CODE_COLUMN,
        JICFS_LV6_NAME_COLUMN,
    ]
    return (
        combined.groupby(group_columns, dropna=False, observed=True)["購買記録数"]
        .sum()
        .reset_index()
        .sort_values(["購買記録数", PRODUCT_NAME_COLUMN], ascending=[False, True])
        .reset_index(drop=True)
    )


def classify_keyword_hits(products: pd.DataFrame) -> pd.DataFrame:
    """商品ごとのキーワード該当状況を付与する。"""
    result = products.copy()
    complete_matches = result[PRODUCT_NAME_COLUMN].map(
        lambda name: matched_keywords(name, COMPLETE_MEAL_KEYWORDS)
    )
    review_matches = result[PRODUCT_NAME_COLUMN].map(
        lambda name: matched_keywords(name, REVIEW_KEYWORDS)
    )

    result["一食完結型該当キーワード"] = complete_matches.map("｜".join)
    result["要確認該当キーワード"] = review_matches.map("｜".join)
    has_complete = complete_matches.map(bool)
    has_review = review_matches.map(bool)
    result["抽出結果"] = STATUS_UNMATCHED
    result.loc[has_complete & ~has_review, "抽出結果"] = STATUS_COMPLETE
    result.loc[has_complete & has_review, "抽出結果"] = STATUS_REVIEW
    return result


def build_keyword_summary(products: pd.DataFrame) -> pd.DataFrame:
    """一食完結型キーワードごとの該当規模と商品例をまとめる。"""
    rows: list[dict[str, object]] = []
    total_records = int(products["購買記録数"].sum())
    for keyword in COMPLETE_MEAL_KEYWORDS:
        matched = products.loc[
            products[PRODUCT_NAME_COLUMN].str.contains(
                re.escape(keyword),
                regex=True,
                na=False,
            )
        ].copy()
        matched = matched.sort_values("購買記録数", ascending=False)
        record_count = int(matched["購買記録数"].sum())
        examples = "｜".join(matched[PRODUCT_NAME_COLUMN].head(5).tolist())
        rows.append(
            {
                "キーワード": keyword,
                "該当ユニーク商品数": len(matched),
                "該当購買記録数": record_count,
                "惣菜類全体に占める割合（%）": (
                    record_count / total_records * 100 if total_records else 0.0
                ),
                "主な該当商品例": examples,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["該当購買記録数", "該当ユニーク商品数"],
        ascending=[False, False],
    )


def build_coverage_summary(products: pd.DataFrame) -> pd.DataFrame:
    """候補・要確認・未抽出の件数とカバー率をまとめる。"""
    total_products = len(products)
    total_records = int(products["購買記録数"].sum())
    rows: list[dict[str, object]] = []
    for status in (STATUS_COMPLETE, STATUS_REVIEW, STATUS_UNMATCHED):
        selected = products.loc[products["抽出結果"].eq(status)]
        product_count = len(selected)
        record_count = int(selected["購買記録数"].sum())
        rows.append(
            {
                "抽出結果": status,
                "ユニーク商品数": product_count,
                "商品名ベース構成比（%）": (
                    product_count / total_products * 100 if total_products else 0.0
                ),
                "購買記録数": record_count,
                "購買記録ベース構成比（%）": (
                    record_count / total_records * 100 if total_records else 0.0
                ),
            }
        )
    return pd.DataFrame(rows)


def build_lv6_summary(products: pd.DataFrame) -> pd.DataFrame:
    """Lv6カテゴリー別に、探索対象の規模と抽出状況を確認する。"""
    summary = (
        products.groupby(
            [JICFS_LV6_CODE_COLUMN, JICFS_LV6_NAME_COLUMN, "抽出結果"],
            dropna=False,
            observed=True,
        )
        .agg(
            ユニーク商品数=(PRODUCT_NAME_COLUMN, "size"),
            購買記録数=("購買記録数", "sum"),
        )
        .reset_index()
    )
    return summary.sort_values(
        ["購買記録数", JICFS_LV6_CODE_COLUMN, "抽出結果"],
        ascending=[False, True, True],
    )


def build_keyword_master() -> pd.DataFrame:
    """今回使用したキーワードを再現可能な形で保存する。"""
    rows = [
        {"種別": "一食完結型キーワード", "キーワード": keyword}
        for keyword in COMPLETE_MEAL_KEYWORDS
    ]
    rows.extend(
        {"種別": "要確認キーワード", "キーワード": keyword}
        for keyword in REVIEW_KEYWORDS
    )
    return pd.DataFrame(rows)


def save_csv(data: pd.DataFrame, path: Path) -> None:
    """Excelでも文字化けしにくいUTF-8 BOM付きCSVとして保存する。"""
    data.to_csv(path, index=False, encoding="utf-8-sig")


def run(dataframes: list[pd.DataFrame]) -> list[Path]:
    """5期間のデータを順に処理し、探索用ファイルを保存する。"""
    if len(dataframes) != 5:
        raise ValueError("data1～data5の5つのDataFrameを指定してください。")

    output_dir = Path(__file__).resolve().parent.parent / "Output"
    output_dir.mkdir(parents=True, exist_ok=True)

    period_tables: list[pd.DataFrame] = []
    quality_tables: list[pd.DataFrame] = []
    for index, data in enumerate(dataframes, start=1):
        source_name = f"data{index}"
        print(f"[{index}/5] {source_name} を集計しています...")
        period_table, quality_table = aggregate_one_period(data, source_name)
        period_tables.append(period_table)
        quality_tables.append(quality_table)
        del period_table, quality_table
        gc.collect()

    products = combine_period_aggregates(period_tables)
    del period_tables
    gc.collect()
    if products.empty:
        raise ValueError(
            "分析期間内に、Lv4名称へ「惣菜」を含む有効な商品がありません。"
            "JICFS Lv4列の内容を確認してください。"
        )

    products = classify_keyword_hits(products)
    keyword_summary = build_keyword_summary(products)
    coverage_summary = build_coverage_summary(products)
    lv6_summary = build_lv6_summary(products)
    keyword_master = build_keyword_master()

    quality = pd.concat(quality_tables, ignore_index=True)
    total_quality = pd.DataFrame(
        [
            {
                "入力元": "全期間統合後",
                "入力行数": quality["入力行数"].sum(),
                "日付有効行数": quality["日付有効行数"].sum(),
                "分析期間内行数": quality["分析期間内行数"].sum(),
                "Lv4惣菜類行数": quality["Lv4惣菜類行数"].sum(),
                "商品名有効行数": quality["商品名有効行数"].sum(),
                "商品別集計行数": len(products),
                "確認されたLv4名称": "｜".join(
                    sorted(
                        {
                            name
                            for names in quality["確認されたLv4名称"]
                            for name in str(names).split("｜")
                            if name and name != "nan"
                        }
                    )
                ),
            }
        ]
    )
    quality = pd.concat([quality, total_quality], ignore_index=True)

    candidate_products = products.loc[
        products["抽出結果"].eq(STATUS_COMPLETE)
    ].copy()
    review_products = products.loc[products["抽出結果"].eq(STATUS_REVIEW)].copy()
    unmatched_products = products.loc[
        products["抽出結果"].eq(STATUS_UNMATCHED)
    ].copy()

    output_items = [
        ("01_Lv4惣菜類の商品一覧.csv", products),
        ("02_一食完結型キーワード別集計.csv", keyword_summary),
        ("03_一食完結型候補商品.csv", candidate_products),
        ("04_要確認商品.csv", review_products),
        ("05_未抽出商品_購買記録数順.csv", unmatched_products),
        ("06_キーワード抽出カバー率.csv", coverage_summary),
        ("07_Lv6カテゴリー別集計.csv", lv6_summary),
        ("08_データ品質確認.csv", quality),
        ("09_使用キーワード一覧.csv", keyword_master),
    ]
    output_paths: list[Path] = []
    for filename, table in output_items:
        path = output_dir / filename
        save_csv(table, path)
        output_paths.append(path)

    print("\nNo19のキーワード探索が完了しました。")
    print(
        f"Lv4惣菜類: {len(products):,}商品 / "
        f"{int(products['購買記録数'].sum()):,}件"
    )
    for row in coverage_summary.itertuples(index=False):
        print(
            f"{row[0]}: {int(row[1]):,}商品 / "
            f"{int(row[3]):,}件"
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
    run([globals()[name] for name in data_names])


if __name__ == "__main__":
    main()
