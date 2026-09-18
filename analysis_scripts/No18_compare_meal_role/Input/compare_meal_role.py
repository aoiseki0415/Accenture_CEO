"""購買経験群と購買未経験群で、普段購入する食事形態を比較する。

目的
----
No17で人数とセブンイレブン利用日数を揃えた若年層について、
「軽食・補助食型」と「食事中心型」の購買記録数を比較する。

入力
----
1. このファイル内で用意する、JICFS Lv6を含むDataFrame
   ``data1`` ～ ``data5``
2. No17の ``Output/01_条件調整後ユーザー一覧.csv``
3. No4の ``Output/栄養バランス`` にある商品別CSVと
   ``product_file_mapping.csv``

出力
----
No18の ``Output`` に次のファイルを保存する。

* ``01_群別購買記録数.csv``
* ``02_ユーザー別購買記録数.csv``
* ``03_分類対象商品一覧.csv``
* ``04_その他惣菜_食事中心型振替一覧.csv``
* ``05_データ品質確認.csv``
* ``06_購買経験群_購買記録数.png``（matplotlibがある場合）
* ``07_購買未経験群_購買記録数.png``（matplotlibがある場合）
* ``08_感度分析_その他惣菜除外.csv``
* ``09_群別軽食購買記録割合.csv``
* ``10_群別軽食購買記録割合.png``（matplotlibがある場合）
* ``11_感度分析_対応商品を含む群別購買記録数.csv``
* ``12_感度分析_対応商品を含む群別軽食購買記録割合.csv``
* ``13_感度分析_対応商品を含む群別軽食購買記録割合.png``

注意
----
* No17で固定した二群を再作成しない。
* 群分けに使用した「栄養バランスを調整したい」対応商品は、
  主分析ではNo4の商品別CSVから取得したZaim商品名により除外する。
  群の定義を結果へ直接持ち込まないためである。
* 対応商品を含めた場合の結果も感度分析として別に保存する。
* receipt_keyは同じレシート内の複数商品で共有されるため、
  商品の一意識別や重複判定には使用しない。
* ``111997 その他惣菜`` は原則として軽食・補助食型とし、
  食事中心型の表現を含み、かつ軽食表現を含まない商品だけを
  食事中心型へ振り替える。
* 出力にはユーザーIDや実際の商品名が含まれる。会社環境内だけで管理し、
  個人PC、Notion、GitHub等へ保存・共有しないこと。
"""

from __future__ import annotations

import gc
import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# =====================================================================
# 【分析条件】
# =====================================================================

BALANCED_USER_PROJECT_DIR_NAME = "No17_balance_usage_days"
BALANCED_USER_FILENAME = "01_条件調整後ユーザー一覧.csv"

TARGET_PRODUCT_PROJECT_DIR_NAME = "No4_extract_confirmed_products_seven"
TARGET_PRODUCT_HEALTH_NEED_DIR_NAME = "栄養バランス"
TARGET_PRODUCT_MAPPING_FILENAME = "product_file_mapping.csv"

ANALYSIS_START_DATE = pd.Timestamp("2024-01-01")
ANALYSIS_END_DATE = pd.Timestamp("2026-06-30")

DATE_COLUMN = "date"
USER_ID_COLUMN = "user_id"
RECEIPT_KEY_COLUMN = "receipt_key"
PRODUCT_NAME_COLUMN = "name"
JICFS_LV6_CODE_COLUMN = "item_jicfs_lv6_code"
JICFS_LV6_NAME_COLUMN = "item_jicfs_lv6_name"
GROUP_COLUMN = "群"
USAGE_DAYS_COLUMN = "利用日数"

EXPERIENCED_GROUP = "購買経験群"
UNEXPERIENCED_GROUP = "購買未経験群"
GROUP_ORDER = (EXPERIENCED_GROUP, UNEXPERIENCED_GROUP)

LIGHT_ROLE = "軽食・補助食型"
CENTER_ROLE = "食事中心型"
ROLE_ORDER = (LIGHT_ROLE, CENTER_ROLE)
LIGHT_RECORD_COUNT_COLUMN = "軽食・補助食型購買記録数"
CENTER_RECORD_COUNT_COLUMN = "食事中心型購買記録数"
ROLE_COUNT_COLUMNS = {
    LIGHT_ROLE: LIGHT_RECORD_COUNT_COLUMN,
    CENTER_ROLE: CENTER_RECORD_COUNT_COLUMN,
}

