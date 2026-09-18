"""10属性について食事補完型割合の群間差と購買指数の相関を確認する。

分析対象
--------
セブンイレブンの「栄養バランスを調整したい」ニーズについて、
男女×20代～60代の10属性を個別に分析する。

各属性で行う処理
----------------
1. 「対応」商品の購買経験群・購買未経験群を定義する。
2. 購買経験群を全員残し、購買未経験群から同数かつ利用日数が近い
   ユーザーを抽出する。
3. JICFS Lv4「惣菜類」の購買記録を「一食完結型」「食事補完型」へ
   分類する。対応商品の購買記録も主分析に含める。
4. 両群の食事補完型購買記録割合と、次の群間差を算出する。

   群間差 = 購買未経験群の食事補完型割合
            - 購買経験群の食事補完型割合

5. No10の属性別対応商品群購買指数と結合し、10属性間の相関を確認する。

入力
----
このスクリプト内で、次の2種類のS3読込処理を設定する。

* ユーザー抽出用データ: date, user_id, user_gender,
  user_age_att_layer を含む5期間分DataFrame
* JICFS分析用データ: date, user_id, name,
  item_jicfs_lv4_code, item_jicfs_lv4_name を含む5期間分DataFrame

また、同じ親フォルダ配下に次の既存結果が必要である。

* No4_extract_confirmed_products_seven/Output/栄養バランス/
* No10_group_purchase_index_seven/Output/セブン_対応商品群購買指数.csv

出力
----
No25のOutputへ、必要な3ファイルだけを保存する。

* 01_属性別分析結果.csv
* 02_相関分析結果.csv
* 03_属性間傾向_散布図_統計なし.png
* 04_属性間相関_散布図_統計あり.png

注意
----
* Zaimの1行を1商品の購買記録として数える。receipt_keyでは重複排除しない。
* 対応商品の購買記録は除外しない。
* ユーザーIDを含む中間表は保存しない。
* 認証情報や実データを、このファイルやGitHubへ保存しない。
"""

from __future__ import annotations

import gc
import re
from bisect import bisect_left
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# =====================================================================
# 分析条件
# =====================================================================

ANALYSIS_START_DATE = pd.Timestamp("2024-01-01")
ANALYSIS_END_DATE = pd.Timestamp("2026-06-30")

DATE_COLUMN = "date"
USER_ID_COLUMN = "user_id"
GENDER_COLUMN = "user_gender"
AGE_COLUMN = "user_age_att_layer"
PRODUCT_NAME_COLUMN = "name"
JICFS_LV4_CODE_COLUMN = "item_jicfs_lv4_code"
JICFS_LV4_NAME_COLUMN = "item_jicfs_lv4_name"

GENDERS = ("男性", "女性")
AGES = ("20代", "30代", "40代", "50代", "60代")
ATTRIBUTES = tuple((gender, age) for gender in GENDERS for age in AGES)

EXPERIENCED_GROUP = "購買経験群"
UNEXPERIENCED_GROUP = "購買未経験群"
GROUP_ORDER = (EXPERIENCED_GROUP, UNEXPERIENCED_GROUP)

COMPLETE_ROLE = "一食完結型"
SUPPLEMENT_ROLE = "食事補完型"
TARGET_LV4_NAME_KEYWORD = "惣菜"

SOURCE_PRODUCT_PROJECT_DIR_NAME = "No4_extract_confirmed_products_seven"
SOURCE_HEALTH_NEED_DIR_NAME = "栄養バランス"
SOURCE_PRODUCT_MAPPING_FILENAME = "product_file_mapping.csv"

SOURCE_INDEX_PROJECT_DIR_NAME = "No10_group_purchase_index_seven"
SOURCE_INDEX_FILENAME = "セブン_対応商品群購買指数.csv"
HEALTH_NEED_COLUMN = "健康ニーズ"
TARGET_HEALTH_NEED = "栄養バランス"

RANDOM_SEED = 20260918

USER_REQUIRED_COLUMNS = {
    DATE_COLUMN,
    USER_ID_COLUMN,
    GENDER_COLUMN,
    AGE_COLUMN,
}

JICFS_REQUIRED_COLUMNS = {
    DATE_COLUMN,
    USER_ID_COLUMN,
    PRODUCT_NAME_COLUMN,
    JICFS_LV4_CODE_COLUMN,
    JICFS_LV4_NAME_COLUMN,
}

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
    "冷し中華",
    "冷やし中華",
    "そうめん",
    "素麺",
    "担々麺",
    "担担麺",
    "麺",
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
    "牛めし",
    "鶏そぼろごはん",
    "鍋",
)

