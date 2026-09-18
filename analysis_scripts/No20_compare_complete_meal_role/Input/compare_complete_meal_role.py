"""購買経験群と購買未経験群で、惣菜類に求める役割を比較する。

目的
----
No17で人数とセブンイレブン利用日数を揃えた若年層について、
JICFS Lv4「惣菜類」の購買記録を次の2群へ分類して比較する。

1. 一食完結型: その商品だけで一回の食事を完結させる役割
2. 食事補完型: 家庭内の食事等を補足する役割

分類方法
--------
1. 商品名が一食完結型キーワードを含む場合、一食完結型候補とする。
2. 候補のうち食事補完型優先キーワードを含む商品は食事補完型へ戻す。
3. 最終的に一食完結型へ残らなかった惣菜類は、余事象として食事補完型とする。

入力
----
1. このファイル内で用意する、JICFS Lv4・Lv6を含むDataFrame
   ``data1`` ～ ``data5``
2. No17の ``Output/01_条件調整後ユーザー一覧.csv``
3. No4の ``Output/栄養バランス`` にある商品別CSVと
   ``product_file_mapping.csv``

出力
----
No20の ``Output`` に、群別・ユーザー別の集計、商品分類一覧、
データ品質確認、購買記録数と一食完結型割合のFigureを保存する。

注意
----
* No17で固定した二群を再作成しない。
* 主分析では、群分けに使用した「栄養バランスを調整したい」対応商品を含め、
  対象ユーザーが購入した惣菜類全体を比較する。
* 対応商品を除いた場合の結果も感度分析として別に保存し、
  対応商品の含有によって結論がどの程度変わるかを確認する。
* receipt_keyは同じレシート内の複数商品で共有されるため、重複排除に使わない。
* 出力にはユーザーID、商品名、集計結果が含まれる。会社環境内だけで管理し、
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
JICFS_LV4_CODE_COLUMN = "item_jicfs_lv4_code"
JICFS_LV4_NAME_COLUMN = "item_jicfs_lv4_name"
JICFS_LV6_CODE_COLUMN = "item_jicfs_lv6_code"
JICFS_LV6_NAME_COLUMN = "item_jicfs_lv6_name"
GROUP_COLUMN = "群"
USAGE_DAYS_COLUMN = "利用日数"

EXPERIENCED_GROUP = "購買経験群"
UNEXPERIENCED_GROUP = "購買未経験群"
GROUP_ORDER = (EXPERIENCED_GROUP, UNEXPERIENCED_GROUP)

COMPLETE_ROLE = "一食完結型"
SUPPLEMENT_ROLE = "食事補完型"
ROLE_ORDER = (COMPLETE_ROLE, SUPPLEMENT_ROLE)
COMPLETE_COUNT_COLUMN = "一食完結型購買記録数"
SUPPLEMENT_COUNT_COLUMN = "食事補完型購買記録数"
ROLE_COUNT_COLUMNS = {
    COMPLETE_ROLE: COMPLETE_COUNT_COLUMN,
    SUPPLEMENT_ROLE: SUPPLEMENT_COUNT_COLUMN,
}

TARGET_LV4_NAME_KEYWORD = "惣菜"

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

# 一食完結型キーワードに該当しても、次の表現を含めば食事補完型へ戻す。
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

# 割合グラフは原則30%を上限とする。実値が超える場合は自動的に拡張する。
SHARE_CHART_MIN_Y_MAX = 30.0

REQUIRED_PURCHASE_COLUMNS = {
    DATE_COLUMN,
    USER_ID_COLUMN,
    RECEIPT_KEY_COLUMN,
    PRODUCT_NAME_COLUMN,
    JICFS_LV4_CODE_COLUMN,
    JICFS_LV4_NAME_COLUMN,
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
# 最終的に、上記の必要列を含む各期間のDataFrameが次の5変数へ
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


def build_literal_pattern(keywords: tuple[str, ...]) -> str:
    return "|".join(re.escape(keyword) for keyword in keywords)


COMPLETE_PATTERN = build_literal_pattern(COMPLETE_MEAL_KEYWORDS)
SUPPLEMENT_OVERRIDE_PATTERN = build_literal_pattern(SUPPLEMENT_OVERRIDE_KEYWORDS)


def read_balanced_users(input_path: Path) -> pd.DataFrame:
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
    require_columns(users, {USER_ID_COLUMN, GROUP_COLUMN}, str(input_path))
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


def collect_target_product_names(product_source_dir: Path) -> tuple[set[str], pd.DataFrame]:
    mapping_path = product_source_dir / TARGET_PRODUCT_MAPPING_FILENAME
    if not mapping_path.exists():
        raise FileNotFoundError(f"商品対応表が見つかりません: {mapping_path}")
    mapping = pd.read_csv(
        mapping_path, dtype=str, encoding="utf-8-sig"
    ).fillna("")
    require_columns(
        mapping,
        {"商品番号", "商品名", "出力ファイル名"},
        str(mapping_path),
    )
    if mapping.empty:
        raise ValueError(f"商品対応表が空です: {mapping_path}")

    product_names: set[str] = set()
    quality_rows: list[dict[str, object]] = []
    for _, row in mapping.iterrows():
        number = str(row["商品番号"]).strip().zfill(3)
        label = str(row["商品名"]).strip()
        product_path = product_source_dir / str(row["出力ファイル名"]).strip()
        if not product_path.exists():
            raise FileNotFoundError(f"商品{number}のCSVが見つかりません: {product_path}")
        product_data = pd.read_csv(
            product_path,
            usecols=[PRODUCT_NAME_COLUMN],
            dtype="string",
            encoding="utf-8-sig",
            low_memory=False,
        )
        normalized = normalize_text(product_data[PRODUCT_NAME_COLUMN])
        product_names.update(normalized.loc[normalized.ne("")].astype(str).tolist())
        quality_rows.append(
            {
                "入力元": f"商品{number}｜{label}",
                "確認項目": "No4商品CSV行数",
                "行数": len(product_data),
            }
        )
    if not product_names:
        raise ValueError("対応商品を除外するZaim商品名を取得できませんでした。")
    return product_names, pd.DataFrame(quality_rows)


def classify_meal_role(names: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """商品名から一食完結型を確定し、残りを食事補完型とする。"""
    keyword_hit = names.str.contains(COMPLETE_PATTERN, regex=True, na=False)
    override_hit = names.str.contains(
        SUPPLEMENT_OVERRIDE_PATTERN,
        regex=True,
        na=False,
    )
    complete = keyword_hit & ~override_hit
    roles = pd.Series(SUPPLEMENT_ROLE, index=names.index, dtype="string")
    roles.loc[complete] = COMPLETE_ROLE
    return roles, keyword_hit, override_hit


def prepare_purchase_chunk(
    data: pd.DataFrame,
    source_name: str,
    cohort_user_ids: set[str],
    target_product_names: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    require_columns(data, REQUIRED_PURCHASE_COLUMNS, source_name)
    selected = data.loc[:, sorted(REQUIRED_PURCHASE_COLUMNS)].copy()
    input_rows = len(selected)

    selected["_date"] = pd.to_datetime(selected[DATE_COLUMN], errors="coerce")
    selected["_user_id"] = normalize_identifier(selected[USER_ID_COLUMN])
    selected["_receipt_key"] = normalize_identifier(selected[RECEIPT_KEY_COLUMN])
    selected["_name"] = normalize_text(selected[PRODUCT_NAME_COLUMN])
    selected["_lv4_code"] = normalize_jicfs_code(selected[JICFS_LV4_CODE_COLUMN])
    selected["_lv4_name"] = normalize_text(selected[JICFS_LV4_NAME_COLUMN])
    selected["_lv6_code"] = normalize_jicfs_code(selected[JICFS_LV6_CODE_COLUMN])
    selected["_lv6_name"] = normalize_text(selected[JICFS_LV6_NAME_COLUMN])

    in_period = selected["_date"].between(
        ANALYSIS_START_DATE,
        ANALYSIS_END_DATE + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1),
        inclusive="both",
    )
    in_cohort = selected["_user_id"].notna() & selected["_user_id"].isin(
        cohort_user_ids
    )
    is_deli = selected["_lv4_name"].str.contains(
        TARGET_LV4_NAME_KEYWORD,
        regex=False,
        na=False,
    )
    target_record = selected["_name"].isin(target_product_names)
    eligible = in_period & in_cohort & is_deli & selected["_name"].ne("")

    prepared = selected.loc[
        eligible,
        [
            "_user_id",
            "_receipt_key",
            "_name",
            "_lv4_code",
            "_lv4_name",
            "_lv6_code",
            "_lv6_name",
        ],
    ].copy()
    prepared["対応商品"] = target_record.loc[eligible].to_numpy(dtype=bool)
    (
        prepared["食事形態"],
        prepared["一食完結型キーワード該当"],
        prepared["食事補完型優先表現該当"],
    ) = classify_meal_role(prepared["_name"])
    prepared = prepared.rename(
        columns={
            "_user_id": USER_ID_COLUMN,
            "_receipt_key": RECEIPT_KEY_COLUMN,
            "_name": PRODUCT_NAME_COLUMN,
            "_lv4_code": JICFS_LV4_CODE_COLUMN,
            "_lv4_name": JICFS_LV4_NAME_COLUMN,
            "_lv6_code": JICFS_LV6_CODE_COLUMN,
            "_lv6_name": JICFS_LV6_NAME_COLUMN,
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
                "確認項目": "Lv4惣菜類行数（対応商品を含む）",
                "行数": len(prepared),
            },
            {
                "入力元": source_name,
                "確認項目": "主分析で除外する対応商品行数",
                "行数": int(prepared["対応商品"].sum()),
            },
            {
                "入力元": source_name,
                "確認項目": "一食完結型キーワード該当行数",
                "行数": int(prepared["一食完結型キーワード該当"].sum()),
            },
            {
                "入力元": source_name,
                "確認項目": "食事補完型優先表現で戻した行数",
                "行数": int(
                    (
                        prepared["一食完結型キーワード該当"]
                        & prepared["食事補完型優先表現該当"]
                    ).sum()
                ),
            },
            {
                "入力元": source_name,
                "確認項目": "最終一食完結型行数",
                "行数": int(prepared["食事形態"].eq(COMPLETE_ROLE).sum()),
            },
            {
                "入力元": source_name,
                "確認項目": "最終食事補完型行数",
                "行数": int(prepared["食事形態"].eq(SUPPLEMENT_ROLE).sum()),
            },
        ]
    )
    return prepared, quality


def aggregate_user_counts(
    purchase_data: pd.DataFrame,
    balanced_users: pd.DataFrame,
) -> pd.DataFrame:
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
    result["惣菜類購買記録数"] = result[
        [COMPLETE_COUNT_COLUMN, SUPPLEMENT_COUNT_COLUMN]
    ].sum(axis=1)
    result["一食完結型購買記録割合（%）"] = np.where(
        result["惣菜類購買記録数"].gt(0),
        result[COMPLETE_COUNT_COLUMN] / result["惣菜類購買記録数"] * 100,
        np.nan,
    )
    return result


def summarize_groups(user_counts: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group in GROUP_ORDER:
        group_data = user_counts.loc[user_counts[GROUP_COLUMN].eq(group)]
        if group_data.empty:
            raise ValueError(f"{group}のユーザーが存在しません。")
        complete_count = int(group_data[COMPLETE_COUNT_COLUMN].sum())
        supplement_count = int(group_data[SUPPLEMENT_COUNT_COLUMN].sum())
        total_count = complete_count + supplement_count
        users_with_records = int(group_data["惣菜類購買記録数"].gt(0).sum())
        for role, count in (
            (COMPLETE_ROLE, complete_count),
            (SUPPLEMENT_ROLE, supplement_count),
        ):
            rows.append(
                {
                    "群": group,
                    "食事形態": role,
                    "ユーザー数": len(group_data),
                    "惣菜類を1回以上購買したユーザー数": users_with_records,
                    "購買記録数": count,
                    "群内構成割合（%）": (
                        count / total_count * 100 if total_count else np.nan
                    ),
                    "1人当たり平均購買記録数": count / len(group_data),
                }
            )
    return pd.DataFrame(rows)


def summarize_complete_share(group_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group in GROUP_ORDER:
        data = group_summary.loc[group_summary["群"].eq(group)]
        complete_count = int(
            data.loc[data["食事形態"].eq(COMPLETE_ROLE), "購買記録数"].iloc[0]
        )
        supplement_count = int(
            data.loc[data["食事形態"].eq(SUPPLEMENT_ROLE), "購買記録数"].iloc[0]
        )
        total_count = complete_count + supplement_count
        rows.append(
            {
                "群": group,
                COMPLETE_COUNT_COLUMN: complete_count,
                SUPPLEMENT_COUNT_COLUMN: supplement_count,
                "惣菜類購買記録数": total_count,
                "一食完結型購買記録割合（%）": (
                    complete_count / total_count * 100 if total_count else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def matched_keyword_text(product_name: str, keywords: tuple[str, ...]) -> str:
    return "｜".join(keyword for keyword in keywords if keyword in product_name)


def build_product_classification_table(purchase_data: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        JICFS_LV4_CODE_COLUMN,
        JICFS_LV4_NAME_COLUMN,
        JICFS_LV6_CODE_COLUMN,
        JICFS_LV6_NAME_COLUMN,
        PRODUCT_NAME_COLUMN,
        "食事形態",
        "一食完結型キーワード該当",
        "食事補完型優先表現該当",
    ]
    result = (
        purchase_data.groupby(group_columns, dropna=False, observed=True)
        .size()
        .reset_index(name="購買記録数")
    )
    result["一食完結型該当キーワード"] = result[PRODUCT_NAME_COLUMN].map(
        lambda name: matched_keyword_text(name, COMPLETE_MEAL_KEYWORDS)
    )
    result["食事補完型優先キーワード"] = result[PRODUCT_NAME_COLUMN].map(
        lambda name: matched_keyword_text(name, SUPPLEMENT_OVERRIDE_KEYWORDS)
    )
    return result.sort_values(
        ["食事形態", "購買記録数", PRODUCT_NAME_COLUMN],
        ascending=[True, False, True],
    ).reset_index(drop=True)


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


def save_group_chart(
    group_summary: pd.DataFrame,
    group: str,
    output_path: Path,
    y_limit: float,
) -> bool:
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
    labels = ROLE_ORDER if use_japanese else ("Complete meal", "Meal supplement")
    title = group if use_japanese else (
        "Purchase-experienced"
        if group == EXPERIENCED_GROUP
        else "No purchase experience"
    )
    y_label = "購買記録数（件）" if use_japanese else "Purchase records"

    fig, ax = plt.subplots(figsize=(7.2, 5.8))
    positions = np.array([-0.30, 0.30])
    bars = ax.bar(
        positions,
        values,
        width=0.44,
        color=("#44546A", "#9E9E9E"),
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


def save_complete_share_chart(
    complete_share: pd.DataFrame,
    output_path: Path,
    title_suffix: str = "",
) -> bool:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlibがないためグラフ出力をスキップします。")
        return False
    use_japanese = configure_plot_font()
    data = complete_share.set_index("群").reindex(GROUP_ORDER)
    values = data["一食完結型購買記録割合（%）"].astype(float).to_numpy()
    if use_japanese:
        labels = GROUP_ORDER
        title = "惣菜類の購買記録に占める一食完結型の割合"
        if title_suffix:
            title = f"{title}\n{title_suffix}"
        y_label = "一食完結型購買記録割合（%）"
    else:
        labels = ("Purchase-experienced", "No purchase experience")
        title = "Share of complete-meal purchases"
        if title_suffix:
            title = f"{title}\n(sensitivity analysis: target products excluded)"
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
    finite_values = values[np.isfinite(values)]
    observed_max = float(finite_values.max()) if finite_values.size else 0.0
    y_limit = max(
        SHARE_CHART_MIN_Y_MAX,
        np.ceil((observed_max * 1.15) / 5.0) * 5.0,
    )
    ax.set_ylim(0, y_limit)
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
    main_purchase_data: pd.DataFrame,
    sensitivity_purchase_data: pd.DataFrame,
    quality_table: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    user_counts = aggregate_user_counts(main_purchase_data, balanced_users)
    group_summary = summarize_groups(user_counts)
    complete_share = summarize_complete_share(group_summary)
    product_classification = build_product_classification_table(main_purchase_data)

    sensitivity_user_counts = aggregate_user_counts(
        sensitivity_purchase_data, balanced_users
    )
    sensitivity_group_summary = summarize_groups(sensitivity_user_counts)
    sensitivity_complete_share = summarize_complete_share(
        sensitivity_group_summary
    )

    tables = [
        ("01_群別購買記録数.csv", group_summary),
        ("02_ユーザー別購買記録数.csv", user_counts),
        ("03_惣菜類の商品分類一覧.csv", product_classification),
        (
            "04_一食完結型商品一覧.csv",
            product_classification.loc[
                product_classification["食事形態"].eq(COMPLETE_ROLE)
            ],
        ),
        (
            "05_食事補完型商品一覧.csv",
            product_classification.loc[
                product_classification["食事形態"].eq(SUPPLEMENT_ROLE)
            ],
        ),
        ("06_データ品質確認.csv", quality_table),
        ("09_群別一食完結型購買記録割合.csv", complete_share),
        (
            "11_感度分析_対応商品を除外した群別購買記録数.csv",
            sensitivity_group_summary,
        ),
        (
            "12_感度分析_対応商品を除外した一食完結型購買記録割合.csv",
            sensitivity_complete_share,
        ),
    ]
    output_paths: list[Path] = []
    for filename, table in tables:
        path = output_dir / filename
        table.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.6f")
        output_paths.append(path)

    max_count = float(group_summary["購買記録数"].max())
    y_limit = max(1.0, max_count * 1.18)
    for group, filename in (
        (EXPERIENCED_GROUP, "07_購買経験群_購買記録数.png"),
        (UNEXPERIENCED_GROUP, "08_購買未経験群_購買記録数.png"),
    ):
        path = output_dir / filename
        if save_group_chart(group_summary, group, path, y_limit):
            output_paths.append(path)

    share_chart = output_dir / "10_群別一食完結型購買記録割合.png"
    if save_complete_share_chart(complete_share, share_chart):
        output_paths.append(share_chart)

    sensitivity_chart = (
        output_dir / "13_感度分析_対応商品を除外した一食完結型割合.png"
    )
    if save_complete_share_chart(
        sensitivity_complete_share,
        sensitivity_chart,
        title_suffix="（対応商品を除外した感度分析）",
    ):
        output_paths.append(sensitivity_chart)
    return output_paths


def run(
    dataframes: list[pd.DataFrame],
    balanced_user_path: Optional[Path] = None,
    product_source_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> list[Path]:
    if len(dataframes) != 5:
        raise ValueError("data1～data5の5つのDataFrameを指定してください。")
    project_dir = Path(__file__).resolve().parents[1]
    workspace_dir = project_dir.parent
    balanced_user_path = balanced_user_path or (
        workspace_dir
        / BALANCED_USER_PROJECT_DIR_NAME
        / "Output"
        / BALANCED_USER_FILENAME
    )
    product_source_dir = product_source_dir or (
        workspace_dir
        / TARGET_PRODUCT_PROJECT_DIR_NAME
        / "Output"
        / TARGET_PRODUCT_HEALTH_NEED_DIR_NAME
    )
    output_dir = output_dir or project_dir / "Output"

    balanced_users = read_balanced_users(balanced_user_path)
    cohort_user_ids = set(balanced_users[USER_ID_COLUMN].astype(str).tolist())
    target_names, target_quality = collect_target_product_names(product_source_dir)

    prepared_chunks: list[pd.DataFrame] = []
    quality_tables: list[pd.DataFrame] = [target_quality]
    for number, data in enumerate(dataframes, start=1):
        prepared, quality = prepare_purchase_chunk(
            data=data,
            source_name=f"data{number}",
            cohort_user_ids=cohort_user_ids,
            target_product_names=target_names,
        )
        prepared_chunks.append(prepared)
        quality_tables.append(quality)
        print(
            f"data{number}: 入力={len(data):,}行 / "
            f"Lv4惣菜類={len(prepared):,}行"
        )

    main_purchase_data = pd.concat(
        prepared_chunks,
        ignore_index=True,
        sort=False,
        copy=False,
    )
    prepared_chunks.clear()
    dataframes.clear()
    gc.collect()

    if main_purchase_data.empty:
        raise ValueError(
            "No17対象ユーザーの分析期間内データに、Lv4「惣菜類」がありません。"
        )
    sensitivity_purchase_data = main_purchase_data.loc[
        ~main_purchase_data["対応商品"]
    ].copy()
    if sensitivity_purchase_data.empty:
        raise ValueError("対応商品を除外すると感度分析対象がありません。")

    overall_quality = pd.DataFrame(
        [
            {"入力元": "全体", "確認項目": "No17対象ユーザー数", "行数": len(balanced_users)},
            {"入力元": "全体", "確認項目": "対応商品Zaim商品名数", "行数": len(target_names)},
            {
                "入力元": "全体",
                "確認項目": "主分析対象行数（対応商品を含む）",
                "行数": len(main_purchase_data),
            },
            {
                "入力元": "全体",
                "確認項目": "感度分析対象行数（対応商品を除外）",
                "行数": len(sensitivity_purchase_data),
            },
        ]
    )
    quality_table = pd.concat(
        [*quality_tables, overall_quality], ignore_index=True, sort=False
    )
    output_paths = save_outputs(
        balanced_users=balanced_users,
        main_purchase_data=main_purchase_data,
        sensitivity_purchase_data=sensitivity_purchase_data,
        quality_table=quality_table,
        output_dir=output_dir,
    )

    summary = pd.read_csv(output_dir / "09_群別一食完結型購買記録割合.csv")
    print("\nNo20の食事形態比較が完了しました。")
    for row in summary.itertuples(index=False):
        print(f"{row[0]}: 一食完結型割合={float(row[4]):.1f}%")
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