# JICFS Lv6だけで軽食・補助食型と判定する11カテゴリー。
LIGHT_CODES = frozenset(
    {
        "110601",  # 調理用スープ
        "110603",  # インスタントスープ
        "110605",  # インスタント味噌汁・吸物
        "110697",  # その他スープ
        "111301",  # 食パン
        "111303",  # 菓子パン
        "111305",  # 調理パン
        "111307",  # シリアル類
        "111397",  # その他パン
        "111901",  # サラダ
        "111903",  # 煮豆
    }
)

# JICFS Lv6だけで食事中心型と判定する17カテゴリー。
CENTER_CODES = frozenset(
    {
        "110501",  # インスタントカレー
        "110502",  # 調理済みカレー
        "110503",  # インスタントシチュー
        "110504",  # 調理済みシチュー
        "110511",  # 米飯加工品
        "110597",  # その他調理品
        "110707",  # 冷凍調理
        "110721",  # 冷凍ピザ・グラタン類
        "110723",  # 冷凍麺
        "110725",  # 冷凍米飯加工品
        "111201",  # インスタント袋麺
        "111203",  # カップ麺
        "111207",  # 生麺・ゆで麺
        "111209",  # スパゲッティ
        "111905",  # 和惣菜
        "111907",  # 中華惣菜
        "111909",  # 洋惣菜
    }
)

# 商品名で例外判定するカテゴリー。原則は軽食・補助食型。
OTHER_DELI_CODE = "111997"

# 今回のS3取得対象から外したカテゴリー。
EXCLUDED_CODES = frozenset(
    {
        "110513",  # レンジ専用食品: データ不足
        "110797",  # その他冷凍食品: 調理素材が中心
        "111297",  # その他麺類: データ不足
    }
)

EXPECTED_ANALYSIS_CODES = LIGHT_CODES | CENTER_CODES | {OTHER_DELI_CODE}

# その他惣菜で、食事中心型への振替を止める表現。こちらを優先する。
LIGHT_OVERRIDE_KEYWORDS = (
    "おにぎり",
    "おむすび",
    "いなり",
    "手巻",
    "細巻",
    "サラダ",
    "パン",
)

# その他惣菜で、軽食表現がない場合に食事中心型へ振り替える表現。
CENTER_KEYWORDS = (
    "弁当",
    "丼",
    "重",
    "御膳",
    "幕の内",
    "プレート",
    "オムライス",
    "チャーハン",
    "炒飯",
    "ビビンバ",
    "カレー",
    "ドリア",
    "そば",
    "蕎麦",
    "うどん",
    "ラーメン",
    "パスタ",
    "スパゲティ",
    "スパゲッティ",
    "焼そば",
    "焼きそば",
    "ちゃんぽん",
)

REQUIRED_PURCHASE_COLUMNS = {
    DATE_COLUMN,
    USER_ID_COLUMN,
    RECEIPT_KEY_COLUMN,
    PRODUCT_NAME_COLUMN,
    JICFS_LV6_CODE_COLUMN,
    JICFS_LV6_NAME_COLUMN,
}

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
# 【ユーザー記入欄】S3読込テンプレートで data1～data5 を作成する
# =====================================================================
# この位置に、会社環境で用意されたS3読込コードを貼り付ける。
# 最終的に、JICFS Lv6を含む各期間のDataFrameが次の5変数へ
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


def normalize_identifier(values: pd.Series) -> pd.Series:
    """IDを比較用の文字列へ統一し、欠損・不明を除外可能にする。"""
    normalized = values.astype("string").str.strip()
    invalid = (
        values.isna()
        | normalized.isna()
        | normalized.eq("")
        | normalized.str.lower().isin({"nan", "none", "null"})
        | normalized.str.contains("不明", na=False)
    )
    normalized = normalized.str.replace(r"\.0$", "", regex=True)
    return normalized.mask(invalid)


def normalize_text(values: pd.Series) -> pd.Series:
    """文字列の欠損を空文字にし、前後空白を除く。"""
    return values.astype("string").fillna("").str.strip()


def normalize_jicfs_code(values: pd.Series) -> pd.Series:
    """JICFSコードを6桁の比較用文字列へ統一する。"""
    normalized = values.astype("string").str.strip()
    normalized = normalized.str.replace(r"\.0$", "", regex=True)
    return normalized


def build_literal_pattern(keywords: tuple[str, ...]) -> str:
    """部分一致用キーワードを正規表現として安全に連結する。"""
    return "|".join(re.escape(keyword) for keyword in keywords)