# 一食完結型キーワードに該当しても、次の表現を含む場合は食事補完型へ戻す。
SUPPLEMENT_OVERRIDE_KEYWORDS = (
    "サラダ",
    "おにぎり",
    "おむすび",
    "いなり",
    "手巻",
    "細巻",
    "サンド",
    "パン",
)

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


# =====================================================================
# ユーザー記入欄A: ユーザー抽出用S3データを読み込む
# =====================================================================

def load_user_source_dataframes() -> list[pd.DataFrame]:
    """ユーザー抽出用の5期間分DataFrameを返す。

    この関数内へ、これまで利用してきたS3読込テンプレートを貼り付け、
    data1～data5を作成する。必要列はUSER_REQUIRED_COLUMNSを参照する。
    認証情報はスクリプトへ直接記載しないこと。
    """

    # ---------------------------------------------------------------
    # ここにユーザー抽出用S3読込テンプレートを貼り付ける。
    #
    # data1 = ...  # 2024年1～6月
    # data2 = ...  # 2024年7～12月
    # data3 = ...  # 2025年1～6月
    # data4 = ...  # 2025年7～12月
    # data5 = ...  # 2026年1～6月
    # ---------------------------------------------------------------

    try:
        dataframes = [data1, data2, data3, data4, data5]
    except NameError as error:
        raise RuntimeError(
            "load_user_source_dataframes()内へ、ユーザー抽出用の"
            "data1～data5を作るS3読込コードを設定してください。"
        ) from error
    return dataframes


# =====================================================================
# ユーザー記入欄B: JICFS分析用S3データを読み込む
# =====================================================================

def load_jicfs_source_dataframes() -> list[pd.DataFrame]:
    """JICFS Lv4を含む5期間分DataFrameを返す。

    この関数内へ、最近作成したJICFS列付きS3データの読込テンプレートを
    貼り付け、data1～data5を作成する。必要列は
    JICFS_REQUIRED_COLUMNSを参照する。
    認証情報はスクリプトへ直接記載しないこと。
    """

    # ---------------------------------------------------------------
    # ここにJICFS分析用S3読込テンプレートを貼り付ける。
    #
    # data1 = ...  # 2024年1～6月
    # data2 = ...  # 2024年7～12月
    # data3 = ...  # 2025年1～6月
    # data4 = ...  # 2025年7～12月
    # data5 = ...  # 2026年1～6月
    # ---------------------------------------------------------------

    try:
        dataframes = [data1, data2, data3, data4, data5]
    except NameError as error:
        raise RuntimeError(
            "load_jicfs_source_dataframes()内へ、JICFS分析用の"
            "data1～data5を作るS3読込コードを設定してください。"
        ) from error
    return dataframes


# =====================================================================
# 共通処理
# =====================================================================

def require_columns(
    data: pd.DataFrame,
    required_columns: set[str],
    source_name: str,
) -> None:
    missing = sorted(required_columns - set(data.columns))
    if missing:
        raise ValueError(f"{source_name} に必要な列がありません: {missing}")


def normalize_identifier(values: pd.Series) -> pd.Series:
    normalized = values.astype("string").str.strip()
    invalid = (
        values.isna()
        | normalized.isna()
        | normalized.eq("")
        | normalized.str.lower().isin({"nan", "none", "null"})
        | normalized.str.contains("不明", na=False)
    )
    return normalized.str.replace(r"\.0$", "", regex=True).mask(invalid)


def normalize_text(values: pd.Series) -> pd.Series:
    return (
        values.astype("string")
        .fillna("")
        .str.normalize("NFKC")
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )


def normalize_jicfs_code(values: pd.Series) -> pd.Series:
    return (
        values.astype("string")
        .fillna("")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )


def attribute_label(gender: str, age: str) -> str:
    return f"{gender}・{age}"


def in_analysis_period(datetimes: pd.Series) -> pd.Series:
    return datetimes.between(
        ANALYSIS_START_DATE,
        ANALYSIS_END_DATE + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1),
        inclusive="both",
    )


def build_literal_pattern(keywords: tuple[str, ...]) -> str:
    return "|".join(re.escape(keyword) for keyword in keywords)


COMPLETE_PATTERN = build_literal_pattern(COMPLETE_MEAL_KEYWORDS)
SUPPLEMENT_OVERRIDE_PATTERN = build_literal_pattern(
    SUPPLEMENT_OVERRIDE_KEYWORDS
)


