"""購買経験群と購買未経験群の人数・セブン利用日数を揃える。

目的
----
No16で作成したユーザー別利用日数を用い、購買経験群は全員残したまま、
購買未経験群から同数のユーザーを抽出する。購買未経験群は、購買経験群の
利用日数にできるだけ近い分布となるように選ぶ。

この処理では抽出のために利用日数の近いユーザーを内部的に対応づけるが、
後続分析をペア単位で行うことは前提としない。最終的には、人数と利用日数の
分布を揃えた2群として扱う。

入力
----
No16の ``Output/02_ユーザー別利用日数.csv``

出力
----
No17の ``Output`` に次のファイルを保存する。

* ``01_条件調整後ユーザー一覧.csv``
* ``02_条件調整前後要約.csv``
* ``03_利用日数分布確認.csv``
* ``04_条件調整品質確認.csv``

注意
----
出力にはユーザーIDが含まれる。会社環境内だけで管理し、個人PC、Notion、
GitHub等へ保存・共有しないこと。
"""

from __future__ import annotations

from bisect import bisect_left
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# =====================================================================
# 【分析条件】
# =====================================================================

SOURCE_PROJECT_DIR_NAME = "No16_compare_seven_usage_days"
SOURCE_FILENAME = "02_ユーザー別利用日数.csv"

USER_ID_COLUMN = "user_id"
GROUP_COLUMN = "群"
USAGE_DAYS_COLUMN = "利用日数"

EXPERIENCED_GROUP = "購買経験群"
UNEXPERIENCED_GROUP = "購買未経験群"
GROUP_ORDER = (EXPERIENCED_GROUP, UNEXPERIENCED_GROUP)

# 同じ利用日数の候補が複数いる場合の抽出を再現可能にする。
RANDOM_SEED = 20260915

# 0.1未満を、利用日数の平均差が十分小さいかを見る目安とする。
# この値を超えても処理は止めず、品質確認表とログで警告する。
SMD_WARNING_THRESHOLD = 0.10

REQUIRED_COLUMNS = {
    USER_ID_COLUMN,
    GROUP_COLUMN,
    USAGE_DAYS_COLUMN,
}


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
    """欠損・空欄・不明を除外できる比較用IDへ統一する。"""
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


def read_user_usage_days(input_path: Path) -> pd.DataFrame:
    """No16のユーザー別利用日数を読み込み、分析可能な形へ整える。"""
    if not input_path.exists():
        raise FileNotFoundError(
            "No16のユーザー別利用日数CSVが見つかりません。"
            f"\n確認対象: {input_path}"
        )

    data = pd.read_csv(
        input_path,
        dtype={USER_ID_COLUMN: "string", GROUP_COLUMN: "string"},
        encoding="utf-8-sig",
        low_memory=False,
    )
    require_columns(data, REQUIRED_COLUMNS, str(input_path))

    data = data.copy()
    data[USER_ID_COLUMN] = normalize_user_ids(data[USER_ID_COLUMN])
    data[GROUP_COLUMN] = data[GROUP_COLUMN].astype("string").str.strip()
    data[USAGE_DAYS_COLUMN] = pd.to_numeric(
        data[USAGE_DAYS_COLUMN], errors="coerce"
    )

    invalid_user = data[USER_ID_COLUMN].isna()
    invalid_group = ~data[GROUP_COLUMN].isin(GROUP_ORDER)
    invalid_days = (
        data[USAGE_DAYS_COLUMN].isna()
        | data[USAGE_DAYS_COLUMN].lt(1)
        | data[USAGE_DAYS_COLUMN].mod(1).ne(0)
    )
    if invalid_user.any() or invalid_group.any() or invalid_days.any():
        raise ValueError(
            "入力CSVに分析できない行があります。"
            f" user_id不正={int(invalid_user.sum())}行 /"
            f" 群不正={int(invalid_group.sum())}行 /"
            f" 利用日数不正={int(invalid_days.sum())}行"
        )

    data[USAGE_DAYS_COLUMN] = data[USAGE_DAYS_COLUMN].astype(int)

    duplicated = data[USER_ID_COLUMN].duplicated(keep=False)
    if duplicated.any():
        raise ValueError(
            "同じuser_idが複数行に存在します。No16のユーザー単位出力を"
            f"確認してください: {int(duplicated.sum())}行"
        )

    group_counts = data[GROUP_COLUMN].value_counts()
    for group_name in GROUP_ORDER:
        if int(group_counts.get(group_name, 0)) == 0:
            raise ValueError(f"{group_name}のユーザーが存在しません。")

    return data


