# 解析スクリプト（現時点の最新版）

SSDから復元したPythonコードのうち、最終的に実施した本分析の流れに対応する No4〜No13 のみを保管しています。

## 対応関係

| No. | 対象 | 内容 | スクリプト |
|---|---|---|---|
| No4 | セブンイレブン | 確定商品の購買記録を商品別CSVへ抽出 | `No4_extract_confirmed_products_seven/Input/extract_confirmed_products_seven.py` |
| No5 | ローソン | 確定商品の購買記録を商品別CSVへ抽出 | `No5_extract_confirmed_products_lawson/Input/extract_confirmed_products_lawson.py` |
| No6 | ファミリーマート | 確定商品の購買記録を商品別CSVへ抽出 | `No6_extract_confirmed_products_familymart/Input/extract_confirmed_products_familymart.py` |
| No7 | セブンイレブン | 属性別の購買記録数・対象者数・個別商品購買指数を算出 | `No7_purchase_index_seven/Input/calculate_purchase_index_seven.py` |
| No8 | ローソン | 属性別の購買記録数・対象者数・個別商品購買指数を算出 | `No8_purchase_index_lawson/Input/calculate_purchase_index_lawson.py` |
| No9 | ファミリーマート | 属性別の購買記録数・対象者数・個別商品購買指数を算出 | `No9_purchase_index_familymart/Input/calculate_purchase_index_familymart.py` |
| No10 | セブンイレブン | 個別商品購買指数を平均し、対応商品群購買指数を算出 | `No10_group_purchase_index_seven/Input/calculate_group_purchase_index_seven.py` |
| No11 | ローソン | 個別商品購買指数を平均し、対応商品群購買指数を算出 | `No11_group_purchase_index_lawson/Input/calculate_group_purchase_index_lawson.py` |
| No12 | ファミリーマート | 個別商品購買指数を平均し、対応商品群購買指数を算出 | `No12_group_purchase_index_familymart/Input/calculate_group_purchase_index_familymart.py` |
| No13 | 3社統合 | 全セルの指数から閾値を算出し、適切さを3段階で評価 | `No13_classify_group_purchase_index/Input/classify_group_purchase_index.py` |

## 実行順

1. No4〜No6：確定商品のデータ抽出
2. No7〜No9：個別商品購買指数の算出
3. No10〜No12：対応商品群購買指数の算出
4. No13：全社共通の閾値による適切さの評価

各スクリプトは、従来のCode Editor上の構成に合わせ、各Noフォルダの `Input` 内に置いてあります。スクリプトが参照する前段階のNoフォルダも、同じ親フォルダ配下に配置する想定です。

## 保管対象外

- `extract_confirmed_products.py`：3社別・除外表現対応版より前の汎用版
- `precheck_product_search.py`：本分析 No4〜No13 より前の表示名確認用スクリプト

## 取扱上の注意

- このリポジトリには、Zaimの元データ、商品別の抽出データ、分析結果、Excelファイル、認証情報を保存しません。
- S3からデータを取得する処理は、承認された会社環境で、その環境用の処理を各スクリプトの所定箇所へ設定して使用します。
- アクセスキー等の認証情報をPythonファイルへ直接記載しないでください。
- `Input` 内はPythonコードのみ、`Output` は全内容をGit管理対象外にしています。