def classify_meal_role(names: pd.Series) -> pd.Series:
    """No20と同じ規則で、惣菜類を二つの食事上の役割へ分類する。"""
    keyword_hit = names.str.contains(COMPLETE_PATTERN, regex=True, na=False)
    override_hit = names.str.contains(
        SUPPLEMENT_OVERRIDE_PATTERN,
        regex=True,
        na=False,
    )
    complete = keyword_hit & ~override_hit
    roles = pd.Series(SUPPLEMENT_ROLE, index=names.index, dtype="string")
    roles.loc[complete] = COMPLETE_ROLE
    return roles


# =====================================================================
# 1. 属性別のセブン利用日数を作る
# =====================================================================

def prepare_user_source_chunk(
    data: pd.DataFrame,
    source_name: str,
) -> pd.DataFrame:
    require_columns(data, USER_REQUIRED_COLUMNS, source_name)
    selected = data.loc[:, sorted(USER_REQUIRED_COLUMNS)].copy()
    selected["_date"] = pd.to_datetime(selected[DATE_COLUMN], errors="coerce")
    selected["_day"] = selected["_date"].dt.normalize()
    selected["_user_id"] = normalize_identifier(selected[USER_ID_COLUMN])
    selected["_gender"] = normalize_text(selected[GENDER_COLUMN])
    selected["_age"] = normalize_text(selected[AGE_COLUMN])

    eligible = (
        in_analysis_period(selected["_date"])
        & selected["_user_id"].notna()
        & selected["_gender"].isin(GENDERS)
        & selected["_age"].isin(AGES)
    )
    # 同じユーザー・属性・日付に複数商品があっても、利用日は1日とする。
    prepared = selected.loc[
        eligible,
        ["_user_id", "_gender", "_age", "_day"],
    ].drop_duplicates()
    print(
        f"{source_name}: 入力={len(data):,}行 / "
        f"有効な属性別利用日={len(prepared):,}行"
    )
    return prepared