def nearest_available_day(
    target_day: int,
    active_days: list[int],
    rng: np.random.Generator,
) -> int:
    """利用可能な日のうち、目標利用日数に最も近い日を返す。"""
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


def select_balanced_users(
    user_day: pd.DataFrame,
    random_seed: int = RANDOM_SEED,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """購買経験群を基準に、利用日数の近い未経験群を同数抽出する。"""
    experienced = user_day.loc[
        user_day[GROUP_COLUMN].eq(EXPERIENCED_GROUP)
    ].copy()
    unexperienced = user_day.loc[
        user_day[GROUP_COLUMN].eq(UNEXPERIENCED_GROUP)
    ].copy()

    if len(unexperienced) < len(experienced):
        raise ValueError(
            "購買未経験群の人数が購買経験群より少ないため、同数抽出できません。"
        )

    rng = np.random.default_rng(random_seed)

    # 利用日数ごとの候補行番号を用意し、同じ日数の中ではランダム抽出する。
    candidate_buckets: dict[int, list[int]] = {}
    for usage_day, indices in unexperienced.groupby(USAGE_DAYS_COLUMN).groups.items():
        shuffled = np.asarray(list(indices), dtype=object)
        rng.shuffle(shuffled)
        candidate_buckets[int(usage_day)] = shuffled.tolist()

    active_days = sorted(candidate_buckets)
    selected_control_indices: list[object] = []
    internal_match_rows: list[dict[str, int]] = []

    # 利用日数の大きい経験群ユーザーから処理し、希少な高利用層を先に確保する。
    target_rows = experienced.sort_values(
        [USAGE_DAYS_COLUMN, USER_ID_COLUMN],
        ascending=[False, True],
    )

    for _, target in target_rows.iterrows():
        target_day = int(target[USAGE_DAYS_COLUMN])
        selected_day = nearest_available_day(target_day, active_days, rng)
        selected_index = candidate_buckets[selected_day].pop()
        selected_control_indices.append(selected_index)
        internal_match_rows.append(
            {
                "基準利用日数": target_day,
                "抽出ユーザー利用日数": selected_day,
                "利用日数差": selected_day - target_day,
            }
        )

        if not candidate_buckets[selected_day]:
            del candidate_buckets[selected_day]
            delete_position = bisect_left(active_days, selected_day)
            if (
                delete_position >= len(active_days)
                or active_days[delete_position] != selected_day
            ):
                raise RuntimeError("利用日数候補の管理に不整合があります。")
            active_days.pop(delete_position)

    selected_unexperienced = unexperienced.loc[selected_control_indices].copy()
    if len(selected_unexperienced) != len(experienced):
        raise RuntimeError("条件調整後の二群の人数が一致しません。")

    selected = pd.concat(
        [experienced, selected_unexperienced],
        ignore_index=True,
        sort=False,
    )
    selected["抽出シード"] = random_seed
    selected = selected.sort_values(
        [GROUP_COLUMN, USAGE_DAYS_COLUMN, USER_ID_COLUMN],
        ascending=[True, False, True],
    ).reset_index(drop=True)

    internal_match = pd.DataFrame(internal_match_rows)
    return selected, internal_match


def summarize_usage_days(
    data: pd.DataFrame,
    stage: str,
) -> pd.DataFrame:
    """二群の利用日数を記述統計で要約する。"""
    rows: list[dict[str, object]] = []
    for group_name in GROUP_ORDER:
        values = data.loc[
            data[GROUP_COLUMN].eq(group_name), USAGE_DAYS_COLUMN
        ].astype(float)
        if values.empty:
            raise ValueError(f"{stage}の{group_name}に利用日数がありません。")
        rows.append(
            {
                "段階": stage,
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


def standardized_mean_difference(data: pd.DataFrame) -> float:
    """条件調整後の利用日数について標準化平均差を算出する。"""
    experienced = data.loc[
        data[GROUP_COLUMN].eq(EXPERIENCED_GROUP), USAGE_DAYS_COLUMN
    ].astype(float)
    unexperienced = data.loc[
        data[GROUP_COLUMN].eq(UNEXPERIENCED_GROUP), USAGE_DAYS_COLUMN
    ].astype(float)

    pooled_variance = (experienced.var(ddof=1) + unexperienced.var(ddof=1)) / 2
    if pooled_variance == 0:
        return 0.0 if experienced.mean() == unexperienced.mean() else np.inf
    return float(
        (experienced.mean() - unexperienced.mean()) / np.sqrt(pooled_variance)
    )


def build_distribution_table(selected: pd.DataFrame) -> pd.DataFrame:
    """条件調整後の利用日数別人数・割合を二群で比較する。"""
    count_table = (
        selected.groupby([USAGE_DAYS_COLUMN, GROUP_COLUMN])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=GROUP_ORDER, fill_value=0)
        .sort_index()
    )
    result = count_table.reset_index().rename(
        columns={
            EXPERIENCED_GROUP: "購買経験群_人数",
            UNEXPERIENCED_GROUP: "購買未経験群_人数",
        }
    )
    experienced_total = int(result["購買経験群_人数"].sum())
    unexperienced_total = int(result["購買未経験群_人数"].sum())
    result["購買経験群_割合（%）"] = (
        result["購買経験群_人数"] / experienced_total * 100
    )
    result["購買未経験群_割合（%）"] = (
        result["購買未経験群_人数"] / unexperienced_total * 100
    )
    result["割合差（pt）"] = (
        result["購買経験群_割合（%）"]
        - result["購買未経験群_割合（%）"]
    )
    return result


def build_quality_table(
    original: pd.DataFrame,
    selected: pd.DataFrame,
    internal_match: pd.DataFrame,
    random_seed: int,
) -> pd.DataFrame:
    """人数一致と利用日数の近さを確認する指標を作る。"""
    before_counts = original[GROUP_COLUMN].value_counts()
    after_counts = selected[GROUP_COLUMN].value_counts()
    smd = standardized_mean_difference(selected)

    checks: list[dict[str, object]] = [
        {
            "確認項目": "抽出方法",
            "値": "利用日数の最近傍・重複なし抽出",
            "判定": "参考",
        },
        {
            "確認項目": "抽出シード",
            "値": random_seed,
            "判定": "再現用",
        },
        {
            "確認項目": "条件調整前_購買経験群人数",
            "値": int(before_counts.get(EXPERIENCED_GROUP, 0)),
            "判定": "参考",
        },
        {
            "確認項目": "条件調整前_購買未経験群人数",
            "値": int(before_counts.get(UNEXPERIENCED_GROUP, 0)),
            "判定": "参考",
        },
        {
            "確認項目": "条件調整後_購買経験群人数",
            "値": int(after_counts.get(EXPERIENCED_GROUP, 0)),
            "判定": "一致"
            if after_counts.get(EXPERIENCED_GROUP, 0)
            == after_counts.get(UNEXPERIENCED_GROUP, 0)
            else "要確認",
        },
        {
            "確認項目": "条件調整後_購買未経験群人数",
            "値": int(after_counts.get(UNEXPERIENCED_GROUP, 0)),
            "判定": "一致"
            if after_counts.get(EXPERIENCED_GROUP, 0)
            == after_counts.get(UNEXPERIENCED_GROUP, 0)
            else "要確認",
        },
        {
            "確認項目": "利用日数が完全一致した抽出数",
            "値": int(internal_match["利用日数差"].eq(0).sum()),
            "判定": "参考",
        },
        {
            "確認項目": "利用日数差の絶対値平均",
            "値": float(internal_match["利用日数差"].abs().mean()),
            "判定": "小さいほど良い",
        },
        {
            "確認項目": "利用日数差の絶対値最大",
            "値": int(internal_match["利用日数差"].abs().max()),
            "判定": "小さいほど良い",
        },
        {
            "確認項目": "条件調整後_利用日数の標準化平均差（SMD）",
            "値": smd,
            "判定": "良好"
            if np.isfinite(smd) and abs(smd) < SMD_WARNING_THRESHOLD
            else "要確認",
        },
    ]
    return pd.DataFrame(checks)


def save_outputs(
    original: pd.DataFrame,
    selected: pd.DataFrame,
    internal_match: pd.DataFrame,
    output_dir: Path,
    random_seed: int,
) -> list[Path]:
    """条件調整後の対象者と確認表を保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = pd.concat(
        [
            summarize_usage_days(original, "条件調整前"),
            summarize_usage_days(selected, "条件調整後"),
        ],
        ignore_index=True,
    )
    distribution = build_distribution_table(selected)
    quality = build_quality_table(
        original=original,
        selected=selected,
        internal_match=internal_match,
        random_seed=random_seed,
    )

    output_paths = [
        output_dir / "01_条件調整後ユーザー一覧.csv",
        output_dir / "02_条件調整前後要約.csv",
        output_dir / "03_利用日数分布確認.csv",
        output_dir / "04_条件調整品質確認.csv",
    ]
    selected.to_csv(output_paths[0], index=False, encoding="utf-8-sig")
    summary.to_csv(
        output_paths[1], index=False, encoding="utf-8-sig", float_format="%.6f"
    )
    distribution.to_csv(
        output_paths[2], index=False, encoding="utf-8-sig", float_format="%.6f"
    )
    quality.to_csv(
        output_paths[3], index=False, encoding="utf-8-sig", float_format="%.6f"
    )
    return output_paths


def run(
    input_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    random_seed: int = RANDOM_SEED,
) -> list[Path]:
    """No16の結果から人数・利用日数を揃えた二群を抽出する。"""
    project_dir = Path(__file__).resolve().parents[1]
    workspace_dir = project_dir.parent

    if input_path is None:
        input_path = (
            workspace_dir
            / SOURCE_PROJECT_DIR_NAME
            / "Output"
            / SOURCE_FILENAME
        )
    if output_dir is None:
        output_dir = project_dir / "Output"

    original = read_user_usage_days(input_path)
    selected, internal_match = select_balanced_users(
        original,
        random_seed=random_seed,
    )
    output_paths = save_outputs(
        original=original,
        selected=selected,
        internal_match=internal_match,
        output_dir=output_dir,
        random_seed=random_seed,
    )

    before_counts = original[GROUP_COLUMN].value_counts()
    after_counts = selected[GROUP_COLUMN].value_counts()
    smd = standardized_mean_difference(selected)

    print("\n利用日数と人数を揃えたユーザー抽出が完了しました。")
    print(
        "条件調整前: "
        f"購買経験群={int(before_counts[EXPERIENCED_GROUP]):,}人 / "
        f"購買未経験群={int(before_counts[UNEXPERIENCED_GROUP]):,}人"
    )
    print(
        "条件調整後: "
        f"購買経験群={int(after_counts[EXPERIENCED_GROUP]):,}人 / "
        f"購買未経験群={int(after_counts[UNEXPERIENCED_GROUP]):,}人"
    )
    print(f"条件調整後の利用日数SMD: {smd:.6f}")
    if not np.isfinite(smd) or abs(smd) >= SMD_WARNING_THRESHOLD:
        print(
            "注意: 利用日数のSMDが0.10以上です。"
            "02・03・04の確認表を見てから後続分析へ進んでください。"
        )
    print(f"保存先: {output_dir}")
    return output_paths


def main() -> None:
    run()


if __name__ == "__main__":
    main()
