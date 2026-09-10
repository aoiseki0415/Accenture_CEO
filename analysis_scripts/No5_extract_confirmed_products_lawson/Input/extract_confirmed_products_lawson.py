"""ローソンの確定済み商品を抽出する。Excel操作にopenpyxlは使用しない。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET

import pandas as pd


# =====================================================================
# 【ユーザー設定欄】コンビニごとに変更する
# =====================================================================
INPUT_EXCEL_NAME = "商品確認.xlsx"

# No5では、ローソンの3つの健康ニーズを一括処理する。
TARGET_SHEETS = {
    "栄養バランス": "ローソン_栄養バランス",
    "脂質": "ローソン_脂質",
    "エネルギー": "ローソン_エネルギー",
}

# 購買データ内の列名
PURCHASE_DATE_COLUMN = "date"
PRODUCT_NAME_COLUMN = "name"


# =====================================================================
# 【ユーザー記入欄】ローソンのS3読込テンプレートで data1～data5 を作成する
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


# Excelの列名
EXCEL_PRODUCT_COLUMN = "商品名"
EXCEL_TERM_COLUMNS = [
    "最低限の表現要素1",
    "最低限の表現要素2",
    "最低限の表現要素3",
]
EXCEL_OPERATOR_COLUMN = "結合条件（AND/OR）"
EXCEL_EXCLUDE_COLUMNS = [
    "除外表現1",
    "除外表現2",
    "除外表現3",
]
EXCEL_MATCH_RESULT_COLUMN = "照合結果"
EXCEL_FIRST_DATE_COLUMN = "最初に記録された日"
EXCEL_LAST_DATE_COLUMN = "最後に記録された日"
EXCEL_ROW_COUNT_COLUMN = "データ数"
CONFIRMED_VALUE = "確定"


# xlsx内部で使われるXML名前空間
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", NS_MAIN)
ET.register_namespace("r", NS_REL)


def qname(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def parse_xml_preserving_namespaces(xml_data: bytes) -> ET.Element:
    """書き戻し時にExcel固有のXML接頭辞が失われないように解析する。"""
    for _, namespace in ET.iterparse(
        BytesIO(xml_data), events=("start-ns",)
    ):
        prefix, uri = namespace
        # ElementTreeが予約する接頭辞は登録しない。
        if not re.fullmatch(r"ns\d+", prefix or ""):
            ET.register_namespace(prefix or "", uri)
    return ET.fromstring(xml_data)


def combine_purchase_data(dataframes: list[pd.DataFrame]) -> pd.DataFrame:
    """5期間分を全列のまま縦結合し、日付列を変換する。"""
    required_columns = {PURCHASE_DATE_COLUMN, PRODUCT_NAME_COLUMN}
    for number, data in enumerate(dataframes, start=1):
        missing = sorted(required_columns - set(data.columns))
        if missing:
            raise ValueError(f"data{number} に必要な列がありません: {missing}")

    expected_rows = sum(len(data) for data in dataframes)
    combined = pd.concat(dataframes, ignore_index=True, sort=False)
    if len(combined) != expected_rows:
        raise RuntimeError("結合前後の行数が一致しません。")

    combined[PURCHASE_DATE_COLUMN] = pd.to_datetime(
        combined[PURCHASE_DATE_COLUMN], errors="coerce"
    )
    print(f"5期間分を結合しました: {len(combined):,}行")
    return combined


def normalize_cell(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def make_search_mask(
    product_names: pd.Series,
    terms: list[str],
    operator: str,
    exclude_terms: list[str],
) -> pd.Series:
    """含める表現を検索し、除外表現を含む商品名を取り除く。"""
    active_terms = [term for term in terms if term]
    if not active_terms:
        raise ValueError("最低限の表現要素が1つも設定されていません。")

    masks = [
        product_names.str.contains(term, regex=False, na=False)
        for term in active_terms
    ]
    result = masks[0]
    if len(masks) > 1:
        operator = operator.upper()
        if operator not in {"AND", "OR"}:
            raise ValueError("表現要素が複数ある場合はANDまたはORが必要です。")

        for include_mask in masks[1:]:
            result = (
                result & include_mask
                if operator == "AND"
                else result | include_mask
            )

    # 除外表現は、いずれか1つでも含まれていたら除外する。
    active_exclude_terms = [term for term in exclude_terms if term]
    if active_exclude_terms:
        exclude_mask = product_names.str.contains(
            active_exclude_terms[0], regex=False, na=False
        )
        for exclude_term in active_exclude_terms[1:]:
            exclude_mask = exclude_mask | product_names.str.contains(
                exclude_term, regex=False, na=False
            )
        result = result & ~exclude_mask
    return result


def column_letters_to_number(letters: str) -> int:
    result = 0
    for character in letters:
        result = result * 26 + ord(character.upper()) - ord("A") + 1
    return result


def column_number_to_letters(number: int) -> str:
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def cell_column_number(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference)
    if not match:
        raise ValueError(f"不正なセル参照です: {reference}")
    return column_letters_to_number(match.group(1))


def read_shared_strings(archive: ZipFile) -> list[str]:
    """xlsxの共有文字列を読み込む。存在しない場合は空リストを返す。"""
    try:
        xml_data = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(xml_data)
    strings = []
    for item in root.findall(qname(NS_MAIN, "si")):
        texts = [node.text or "" for node in item.iter(qname(NS_MAIN, "t"))]
        strings.append("".join(texts))
    return strings


def get_target_sheet_path(archive: ZipFile, sheet_name: str) -> str:
    """タブ名からxlsx内部のワークシートXMLを特定する。"""
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationship_id = None
    sheet_names = []
    for sheet in workbook.findall(f".//{qname(NS_MAIN, 'sheet')}"):
        current_name = sheet.attrib.get("name", "")
        sheet_names.append(current_name)
        if current_name == sheet_name:
            relationship_id = sheet.attrib[qname(NS_REL, "id")]

    if relationship_id is None:
        raise ValueError(
            f"指定タブが見つかりません: {sheet_name}\n利用可能なタブ: {sheet_names}"
        )

    relationships = ET.fromstring(
        archive.read("xl/_rels/workbook.xml.rels")
    )
    for relationship in relationships.findall(
        qname(NS_PACKAGE_REL, "Relationship")
    ):
        if relationship.attrib.get("Id") == relationship_id:
            target = relationship.attrib["Target"].lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"
    raise ValueError("対象タブの内部ファイルを特定できませんでした。")


def get_cell_value(cell: ET.Element, shared_strings: list[str]) -> object:
    """セルXMLから表示値を取り出す。"""
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(
            node.text or "" for node in cell.iter(qname(NS_MAIN, "t"))
        )

    value_node = cell.find(qname(NS_MAIN, "v"))
    if value_node is None or value_node.text is None:
        return None
    value = value_node.text
    if cell_type == "s":
        return shared_strings[int(value)]
    if cell_type in {"str", "b"}:
        return value
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def read_target_sheet(
    input_excel_path: Path,
    sheet_name: str,
) -> tuple[str, ET.Element, list[dict[int, object]]]:
    """対象タブを読み、内部パス・XML・行データを返す。"""
    with ZipFile(input_excel_path, "r") as archive:
        sheet_path = get_target_sheet_path(archive, sheet_name)
        root = parse_xml_preserving_namespaces(archive.read(sheet_path))
        shared_strings = read_shared_strings(archive)

    rows = []
    sheet_data = root.find(qname(NS_MAIN, "sheetData"))
    if sheet_data is None:
        raise ValueError("対象タブに表データがありません。")

    for row in sheet_data.findall(qname(NS_MAIN, "row")):
        row_values = {}
        for cell in row.findall(qname(NS_MAIN, "c")):
            row_values[cell_column_number(cell.attrib["r"])] = get_cell_value(
                cell, shared_strings
            )
        rows.append(row_values)
    return sheet_path, root, rows


def find_header_columns(rows: list[dict[int, object]]) -> dict[str, int]:
    """1行目から必要な列番号を取得する。"""
    if not rows:
        raise ValueError("入力Excelの対象タブが空です。")
    headers = {
        normalize_cell(value): column
        for column, value in rows[0].items()
        if normalize_cell(value)
    }
    required = [
        EXCEL_PRODUCT_COLUMN,
        *EXCEL_TERM_COLUMNS,
        EXCEL_OPERATOR_COLUMN,
        *EXCEL_EXCLUDE_COLUMNS,
        EXCEL_MATCH_RESULT_COLUMN,
        EXCEL_FIRST_DATE_COLUMN,
        EXCEL_LAST_DATE_COLUMN,
        EXCEL_ROW_COUNT_COLUMN,
    ]
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(f"入力Excelに必要な列がありません: {missing}")
    return headers


def find_or_create_row(sheet_data: ET.Element, row_number: int) -> ET.Element:
    for row in sheet_data.findall(qname(NS_MAIN, "row")):
        if int(row.attrib["r"]) == row_number:
            return row
    new_row = ET.Element(qname(NS_MAIN, "row"), {"r": str(row_number)})
    sheet_data.append(new_row)
    return new_row


def find_or_create_cell(
    row: ET.Element,
    row_number: int,
    column_number: int,
) -> ET.Element:
    reference = f"{column_number_to_letters(column_number)}{row_number}"
    cells = row.findall(qname(NS_MAIN, "c"))
    for cell in cells:
        if cell.attrib.get("r") == reference:
            return cell

    new_cell = ET.Element(qname(NS_MAIN, "c"), {"r": reference})
    for position, cell in enumerate(cells):
        if cell_column_number(cell.attrib["r"]) > column_number:
            row.insert(position, new_cell)
            break
    else:
        row.append(new_cell)
    return new_cell


def set_sheet_cell(
    root: ET.Element,
    row_number: int,
    column_number: int,
    value: object,
) -> None:
    """既存の書式を残しながら対象セルの値だけを更新する。"""
    sheet_data = root.find(qname(NS_MAIN, "sheetData"))
    if sheet_data is None:
        raise ValueError("対象タブに表データがありません。")
    row = find_or_create_row(sheet_data, row_number)
    cell = find_or_create_cell(row, row_number, column_number)

    for child in list(cell):
        if child.tag in {
            qname(NS_MAIN, "v"),
            qname(NS_MAIN, "is"),
            qname(NS_MAIN, "f"),
        }:
            cell.remove(child)

    if value is None:
        cell.attrib.pop("t", None)
    elif isinstance(value, (int, float)):
        cell.attrib.pop("t", None)
        ET.SubElement(cell, qname(NS_MAIN, "v")).text = str(value)
    else:
        cell.attrib["t"] = "inlineStr"
        inline = ET.SubElement(cell, qname(NS_MAIN, "is"))
        ET.SubElement(inline, qname(NS_MAIN, "t")).text = str(value)


def save_updated_workbook(
    input_path: Path,
    output_path: Path,
    updated_sheets: dict[str, ET.Element],
) -> None:
    """他のタブを保持し、処理した3タブのXMLだけを差し替える。"""
    updated_xml = {
        sheet_path: ET.tostring(
            root, encoding="utf-8", xml_declaration=True
        )
        for sheet_path, root in updated_sheets.items()
    }
    with ZipFile(input_path, "r") as source, ZipFile(
        output_path, "w", compression=ZIP_DEFLATED
    ) as destination:
        for file_info in source.infolist():
            content = updated_xml.get(
                file_info.filename, source.read(file_info.filename)
            )
            destination.writestr(file_info, content)


def process_confirmed_products(
    purchase_data: pd.DataFrame,
    input_excel_path: Path,
    output_dir: Path,
) -> Path:
    """3つの健康ニーズを処理し、商品別CSVと集計済みExcelを作る。"""
    if not input_excel_path.exists():
        raise FileNotFoundError(f"入力Excelが見つかりません: {input_excel_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    # 処理開始時に、3つの健康ニーズ用フォルダをすべて作る。
    health_output_dirs = {
        health_need: output_dir / health_need
        for health_need in TARGET_SHEETS
    }
    for health_output_dir in health_output_dirs.values():
        health_output_dir.mkdir(parents=True, exist_ok=True)

    searchable_names = purchase_data[PRODUCT_NAME_COLUMN].fillna("").astype(str)
    mapping_columns = [
        "商品番号",
        "商品名",
        "出力ファイル名",
        "最低限の表現要素1",
        "最低限の表現要素2",
        "最低限の表現要素3",
        "結合条件",
        "除外表現1",
        "除外表現2",
        "除外表現3",
        "抽出件数",
        "抽出されたZaim商品名の種類数",
        "抽出されたZaim商品名",
    ]
    updated_sheets: dict[str, ET.Element] = {}

    for health_need, sheet_name in TARGET_SHEETS.items():
        print(f"\n===== {health_need}｜{sheet_name} =====")
        health_output_dir = health_output_dirs[health_need]

        sheet_path, sheet_root, rows = read_target_sheet(
            input_excel_path, sheet_name
        )
        columns = find_header_columns(rows)
        mapping_rows = []
        confirmed_number = 0

        # rows[0]は見出し。Excel上の行番号はリスト位置+1になる。
        for row_index, row_values in enumerate(rows[1:], start=2):
            match_result = normalize_cell(
                row_values.get(columns[EXCEL_MATCH_RESULT_COLUMN])
            )
            if match_result != CONFIRMED_VALUE:
                continue

            confirmed_number += 1
            product_number = f"{confirmed_number:03d}"
            product_label = normalize_cell(
                row_values.get(columns[EXCEL_PRODUCT_COLUMN])
            )
            terms = [
                normalize_cell(row_values.get(columns[column]))
                for column in EXCEL_TERM_COLUMNS
            ]
            operator = normalize_cell(
                row_values.get(columns[EXCEL_OPERATOR_COLUMN])
            )
            exclude_terms = [
                normalize_cell(row_values.get(columns[column]))
                for column in EXCEL_EXCLUDE_COLUMNS
            ]

            try:
                mask = make_search_mask(
                    searchable_names,
                    terms,
                    operator,
                    exclude_terms,
                )
            except ValueError as error:
                raise ValueError(
                    f"{sheet_name}のExcel {row_index}行目"
                    f"（{product_label}）の検索条件に問題があります。"
                ) from error

            extracted = purchase_data.loc[mask].copy()
            extracted = extracted.sort_values(
                PURCHASE_DATE_COLUMN, na_position="last"
            )
            output_filename = f"product_{product_number}.csv"
            extracted.to_csv(
                health_output_dir / output_filename,
                index=False,
                encoding="utf-8-sig",
            )

            valid_dates = extracted[PURCHASE_DATE_COLUMN].dropna()
            first_date = valid_dates.min() if not valid_dates.empty else None
            last_date = valid_dates.max() if not valid_dates.empty else None
            row_count = len(extracted)

            set_sheet_cell(
                sheet_root,
                row_index,
                columns[EXCEL_FIRST_DATE_COLUMN],
                first_date.strftime("%Y-%m-%d")
                if first_date is not None
                else None,
            )
            set_sheet_cell(
                sheet_root,
                row_index,
                columns[EXCEL_LAST_DATE_COLUMN],
                last_date.strftime("%Y-%m-%d")
                if last_date is not None
                else None,
            )
            set_sheet_cell(
                sheet_root,
                row_index,
                columns[EXCEL_ROW_COUNT_COLUMN],
                row_count,
            )

            matched_names = sorted(
                extracted[PRODUCT_NAME_COLUMN]
                .dropna()
                .astype(str)
                .unique()
                .tolist()
            )
            mapping_rows.append(
                {
                    "商品番号": product_number,
                    "商品名": product_label,
                    "出力ファイル名": output_filename,
                    "最低限の表現要素1": terms[0],
                    "最低限の表現要素2": terms[1],
                    "最低限の表現要素3": terms[2],
                    "結合条件": operator.upper()
                    if len([term for term in terms if term]) > 1
                    else "",
                    "除外表現1": exclude_terms[0],
                    "除外表現2": exclude_terms[1],
                    "除外表現3": exclude_terms[2],
                    "抽出件数": row_count,
                    "抽出されたZaim商品名の種類数": len(matched_names),
                    "抽出されたZaim商品名": " | ".join(matched_names),
                }
            )
            print(
                f"[{product_number}] {product_label}: "
                f"{row_count:,}行 / 商品名{len(matched_names):,}種類"
            )

        mapping_path = health_output_dir / "product_file_mapping.csv"
        pd.DataFrame(mapping_rows, columns=mapping_columns).to_csv(
            mapping_path, index=False, encoding="utf-8-sig"
        )
        updated_sheets[sheet_path] = sheet_root
        print(f"確定商品数: {confirmed_number:,}")
        print(f"保存先: {health_output_dir}")

    completed_excel_path = output_dir / f"completed_{input_excel_path.name}"
    save_updated_workbook(
        input_excel_path,
        completed_excel_path,
        updated_sheets,
    )
    print(f"集計済みExcel: {completed_excel_path}")
    return completed_excel_path


def run(
    data1: pd.DataFrame,
    data2: pd.DataFrame,
    data3: pd.DataFrame,
    data4: pd.DataFrame,
    data5: pd.DataFrame,
) -> Path:
    project_dir = Path(__file__).resolve().parents[1]
    input_excel_path = project_dir / "Input" / INPUT_EXCEL_NAME
    output_dir = project_dir / "Output"
    purchase_data = combine_purchase_data([data1, data2, data3, data4, data5])
    return process_confirmed_products(
        purchase_data, input_excel_path, output_dir
    )


def main() -> None:
    data_names = ["data1", "data2", "data3", "data4", "data5"]
    missing = [name for name in data_names if name not in globals()]
    if missing:
        raise RuntimeError(
            "ユーザー記入欄で次のDataFrameを作成してください: "
            + ", ".join(missing)
        )
    run(*(globals()[name] for name in data_names))


if __name__ == "__main__":
    main()
