"""比較群の購買経験群・購買未経験群で、惣菜類に求める役割を比較する。

No22で人数とセブン利用日数を揃えた男女40代・50代について、
No20と全く同じ母集団・商品分類・主分析・感度分析を行う。

分析条件
--------
* 母集団: JICFS Lv4「惣菜類」
* 一食完結型: No20と同じ一食完結型キーワードに該当し、
  食事補完型優先キーワードに該当しない商品
* 食事補完型: 上記以外の惣菜類
* 主分析: 「栄養バランスを調整したい」対応商品を含む
* 感度分析: 対応商品を除外する

入力
----
1. このファイル内で用意する、JICFS Lv4・Lv6を含むDataFrame
   ``data1`` ～ ``data5``
2. No22の ``Output/01_条件調整後ユーザー一覧.csv``
3. No4の ``Output/栄養バランス`` にある商品別CSVと対応表

出力
----
No23の ``Output`` に、No20と同じ構成の集計CSV・分類一覧・Figureを保存する。
割合Figureの縦軸はNo20と同じ0～100%とし、色はNo20と同系統の別色にする。

注意
----
出力にはユーザーID、商品名、集計結果が含まれる。会社環境内だけで管理し、
個人PC、Notion、GitHub等へ保存・共有しないこと。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


SOURCE_ANALYSIS_SCRIPT = (
    "No20_compare_complete_meal_role/Input/compare_complete_meal_role.py"
)
BALANCED_USER_PROJECT_DIR_NAME = "No22_balance_usage_days_comparison_group"
BALANCED_USER_FILENAME = "01_条件調整後ユーザー一覧.csv"

# No20の紫・ピンクと対応しつつ、比較群であることを見分けられる淡色にする。
COMPARISON_GROUP_CHART_COLORS = ("#A58AC4", "#E6B2AF")


# =====================================================================
# 【ユーザー記入欄】S3読込テンプレートで data1～data5 を作成する
# =====================================================================
# No20と同じ、JICFS Lv4・Lv6を含むセブンイレブンの5期間分データを読む。
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


def load_shared_analysis(path: Path) -> ModuleType:
    """No20の分類・集計処理をそのまま読み込む。"""
    if not path.exists():
        raise FileNotFoundError(f"No20のスクリプトが見つかりません: {path}")
    spec = importlib.util.spec_from_file_location("no20_meal_role_shared", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"No20のスクリプトを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    data_names = ["data1", "data2", "data3", "data4", "data5"]
    missing = [name for name in data_names if name not in globals()]
    if missing:
        raise RuntimeError(
            "ユーザー記入欄で次のDataFrameを作成してください: "
            + ", ".join(missing)
        )

    project_dir = Path(__file__).resolve().parents[1]
    workspace_dir = project_dir.parent
    analysis = load_shared_analysis(workspace_dir / SOURCE_ANALYSIS_SCRIPT)

    # 分類ロジックはNo20と共有し、入力ユーザーとFigureの色だけを変える。
    analysis.SHARE_CHART_COLORS = COMPARISON_GROUP_CHART_COLORS
    balanced_user_path = (
        workspace_dir
        / BALANCED_USER_PROJECT_DIR_NAME
        / "Output"
        / BALANCED_USER_FILENAME
    )
    output_dir = project_dir / "Output"

    dataframes = [globals().pop(name) for name in data_names]
    analysis.run(
        dataframes=dataframes,
        balanced_user_path=balanced_user_path,
        output_dir=output_dir,
    )
    print("\n比較群の食事形態比較（No23）が完了しました。")


if __name__ == "__main__":
    main()