def build_attribute_usage_days(
    dataframes: list[pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(dataframes) != 5:
        raise ValueError("ユーザー抽出用データはdata1～data5の5つが必要です。")

    compact_chunks: list[pd.DataFrame] = []
    for number, data in enumerate(dataframes, start=1):
        compact_chunks.append(
            prepare_user_source_chunk(data, f"user_data{number}")
        )

    compact = pd.concat(
        compact_chunks,
        ignore_index=True,
        sort=False,
        copy=False,
    ).drop_duplicates()
    compact_chunks.clear()
    dataframes.clear()
    gc.collect()

    # JICFS側には性別・年代がないため、ユーザーIDと購買日の組合せから
    # その日の属性を引ける対応表を残す。同じユーザー・同じ日に複数の
    # 属性が記録されている不整合キーは、誤った属性付与を避けるため除外する。
    attribute_counts = (
        compact.groupby(["_user_id", "_day"], observed=True)
        .size()
        .reset_index(name="属性候補数")
    )
    valid_attribute_keys = attribute_counts.loc[
        attribute_counts["属性候補数"].eq(1),
        ["_user_id", "_day"],
    ]
    user_day_attributes = compact.merge(
        valid_attribute_keys,
        on=["_user_id", "_day"],
        how="inner",
        validate="one_to_one",
    ).rename(columns={"_gender": "性別", "_age": "年代"})

    ambiguous_keys = len(attribute_counts) - len(valid_attribute_keys)
    if ambiguous_keys:
        print(
            "注意: 同一ユーザー・同一日に複数属性があるため除外したキー="
            f"{ambiguous_keys:,}件"
        )

    usage_days = (
        user_day_attributes.groupby(
            ["性別", "年代", "_user_id"],
            sort=False,
            observed=True,
        )["_day"]
        .nunique()
        .reset_index(name="利用日数")
        .rename(columns={"性別": "_gender", "年代": "_age"})
    )
    del compact
    gc.collect()
    return usage_days, user_day_attributes


# =====================================================================
# 2. No4の商品別CSVから属性別の購買経験ユーザーを取得する
# =====================================================================

def read_product_mapping(mapping_path: Path) -> pd.DataFrame:
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
    return mapping


def collect_experienced_users_by_attribute(
    product_source_dir: Path,
) -> dict[tuple[str, str], set[str]]:
    experienced = {attribute: set() for attribute in ATTRIBUTES}
    mapping = read_product_mapping(
        product_source_dir / SOURCE_PRODUCT_MAPPING_FILENAME
    )

    for _, row in mapping.iterrows():
        number = str(row["商品番号"]).strip().zfill(3)
        product_path = product_source_dir / str(row["出力ファイル名"]).strip()
        if not product_path.exists():
            raise FileNotFoundError(
                f"商品{number}のCSVが見つかりません: {product_path}"
            )

        product_data = pd.read_csv(
            product_path,
            usecols=lambda column: column in USER_REQUIRED_COLUMNS,
            encoding="utf-8-sig",
            low_memory=False,
        )
        require_columns(product_data, USER_REQUIRED_COLUMNS, str(product_path))
        product_data["_date"] = pd.to_datetime(
            product_data[DATE_COLUMN], errors="coerce"
        )
        product_data["_user_id"] = normalize_identifier(
            product_data[USER_ID_COLUMN]
        )
        product_data["_gender"] = normalize_text(
            product_data[GENDER_COLUMN]
        )
        product_data["_age"] = normalize_text(product_data[AGE_COLUMN])
        eligible = (
            in_analysis_period(product_data["_date"])
            & product_data["_user_id"].notna()
            & product_data["_gender"].isin(GENDERS)
            & product_data["_age"].isin(AGES)
        )
        valid = product_data.loc[
            eligible,
            ["_user_id", "_gender", "_age"],
        ].drop_duplicates()
        for (gender, age), group_data in valid.groupby(
            ["_gender", "_age"], observed=True
        ):
            experienced[(str(gender), str(age))].update(
                group_data["_user_id"].astype(str)
            )

        print(f"商品{number}: 属性が有効な購買記録={int(eligible.sum()):,}行")

    return experienced


# =====================================================================
# 3. 各属性で購買未経験群の人数・利用日数を揃える
# =====================================================================

def nearest_available_day(
    target_day: int,
    active_days: list[int],
    rng: np.random.Generator,
) -> int:
    if not active_days:
        raise RuntimeError("抽出可能な購買未経験群ユーザーが不足しています。")
    position = bisect_left(active_days, target_day)
    candidates: list[int] = []
    if position < len(active_days):
        candidates.append(active_days[position])
    if position > 0:
        candidates.append(active_days[position - 1])
    minimum_distance = min(abs(day - target_day) for day in candidates)
    nearest = [
        day for day in candidates if abs(day - target_day) == minimum_distance
    ]
    if len(nearest) == 1:
        return nearest[0]
    return int(rng.choice(nearest))


def balance_one_attribute(
    usage_data: pd.DataFrame,
    experienced_user_ids: set[str],
    random_seed: int,
    label: str,
) -> pd.DataFrame:
    all_user_ids = set(usage_data["_user_id"].astype(str))
    experienced_ids = all_user_ids & experienced_user_ids
    unexperienced_ids = all_user_ids - experienced_ids

    if not experienced_ids:
        raise ValueError(f"{label}: 購買経験群に該当するユーザーがいません。")
    if len(unexperienced_ids) < len(experienced_ids):
        raise ValueError(
            f"{label}: 購買未経験群が購買経験群より少なく、同数抽出できません。"
        )

    experienced = usage_data.loc[
        usage_data["_user_id"].isin(experienced_ids)
    ].copy()
    unexperienced = usage_data.loc[
        usage_data["_user_id"].isin(unexperienced_ids)
    ].copy()

    rng = np.random.default_rng(random_seed)
    candidate_buckets: dict[int, list[int]] = {}
    for usage_day, indices in unexperienced.groupby("利用日数").groups.items():
        shuffled = np.asarray(list(indices), dtype=object)
        rng.shuffle(shuffled)
        candidate_buckets[int(usage_day)] = shuffled.tolist()
    active_days = sorted(candidate_buckets)

    selected_indices: list[object] = []
    target_rows = experienced.sort_values(
        ["利用日数", "_user_id"],
        ascending=[False, True],
    )
    for _, target in target_rows.iterrows():
        target_day = int(target["利用日数"])
        selected_day = nearest_available_day(target_day, active_days, rng)
        selected_index = candidate_buckets[selected_day].pop()
        selected_indices.append(selected_index)
        if not candidate_buckets[selected_day]:
            del candidate_buckets[selected_day]
            active_days.pop(bisect_left(active_days, selected_day))

    selected_unexperienced = unexperienced.loc[selected_indices].copy()
    experienced["群"] = EXPERIENCED_GROUP
    selected_unexperienced["群"] = UNEXPERIENCED_GROUP
    selected = pd.concat(
        [experienced, selected_unexperienced],
        ignore_index=True,
        sort=False,
    )

    if selected["_user_id"].duplicated().any():
        raise RuntimeError(f"{label}: 条件調整後ユーザーに重複があります。")

    print(
        f"{label}: 条件調整後 "
        f"購買経験群={len(experienced):,}人 / "
        f"購買未経験群={len(selected_unexperienced):,}人 / "
        f"平均利用日数={experienced['利用日数'].mean():.2f}日・"
        f"{selected_unexperienced['利用日数'].mean():.2f}日"
    )
    return selected.loc[:, ["_user_id", "群", "利用日数"]]


def build_all_attribute_cohorts(
    usage_days: pd.DataFrame,
    experienced_by_attribute: dict[tuple[str, str], set[str]],
) -> pd.DataFrame:
    cohorts: list[pd.DataFrame] = []
    for number, (gender, age) in enumerate(ATTRIBUTES):
        label = attribute_label(gender, age)
        attribute_usage = usage_days.loc[
            usage_days["_gender"].eq(gender)
            & usage_days["_age"].eq(age)
        ].copy()
        selected = balance_one_attribute(
            usage_data=attribute_usage,
            experienced_user_ids=experienced_by_attribute[(gender, age)],
            random_seed=RANDOM_SEED + number,
            label=label,
        )
        selected["性別"] = gender
        selected["年代"] = age
        selected["属性"] = label
        cohorts.append(selected)

    result = pd.concat(cohorts, ignore_index=True, sort=False)
    return result.loc[:, ["_user_id", "性別", "年代", "属性", "群", "利用日数"]]


def build_cohort_day_lookup(
    user_day_attributes: pd.DataFrame,
    cohorts: pd.DataFrame,
) -> pd.DataFrame:
    """条件調整後ユーザーについて、利用日ごとの属性・群を対応づける。"""
    cohort_keys = cohorts.loc[
        :, ["_user_id", "性別", "年代", "属性", "群"]
    ].copy()
    lookup = user_day_attributes.merge(
        cohort_keys,
        on=["_user_id", "性別", "年代"],
        how="inner",
        validate="many_to_one",
    )
    duplicated = lookup.duplicated(["_user_id", "_day"], keep=False)
    if duplicated.any():
        raise RuntimeError(
            "条件調整後ユーザーの日付別属性対応に重複があります: "
            f"{int(duplicated.sum())}行"
        )
    return lookup.loc[:, ["_user_id", "_day", "性別", "年代", "属性", "群"]]


# =====================================================================
# 4. JICFSデータを属性・群・食事上の役割別に集計する
# =====================================================================

def prepare_jicfs_chunk(
    data: pd.DataFrame,
    source_name: str,
    cohort_day_lookup: pd.DataFrame,
) -> pd.DataFrame:
    require_columns(data, JICFS_REQUIRED_COLUMNS, source_name)
    selected = data.loc[:, sorted(JICFS_REQUIRED_COLUMNS)].copy()
    selected["_date"] = pd.to_datetime(selected[DATE_COLUMN], errors="coerce")
    selected["_day"] = selected["_date"].dt.normalize()
    selected["_user_id"] = normalize_identifier(selected[USER_ID_COLUMN])
    selected["_name"] = normalize_text(selected[PRODUCT_NAME_COLUMN])
    selected["_lv4_code"] = normalize_jicfs_code(
        selected[JICFS_LV4_CODE_COLUMN]
    )
    selected["_lv4_name"] = normalize_text(selected[JICFS_LV4_NAME_COLUMN])

    eligible = (
        in_analysis_period(selected["_date"])
        & selected["_user_id"].notna()
        & selected["_name"].ne("")
        & selected["_lv4_name"].str.contains(
            TARGET_LV4_NAME_KEYWORD,
            regex=False,
            na=False,
        )
    )
    prepared = selected.loc[
        eligible,
        ["_user_id", "_day", "_name"],
    ].merge(
        cohort_day_lookup,
        on=["_user_id", "_day"],
        how="inner",
        validate="many_to_one",
    )
    prepared["食事形態"] = classify_meal_role(prepared["_name"])
    print(
        f"{source_name}: 入力={len(data):,}行 / "
        f"条件調整後ユーザーの惣菜類={len(prepared):,}行"
    )
    return prepared.loc[:, ["属性", "群", "食事形態"]]


def aggregate_jicfs_records(
    dataframes: list[pd.DataFrame],
    cohort_day_lookup: pd.DataFrame,
) -> pd.DataFrame:
    if len(dataframes) != 5:
        raise ValueError("JICFS分析用データはdata1～data5の5つが必要です。")

    count_tables: list[pd.DataFrame] = []
    for number, data in enumerate(dataframes, start=1):
        prepared = prepare_jicfs_chunk(
            data=data,
            source_name=f"jicfs_data{number}",
            cohort_day_lookup=cohort_day_lookup,
        )
        counts = (
            prepared.groupby(
                ["属性", "群", "食事形態"],
                observed=True,
            )
            .size()
            .reset_index(name="購買記録数")
        )
        count_tables.append(counts)
        del prepared
        gc.collect()

    dataframes.clear()
    combined = pd.concat(count_tables, ignore_index=True, sort=False)
    result = (
        combined.groupby(
            ["属性", "群", "食事形態"],
            observed=True,
            as_index=False,
        )["購買記録数"]
        .sum()
    )
    return result


# =====================================================================
# 5. 属性別の割合・差分・購買指数をまとめる
# =====================================================================

def read_group_purchase_index(index_path: Path) -> dict[str, float]:
    if not index_path.exists():
        raise FileNotFoundError(f"No10の購買指数表が見つかりません: {index_path}")
    table = pd.read_csv(index_path, dtype=str, encoding="utf-8-sig")
    require_columns(table, {HEALTH_NEED_COLUMN}, str(index_path))
    target = table.loc[table[HEALTH_NEED_COLUMN].eq(TARGET_HEALTH_NEED)]
    if len(target) != 1:
        raise ValueError(
            f"No10の表で健康ニーズ『{TARGET_HEALTH_NEED}』を1行に特定できません。"
        )

    result: dict[str, float] = {}
    for gender, age in ATTRIBUTES:
        label = attribute_label(gender, age)
        if label not in table.columns:
            raise ValueError(f"No10の表に属性列がありません: {label}")
        value = pd.to_numeric(target.iloc[0][label], errors="coerce")
        result[label] = float(value) if pd.notna(value) else np.nan
    return result


def build_attribute_result_table(
    role_counts: pd.DataFrame,
    purchase_index: dict[str, float],
) -> pd.DataFrame:
    count_lookup = role_counts.set_index(["属性", "群", "食事形態"])[
        "購買記録数"
    ]
    rows: list[dict[str, object]] = []

    for gender, age in ATTRIBUTES:
        label = attribute_label(gender, age)
        shares: dict[str, float] = {}
        for group in GROUP_ORDER:
            complete_count = int(
                count_lookup.get((label, group, COMPLETE_ROLE), 0)
            )
            supplement_count = int(
                count_lookup.get((label, group, SUPPLEMENT_ROLE), 0)
            )
            total = complete_count + supplement_count
            shares[group] = supplement_count / total * 100 if total else np.nan

        gap = shares[UNEXPERIENCED_GROUP] - shares[EXPERIENCED_GROUP]
        rows.append(
            {
                "属性": label,
                "性別": gender,
                "年代": age,
                "購買経験群_食事補完型購買記録割合（%）": shares[
                    EXPERIENCED_GROUP
                ],
                "購買未経験群_食事補完型購買記録割合（%）": shares[
                    UNEXPERIENCED_GROUP
                ],
                "群間差_未経験群－経験群（ポイント）": gap,
                "対応商品群購買指数": purchase_index[label],
            }
        )

    return pd.DataFrame(rows)


def calculate_correlations(result_table: pd.DataFrame) -> pd.DataFrame:
    x_column = "群間差_未経験群－経験群（ポイント）"
    y_column = "対応商品群購買指数"
    valid = result_table.loc[:, [x_column, y_column]].dropna()
    if len(valid) < 3:
        raise ValueError("相関分析に使用できる属性が3件未満です。")

    x = valid[x_column].astype(float)
    y = valid[y_column].astype(float)
    spearman_r = float(x.rank(method="average").corr(y.rank(method="average")))
    pearson_r = float(x.corr(y))
    spearman_p = np.nan
    pearson_p = np.nan
    try:
        from scipy.stats import pearsonr, spearmanr

        spearman_result = spearmanr(x, y, nan_policy="omit")
        pearson_result = pearsonr(x, y)
        spearman_r = float(
            getattr(spearman_result, "statistic", spearman_result[0])
        )
        spearman_p = float(
            getattr(spearman_result, "pvalue", spearman_result[1])
        )
        pearson_r = float(getattr(pearson_result, "statistic", pearson_result[0]))
        pearson_p = float(getattr(pearson_result, "pvalue", pearson_result[1]))
    except ImportError:
        print(
            "scipyがないため、相関係数のみ保存します。p値は空欄になります。"
        )

    return pd.DataFrame(
        [
            {
                "位置づけ": "主分析",
                "相関手法": "スピアマンの順位相関",
                "属性数": len(valid),
                "相関係数": spearman_r,
                "p値": spearman_p,
                "想定方向": "負",
            },
            {
                "位置づけ": "補足",
                "相関手法": "ピアソンの積率相関",
                "属性数": len(valid),
                "相関係数": pearson_r,
                "p値": pearson_p,
                "想定方向": "負",
            },
        ]
    )


# =====================================================================
# 6. 散布図
# =====================================================================

def configure_plot_font() -> bool:
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


def english_attribute_label(gender: str, age: str) -> str:
    prefix = "M" if gender == "男性" else "F"
    return f"{prefix}{age.replace('代', '')}"


def save_scatter_plot(
    result_table: pd.DataFrame,
    correlation_table: pd.DataFrame,
    output_path: Path,
    show_statistics: bool,
) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise RuntimeError(
            "散布図の作成にはmatplotlibが必要です。"
        ) from error

    use_japanese = configure_plot_font()
    x_column = "群間差_未経験群－経験群（ポイント）"
    y_column = "対応商品群購買指数"
    valid = result_table.dropna(subset=[x_column, y_column]).copy()
    if valid.empty:
        raise ValueError("散布図に使用できる属性がありません。")

    colors = {"男性": "#4E79A7", "女性": "#E07A8D"}
    fig, ax = plt.subplots(figsize=(9.2, 7.0))
    for gender in GENDERS:
        data = valid.loc[valid["性別"].eq(gender)]
        legend_label = gender if use_japanese else (
            "Male" if gender == "男性" else "Female"
        )
        ax.scatter(
            data[x_column],
            data[y_column],
            s=180,
            color=colors[gender],
            edgecolor="#333333",
            linewidth=0.8,
            alpha=0.92,
            label=legend_label,
            zorder=3,
        )
        for _, row in data.iterrows():
            label = (
                str(row["属性"])
                if use_japanese
                else english_attribute_label(str(row["性別"]), str(row["年代"]))
            )
            ax.annotate(
                label,
                (float(row[x_column]), float(row[y_column])),
                xytext=(7, 7),
                textcoords="offset points",
                fontsize=14,
                fontweight="bold",
            )

    regression_text = ""
    if valid[x_column].nunique() >= 2:
        slope, intercept = np.polyfit(
            valid[x_column].astype(float),
            valid[y_column].astype(float),
            1,
        )
        x_line = np.linspace(
            float(valid[x_column].min()),
            float(valid[x_column].max()),
            100,
        )
        ax.plot(
            x_line,
            slope * x_line + intercept,
            color="#555555",
            linestyle="--",
            linewidth=1.4,
            zorder=2,
        )
        sign = "+" if intercept >= 0 else "−"
        regression_text = (
            f"y = {slope:.3f}x {sign} {abs(intercept):.3f}"
        )

    annotation_lines: list[str] = []
    if show_statistics:
        spearman = correlation_table.loc[
            correlation_table["相関手法"].eq("スピアマンの順位相関")
        ].iloc[0]
        annotation_lines.append(
            f"Spearman ρ = {float(spearman['相関係数']):.3f}"
        )
        if pd.notna(spearman["p値"]):
            annotation_lines.append(f"p = {float(spearman['p値']):.3f}")
    if regression_text:
        equation_label = "回帰式" if use_japanese else "Linear fit"
        annotation_lines.append(f"{equation_label}: {regression_text}")

    ax.text(
        0.03,
        0.97,
        "\n".join(annotation_lines),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=13,
        bbox={
            "boxstyle": "round,pad=0.4",
            "facecolor": "white",
            "edgecolor": "#888888",
            "alpha": 0.9,
        },
    )

    if use_japanese:
        title = "食事補完型割合の群間差と対応商品群購買指数"
        x_label = "食事補完型購買記録割合の群間差（未経験群－経験群、ポイント）"
        y_label = "対応商品群購買指数"
    else:
        title = "Meal-role gap and purchase index across attributes"
        x_label = "Gap in meal-complement share (nonbuyer - buyer, points)"
        y_label = "Target-product group purchase index"

    ax.set_title(title, fontsize=17, fontweight="bold", pad=16)
    ax.set_xlabel(x_label, fontsize=13, fontweight="bold")
    ax.set_ylabel(y_label, fontsize=13, fontweight="bold")
    ax.set_xlim(1.5, 11.5)
    ax.tick_params(axis="both", labelsize=15, width=1.4)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_linewidth(1.3)
    ax.spines["bottom"].set_linewidth(1.3)
    ax.grid(color="#D8D8D8", linewidth=0.8, alpha=0.65)
    ax.legend(frameon=False, fontsize=13)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# =====================================================================
# 実行
# =====================================================================

def run(
    user_dataframes: list[pd.DataFrame],
    jicfs_data_loader,
    product_source_dir: Optional[Path] = None,
    purchase_index_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> tuple[Path, Path, Path, Path]:
    project_dir = Path(__file__).resolve().parents[1]
    workspace_dir = project_dir.parent
    product_source_dir = product_source_dir or (
        workspace_dir
        / SOURCE_PRODUCT_PROJECT_DIR_NAME
        / "Output"
        / SOURCE_HEALTH_NEED_DIR_NAME
    )
    purchase_index_path = purchase_index_path or (
        workspace_dir
        / SOURCE_INDEX_PROJECT_DIR_NAME
        / "Output"
        / SOURCE_INDEX_FILENAME
    )
    output_dir = output_dir or project_dir / "Output"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\n[1/5] 属性別のセブン利用日数と日付別属性対応を作成します。")
    usage_days, user_day_attributes = build_attribute_usage_days(user_dataframes)
    del user_dataframes
    gc.collect()

    print("\n[2/5] No4の商品別CSVから属性別購買経験ユーザーを取得します。")
    experienced_by_attribute = collect_experienced_users_by_attribute(
        product_source_dir
    )

    print("\n[3/5] 10属性それぞれで人数と利用日数を揃えます。")
    cohorts = build_all_attribute_cohorts(
        usage_days=usage_days,
        experienced_by_attribute=experienced_by_attribute,
    )
    del usage_days, experienced_by_attribute
    gc.collect()

    cohort_day_lookup = build_cohort_day_lookup(
        user_day_attributes=user_day_attributes,
        cohorts=cohorts,
    )
    del user_day_attributes, cohorts
    gc.collect()

    print("\n[4/5] JICFS分析用データを読み込み、食事上の役割を集計します。")
    jicfs_dataframes = jicfs_data_loader()
    role_counts = aggregate_jicfs_records(
        dataframes=jicfs_dataframes,
        cohort_day_lookup=cohort_day_lookup,
    )
    del jicfs_dataframes, cohort_day_lookup
    gc.collect()

    print("\n[5/5] 属性別結果、相関分析、散布図を保存します。")
    purchase_index = read_group_purchase_index(purchase_index_path)
    result_table = build_attribute_result_table(role_counts, purchase_index)
    correlation_table = calculate_correlations(result_table)

    result_path = output_dir / "01_属性別分析結果.csv"
    correlation_path = output_dir / "02_相関分析結果.csv"
    figure_without_statistics_path = (
        output_dir / "03_属性間傾向_散布図_統計なし.png"
    )
    figure_with_statistics_path = (
        output_dir / "04_属性間相関_散布図_統計あり.png"
    )

    result_table.to_csv(
        result_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
    )
    correlation_table.to_csv(
        correlation_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
    )
    save_scatter_plot(
        result_table,
        correlation_table,
        figure_without_statistics_path,
        show_statistics=False,
    )
    save_scatter_plot(
        result_table,
        correlation_table,
        figure_with_statistics_path,
        show_statistics=True,
    )

    print("\nNo25の属性横断相関分析が完了しました。")
    print(f"属性別結果: {result_path}")
    print(f"相関結果:   {correlation_path}")
    print(f"散布図（統計なし）: {figure_without_statistics_path}")
    print(f"散布図（統計あり）: {figure_with_statistics_path}")
    return (
        result_path,
        correlation_path,
        figure_without_statistics_path,
        figure_with_statistics_path,
    )


def main() -> None:
    # まずユーザー抽出用データだけを読み、処理後に解放する。
    user_dataframes = load_user_source_dataframes()
    # JICFS用データは、ユーザー抽出用データの解放後に読み込む。
    run(
        user_dataframes=user_dataframes,
        jicfs_data_loader=load_jicfs_source_dataframes,
    )


if __name__ == "__main__":
    main()