LIGHT_OVERRIDE_PATTERN = build_literal_pattern(LIGHT_OVERRIDE_KEYWORDS)
CENTER_PATTERN = build_literal_pattern(CENTER_KEYWORDS)


def read_balanced_users(input_path: Path) -> pd.DataFrame:
    """No17の条件調整後ユーザー一覧を読み込む。"""
    if not input_path.exists():
        raise FileNotFoundError(
            "No17の条件調整後ユーザー一覧が見つかりません。"
            f"\n確認対象: {input_path}"
        )

    users = pd.read_csv(
        input_path,
        dtype={USER_ID_COLUMN: "string", GROUP_COLUMN: "string"},
        encoding="utf-8-sig",
        low_memory=False,
    )
    required = {USER_ID_COLUMN, GROUP_COLUMN}
    require_columns(users, required, str(input_path))

    users = users.copy()
    users[USER_ID_COLUMN] = normalize_identifier(users[USER_ID_COLUMN])
    users[GROUP_COLUMN] = normalize_text(users[GROUP_COLUMN])

    invalid_user = users[USER_ID_COLUMN].isna()
    invalid_group = ~users[GROUP_COLUMN].isin(GROUP_ORDER)
    if invalid_user.any() or invalid_group.any():
        raise ValueError(
            "No17のユーザー一覧に不正な行があります。"
            f" user_id不正={int(invalid_user.sum())}行 /"
            f" 群不正={int(invalid_group.sum())}行"
        )

    duplicated = users[USER_ID_COLUMN].duplicated(keep=False)
    if duplicated.any():
        raise ValueError(
            "No17のユーザー一覧に同じuser_idが複数行あります: "
            f"{int(duplicated.sum())}行"
        )

    group_counts = users[GROUP_COLUMN].value_counts()
    if int(group_counts.get(EXPERIENCED_GROUP, 0)) != int(
        group_counts.get(UNEXPERIENCED_GROUP, 0)
    ):
        raise ValueError("No17の二群のユーザー数が一致していません。")

    keep_columns = [USER_ID_COLUMN, GROUP_COLUMN]
    if USAGE_DAYS_COLUMN in users.columns:
        keep_columns.append(USAGE_DAYS_COLUMN)
    return users.loc[:, keep_columns].reset_index(drop=True)


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
    return mapping


def collect_target_product_identifiers(
    product_source_dir: Path,
) -> tuple[set[str], pd.DataFrame]:
    """No4の商品別CSVから、除外に使うZaim商品名を集める。"""
    mapping = read_product_mapping(
        product_source_dir / TARGET_PRODUCT_MAPPING_FILENAME
    )
    product_names: set[str] = set()
    quality_rows: list[dict[str, object]] = []

    for _, row in mapping.iterrows():
        product_number = str(row["商品番号"]).strip().zfill(3)
        product_label = str(row["商品名"]).strip()
        product_path = product_source_dir / str(row["出力ファイル名"]).strip()
        if not product_path.exists():
            raise FileNotFoundError(
                f"商品{product_number}のCSVが見つかりません: {product_path}"
            )

        header = pd.read_csv(
            product_path,
            nrows=0,
            encoding="utf-8-sig",
        )
        require_columns(
            header,
            {PRODUCT_NAME_COLUMN},
            str(product_path),
        )
        product_data = pd.read_csv(
            product_path,
            usecols=[PRODUCT_NAME_COLUMN],
            dtype="string",
            encoding="utf-8-sig",
            low_memory=False,
        )

        normalized_names = normalize_text(product_data[PRODUCT_NAME_COLUMN])
        product_names.update(
            normalized_names.loc[normalized_names.ne("")].astype(str).tolist()
        )
        quality_rows.append(
            {
                "入力元": f"商品{product_number}｜{product_label}",
                "確認項目": "No4商品CSV行数",
                "行数": len(product_data),
            }
        )

    if not product_names:
        raise ValueError("対応商品を除外するZaim商品名を取得できませんでした。")
    return product_names, pd.DataFrame(quality_rows)


def classify_meal_role(
    codes: pd.Series,
    names: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """JICFS Lv6と商品名から食事形態を分類する。"""
    roles = pd.Series(pd.NA, index=codes.index, dtype="string")
    other_deli_moved = pd.Series(False, index=codes.index, dtype=bool)

    roles.loc[codes.isin(LIGHT_CODES)] = LIGHT_ROLE
    roles.loc[codes.isin(CENTER_CODES)] = CENTER_ROLE

    is_other_deli = codes.eq(OTHER_DELI_CODE)
    has_light_override = names.str.contains(
        LIGHT_OVERRIDE_PATTERN,
        regex=True,
        na=False,
    )
    has_center_keyword = names.str.contains(
        CENTER_PATTERN,
        regex=True,
        na=False,
    )

    # その他惣菜は原則として軽食・補助食型。
    roles.loc[is_other_deli] = LIGHT_ROLE
    other_deli_moved = is_other_deli & has_center_keyword & ~has_light_override
    roles.loc[other_deli_moved] = CENTER_ROLE
    return roles, other_deli_moved


def prepare_purchase_chunk(
    data: pd.DataFrame,
    source_name: str,
    cohort_user_ids: set[str],
    target_product_names: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """1期間分を対象ユーザーへ絞り、対応商品フラグを付けて分類する。"""
    require_columns(data, REQUIRED_PURCHASE_COLUMNS, source_name)

    selected = data.loc[:, sorted(REQUIRED_PURCHASE_COLUMNS)].copy()
    input_rows = len(selected)
    selected["_date"] = pd.to_datetime(selected[DATE_COLUMN], errors="coerce")
    selected["_user_id"] = normalize_identifier(selected[USER_ID_COLUMN])
    selected["_receipt_key"] = normalize_identifier(
        selected[RECEIPT_KEY_COLUMN]
    )
    selected["_name"] = normalize_text(selected[PRODUCT_NAME_COLUMN])
    selected["_jicfs_code"] = normalize_jicfs_code(
        selected[JICFS_LV6_CODE_COLUMN]
    )
    selected["_jicfs_name"] = normalize_text(
        selected[JICFS_LV6_NAME_COLUMN]
    )

    valid_date = selected["_date"].notna()
    in_period = valid_date & selected["_date"].between(
        ANALYSIS_START_DATE,
        ANALYSIS_END_DATE + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1),
        inclusive="both",
    )
    valid_user = selected["_user_id"].notna()
    in_cohort = valid_user & selected["_user_id"].isin(cohort_user_ids)
    expected_code = selected["_jicfs_code"].isin(EXPECTED_ANALYSIS_CODES)

    target_by_name = selected["_name"].isin(target_product_names)
    target_record = target_by_name

    eligible = in_period & in_cohort & expected_code
    prepared = selected.loc[
        eligible,
        [
            "_user_id",
            "_receipt_key",
            "_name",
            "_jicfs_code",
            "_jicfs_name",
        ],
    ].copy()
    prepared["対応商品"] = target_record.loc[eligible].to_numpy(dtype=bool)
    prepared["食事形態"], prepared["その他惣菜_食事中心型振替"] = (
        classify_meal_role(prepared["_jicfs_code"], prepared["_name"])
    )

    unclassified = prepared["食事形態"].isna()
    if unclassified.any():
        raise RuntimeError(
            f"{source_name}で食事形態を分類できない行があります: "
            f"{int(unclassified.sum())}行"
        )

    prepared = prepared.rename(
        columns={
            "_user_id": USER_ID_COLUMN,
            "_receipt_key": RECEIPT_KEY_COLUMN,
            "_name": PRODUCT_NAME_COLUMN,
            "_jicfs_code": JICFS_LV6_CODE_COLUMN,
            "_jicfs_name": JICFS_LV6_NAME_COLUMN,
        }
    )

    quality = pd.DataFrame(
        [
            {"入力元": source_name, "確認項目": "入力行数", "行数": input_rows},
            {
                "入力元": source_name,
                "確認項目": "期間内かつNo17対象ユーザーの行数",
                "行数": int((in_period & in_cohort).sum()),
            },
            {
                "入力元": source_name,
                "確認項目": "分析対象JICFSの行数（対応商品除外前）",
                "行数": int((in_period & in_cohort & expected_code).sum()),
            },
            {
                "入力元": source_name,
                "確認項目": "主分析で除外する対応商品行数",
                "行数": int((in_period & in_cohort & expected_code & target_record).sum()),
            },
            {
                "入力元": source_name,
                "確認項目": "食事関連商品行数（対応商品を含む）",
                "行数": len(prepared),
            },
            {
                "入力元": source_name,
                "確認項目": "主分析対象行数（対応商品を除外）",
                "行数": int((~prepared["対応商品"]).sum()),
            },
            {
                "入力元": source_name,
                "確認項目": "軽食・補助食型行数",
                "行数": int(prepared["食事形態"].eq(LIGHT_ROLE).sum()),
            },
            {
                "入力元": source_name,
                "確認項目": "食事中心型行数",
                "行数": int(prepared["食事形態"].eq(CENTER_ROLE).sum()),
            },
            {
                "入力元": source_name,
                "確認項目": "その他惣菜から食事中心型へ振替えた行数",
                "行数": int(
                    prepared["その他惣菜_食事中心型振替"].sum()
                ),
            },
        ]
    )
    return prepared, quality


def aggregate_user_counts(
    purchase_data: pd.DataFrame,
    balanced_users: pd.DataFrame,
) -> pd.DataFrame:
    """ユーザーごとに二つの食事形態の購買記録数を集計する。"""
    counts = (
        purchase_data.groupby([USER_ID_COLUMN, "食事形態"], sort=False)
        .size()
        .unstack(fill_value=0)
        .reindex(columns=ROLE_ORDER, fill_value=0)
        .reset_index()
    )
    result = balanced_users.merge(
        counts,
        on=USER_ID_COLUMN,
        how="left",
        validate="one_to_one",
    )
    for role in ROLE_ORDER:
        result[role] = result[role].fillna(0).astype(int)
    result = result.rename(columns=ROLE_COUNT_COLUMNS)

    result["食事関連商品購買記録数"] = result[
        [LIGHT_RECORD_COUNT_COLUMN, CENTER_RECORD_COUNT_COLUMN]
    ].sum(axis=1)
    result["軽食・補助食型購買記録割合（%）"] = np.where(
        result["食事関連商品購買記録数"].gt(0),
        result[LIGHT_RECORD_COUNT_COLUMN]
        / result["食事関連商品購買記録数"]
        * 100,
        np.nan,
    )
    return result


def summarize_groups(user_counts: pd.DataFrame) -> pd.DataFrame:
    """二群について、軽食・補助食型と食事中心型の購買記録数を要約する。"""
    rows: list[dict[str, object]] = []
    for group in GROUP_ORDER:
        group_data = user_counts.loc[user_counts[GROUP_COLUMN].eq(group)]
        if group_data.empty:
            raise ValueError(f"{group}のユーザーが存在しません。")

        light_count = int(group_data[LIGHT_RECORD_COUNT_COLUMN].sum())
        center_count = int(group_data[CENTER_RECORD_COUNT_COLUMN].sum())
        total_count = light_count + center_count
        users_with_records = int(
            group_data["食事関連商品購買記録数"].gt(0).sum()
        )
        valid_share = group_data[
            "軽食・補助食型購買記録割合（%）"
        ].dropna()

        for role, record_count in (
            (LIGHT_ROLE, light_count),
            (CENTER_ROLE, center_count),
        ):
            rows.append(
                {
                    "群": group,
                    "食事形態": role,
                    "ユーザー数": len(group_data),
                    "食事関連商品を1回以上購買したユーザー数": users_with_records,
                    "購買記録数": record_count,
                    "群内構成割合（%）": (
                        record_count / total_count * 100
                        if total_count > 0
                        else np.nan
                    ),
                    "1人当たり平均購買記録数": record_count
                    / len(group_data),
                    "ユーザー別軽食購買記録割合_平均（%）": (
                        valid_share.mean() if not valid_share.empty else np.nan
                    ),
                    "ユーザー別軽食購買記録割合_中央値（%）": (
                        valid_share.median() if not valid_share.empty else np.nan
                    ),
                }
            )
    return pd.DataFrame(rows)


def summarize_light_share(group_summary: pd.DataFrame) -> pd.DataFrame:
    """各群の食事関連商品購買記録に占める軽食割合をまとめる。"""
    rows: list[dict[str, object]] = []
    for group in GROUP_ORDER:
        data = group_summary.loc[group_summary["群"].eq(group)]
        light_count = int(
            data.loc[data["食事形態"].eq(LIGHT_ROLE), "購買記録数"].iloc[0]
        )
        center_count = int(
            data.loc[data["食事形態"].eq(CENTER_ROLE), "購買記録数"].iloc[0]
        )
        total_count = light_count + center_count
        rows.append(
            {
                "群": group,
                "軽食・補助食型購買記録数": light_count,
                "食事中心型購買記録数": center_count,
                "食事関連商品購買記録数": total_count,
                "軽食・補助食型購買記録割合（%）": (
                    light_count / total_count * 100
                    if total_count > 0
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def build_product_classification_table(purchase_data: pd.DataFrame) -> pd.DataFrame:
    """商品名・JICFS・最終分類ごとの購買記録数を保存用に集計する。"""
    return (
        purchase_data.groupby(
            [
                JICFS_LV6_CODE_COLUMN,
                JICFS_LV6_NAME_COLUMN,
                PRODUCT_NAME_COLUMN,
                "食事形態",
                "その他惣菜_食事中心型振替",
            ],
            dropna=False,
        )
        .size()
        .reset_index(name="購買記録数")
        .sort_values(
            ["食事形態", "購買記録数", PRODUCT_NAME_COLUMN],
            ascending=[True, False, True],
        )
        .reset_index(drop=True)
    )


def build_sensitivity_summary(
    purchase_data: pd.DataFrame,
    balanced_users: pd.DataFrame,
) -> pd.DataFrame:
    """その他惣菜を全件除外した場合の群別結果を作る。"""
    without_other_deli = purchase_data.loc[
        ~purchase_data[JICFS_LV6_CODE_COLUMN].eq(OTHER_DELI_CODE)
    ].copy()
    sensitivity_user_counts = aggregate_user_counts(
        without_other_deli,
        balanced_users,
    )
    result = summarize_groups(sensitivity_user_counts)
    result.insert(0, "分析条件", "111997 その他惣菜をすべて除外")
    return result


def configure_plot_font() -> bool:
    """利用可能な日本語フォントを検出し、なければ英語表示にする。"""
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
    print(
        "日本語フォントが見つからないため、グラフ内ラベルを英語で保存します。"
    )
    return False


def save_group_chart(
    group_summary: pd.DataFrame,
    group: str,
    output_path: Path,
    y_limit: float,
) -> bool:
    """1群について二つの食事形態の購買記録数を棒グラフで保存する。"""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlibがないためグラフ出力をスキップします。")
        return False

    use_japanese = configure_plot_font()
    data = (
        group_summary.loc[group_summary["群"].eq(group)]
        .set_index("食事形態")
        .reindex(ROLE_ORDER)
    )
    values = data["購買記録数"].astype(float).to_numpy()
    if use_japanese:
        labels = ROLE_ORDER
        title = group
        y_label = "購買記録数（件）"
    else:
        labels = ("Light / supplementary", "Meal-centered")
        title = (
            "Purchase-experienced"
            if group == EXPERIENCED_GROUP
            else "No purchase experience"
        )
        y_label = "Purchase records"

    fig, ax = plt.subplots(figsize=(7.2, 5.8))
    positions = np.array([-0.30, 0.30])
    bars = ax.bar(
        positions,
        values,
        width=0.44,
        color=("#6B9F8A", "#44546A"),
        edgecolor="#333333",
        linewidth=1.0,
    )
    ax.set_xticks(positions)
    ax.set_xticklabels(labels)
    ax.set_xlim(-0.95, 0.95)
    ax.set_ylim(0, y_limit)
    ax.set_title(title, fontsize=17, fontweight="bold", pad=14)
    ax.set_ylabel(y_label, fontsize=15, fontweight="bold")
    ax.tick_params(axis="x", labelsize=12, width=1.3)
    ax.tick_params(axis="y", labelsize=12, width=1.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_linewidth(1.4)
    ax.spines["bottom"].set_linewidth(1.4)
    ax.grid(axis="y", color="#D0D0D0", linewidth=0.8, alpha=0.75)
    ax.set_axisbelow(True)
    ax.bar_label(
        bars,
        labels=[f"{int(value):,}" for value in values],
        padding=4,
        fontsize=12,
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return True


def save_light_share_chart(
    light_share: pd.DataFrame,
    output_path: Path,
    title_suffix: str = "",
) -> bool:
    """二群の軽食・補助食型購買記録割合を棒グラフで保存する。"""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlibがないためグラフ出力をスキップします。")
        return False

    use_japanese = configure_plot_font()
    data = light_share.set_index("群").reindex(GROUP_ORDER)
    values = data["軽食・補助食型購買記録割合（%）"].astype(float).to_numpy()
    if use_japanese:
        labels = GROUP_ORDER
        title = "食事関連商品の購買記録に占める軽食の割合"
        if title_suffix:
            title = f"{title}\n{title_suffix}"
        y_label = "軽食・補助食型購買記録割合（%）"
    else:
        labels = ("Purchase-experienced", "No purchase experience")
        title = "Share of light / supplementary food purchases"
        if title_suffix:
            title = f"{title}\n(including target products)"
        y_label = "Share of purchase records (%)"

    fig, ax = plt.subplots(figsize=(7.2, 5.8))
    positions = np.array([-0.30, 0.30])
    bars = ax.bar(
        positions,
        values,
        width=0.44,
        color=("#8064A2", "#D99694"),
        edgecolor="#333333",
        linewidth=1.0,
    )
    ax.set_xticks(positions)
    ax.set_xticklabels(labels)
    ax.set_xlim(-0.95, 0.95)
    ax.set_ylim(0, 100)
    ax.set_title(title, fontsize=16, fontweight="bold", pad=14)
    ax.set_ylabel(y_label, fontsize=14, fontweight="bold")
    ax.tick_params(axis="x", labelsize=12, width=1.3)
    ax.tick_params(axis="y", labelsize=12, width=1.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_linewidth(1.4)
    ax.spines["bottom"].set_linewidth(1.4)
    ax.grid(axis="y", color="#D0D0D0", linewidth=0.8, alpha=0.75)
    ax.set_axisbelow(True)
    ax.bar_label(
        bars,
        labels=[f"{value:.1f}%" for value in values],
        padding=4,
        fontsize=12,
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return True


def save_outputs(
    balanced_users: pd.DataFrame,
    purchase_data: pd.DataFrame,
    purchase_data_including_targets: pd.DataFrame,
    quality_table: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    """集計表・確認表・グラフを保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    user_counts = aggregate_user_counts(purchase_data, balanced_users)
    group_summary = summarize_groups(user_counts)
    light_share = summarize_light_share(group_summary)
    product_classification = build_product_classification_table(purchase_data)
    moved_other_deli = product_classification.loc[
        product_classification["その他惣菜_食事中心型振替"].eq(True)
    ].copy()
    sensitivity = build_sensitivity_summary(purchase_data, balanced_users)
    user_counts_including_targets = aggregate_user_counts(
        purchase_data_including_targets,
        balanced_users,
    )
    group_summary_including_targets = summarize_groups(
        user_counts_including_targets
    )
    light_share_including_targets = summarize_light_share(
        group_summary_including_targets
    )

    output_paths = [
        output_dir / "01_群別購買記録数.csv",
        output_dir / "02_ユーザー別購買記録数.csv",
        output_dir / "03_分類対象商品一覧.csv",
        output_dir / "04_その他惣菜_食事中心型振替一覧.csv",
        output_dir / "05_データ品質確認.csv",
    ]
    group_summary.to_csv(
        output_paths[0], index=False, encoding="utf-8-sig", float_format="%.6f"
    )
    user_counts.to_csv(
        output_paths[1], index=False, encoding="utf-8-sig", float_format="%.6f"
    )
    product_classification.to_csv(
        output_paths[2], index=False, encoding="utf-8-sig"
    )
    moved_other_deli.to_csv(
        output_paths[3], index=False, encoding="utf-8-sig"
    )
    quality_table.to_csv(
        output_paths[4], index=False, encoding="utf-8-sig"
    )

    max_count = float(group_summary["購買記録数"].max())
    y_limit = max(1.0, max_count * 1.18)
    chart_specs = [
        (
            EXPERIENCED_GROUP,
            output_dir / "06_購買経験群_購買記録数.png",
        ),
        (
            UNEXPERIENCED_GROUP,
            output_dir / "07_購買未経験群_購買記録数.png",
        ),
    ]
    for group, path in chart_specs:
        if save_group_chart(group_summary, group, path, y_limit):
            output_paths.append(path)

    sensitivity_path = output_dir / "08_感度分析_その他惣菜除外.csv"
    sensitivity.to_csv(
        sensitivity_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
    )
    output_paths.append(sensitivity_path)

    light_share_path = output_dir / "09_群別軽食購買記録割合.csv"
    light_share.to_csv(
        light_share_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
    )
    output_paths.append(light_share_path)

    light_share_chart_path = output_dir / "10_群別軽食購買記録割合.png"
    if save_light_share_chart(light_share, light_share_chart_path):
        output_paths.append(light_share_chart_path)

    included_summary_path = (
        output_dir / "11_感度分析_対応商品を含む群別購買記録数.csv"
    )
    group_summary_including_targets.to_csv(
        included_summary_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
    )
    output_paths.append(included_summary_path)

    included_share_path = (
        output_dir / "12_感度分析_対応商品を含む群別軽食購買記録割合.csv"
    )
    light_share_including_targets.to_csv(
        included_share_path,
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
    )
    output_paths.append(included_share_path)

    included_share_chart_path = (
        output_dir / "13_感度分析_対応商品を含む群別軽食購買記録割合.png"
    )
    if save_light_share_chart(
        light_share_including_targets,
        included_share_chart_path,
        title_suffix="（対応商品を含む感度分析）",
    ):
        output_paths.append(included_share_chart_path)
    return output_paths


def run(
    dataframes: list[pd.DataFrame],
    balanced_user_path: Optional[Path] = None,
    product_source_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> list[Path]:
    """条件調整済み二群について食事形態の購買記録数を比較する。"""
    project_dir = Path(__file__).resolve().parents[1]
    workspace_dir = project_dir.parent

    if balanced_user_path is None:
        balanced_user_path = (
            workspace_dir
            / BALANCED_USER_PROJECT_DIR_NAME
            / "Output"
            / BALANCED_USER_FILENAME
        )
    if product_source_dir is None:
        product_source_dir = (
            workspace_dir
            / TARGET_PRODUCT_PROJECT_DIR_NAME
            / "Output"
            / TARGET_PRODUCT_HEALTH_NEED_DIR_NAME
        )
    if output_dir is None:
        output_dir = project_dir / "Output"

    balanced_users = read_balanced_users(balanced_user_path)
    cohort_user_ids = set(
        balanced_users[USER_ID_COLUMN].dropna().astype(str).tolist()
    )
    target_product_names, target_quality = (
        collect_target_product_identifiers(product_source_dir)
    )

    prepared_chunks: list[pd.DataFrame] = []
    quality_tables: list[pd.DataFrame] = [target_quality]
    for number, data in enumerate(dataframes, start=1):
        prepared, quality = prepare_purchase_chunk(
            data=data,
            source_name=f"data{number}",
            cohort_user_ids=cohort_user_ids,
            target_product_names=target_product_names,
        )
        prepared_chunks.append(prepared)
        quality_tables.append(quality)
        print(
            f"data{number}: 入力={len(data):,}行 / "
            f"最終分析対象={len(prepared):,}行"
        )

    purchase_data_including_targets = pd.concat(
        prepared_chunks,
        ignore_index=True,
        sort=False,
        copy=False,
    )
    prepared_chunks.clear()
    dataframes.clear()
    gc.collect()

    if purchase_data_including_targets.empty:
        raise ValueError("条件を満たす食事関連商品の購買記録がありません。")

    purchase_data = purchase_data_including_targets.loc[
        ~purchase_data_including_targets["対応商品"]
    ].copy()
    if purchase_data.empty:
        raise ValueError(
            "対応商品を除外すると、主分析に使える購買記録がありません。"
        )

    overall_quality = pd.DataFrame(
        [
            {
                "入力元": "全体",
                "確認項目": "No17対象ユーザー数",
                "行数": len(balanced_users),
            },
            {
                "入力元": "全体",
                "確認項目": "対応商品除外用Zaim商品名数",
                "行数": len(target_product_names),
            },
            {
                "入力元": "全体",
                "確認項目": "食事関連商品行数（対応商品を含む）",
                "行数": len(purchase_data_including_targets),
            },
            {
                "入力元": "全体",
                "確認項目": "主分析対象行数（対応商品を除外）",
                "行数": len(purchase_data),
            },
        ]
    )
    quality_table = pd.concat(
        [*quality_tables, overall_quality],
        ignore_index=True,
        sort=False,
    )

    output_paths = save_outputs(
        balanced_users=balanced_users,
        purchase_data=purchase_data,
        purchase_data_including_targets=purchase_data_including_targets,
        quality_table=quality_table,
        output_dir=output_dir,
    )

    summary = pd.read_csv(output_paths[0], encoding="utf-8-sig")
    print("\n食事形態の群間比較が完了しました。")
    for group in GROUP_ORDER:
        group_summary = summary.loc[summary["群"].eq(group)]
        light_count = int(
            group_summary.loc[
                group_summary["食事形態"].eq(LIGHT_ROLE), "購買記録数"
            ].iloc[0]
        )
        center_count = int(
            group_summary.loc[
                group_summary["食事形態"].eq(CENTER_ROLE), "購買記録数"
            ].iloc[0]
        )
        print(
            f"{group}: {LIGHT_ROLE}={light_count:,}件 / "
            f"{CENTER_ROLE}={center_count:,}件"
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
