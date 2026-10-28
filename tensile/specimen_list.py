# ======================================
# 試験片の一覧（台帳）
# ======================================
# 試験片の情報（寸法・メモ・結果など）を Google スプレッドシートに 1行ずつ保存する。
# スプレッドシート ＝ 試験片の「台帳」。1行目が見出し、2行目から 1行 ＝ 試験片1本。
#
# 画面（入力欄や一覧表）は ui_specimens.py で作っている。
# このファイルは「台帳の読み書き」と「入力値の整理」だけを受け持つ。

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

JST = ZoneInfo("Asia/Tokyo")

# ---------- 列（スプレッドシートの見出し） ----------
STATUS_OPTIONS = ["未試験", "解析済み", "失敗"]
DETAIL_POSITIONS = ["上部", "中央", "下部"]

WIDTH_DETAIL_COLUMNS = [f"幅 {p}{i}" for p in DETAIL_POSITIONS for i in range(1, 4)]
THICKNESS_DETAIL_COLUMNS = [f"厚み {p}{i}" for p in DETAIL_POSITIONS for i in range(1, 4)]
GAUGE_DETAIL_COLUMNS = [f"ゲージ長さ {i}" for i in range(1, 4)]

RESULT_COLUMNS = ["引張強さ [MPa]", "破断ひずみ [-]", "弾性率 [GPa]", "AEイベント数"]

# Google ドライブに保存した元ファイル（ID はアプリが読み直すときに使う。人が見るのはリンク）
FILE_COLUMNS = ["SSファイル", "AEファイル", "データフォルダ"]
FILE_ID_COLUMNS = ["SSファイルID", "AEファイルID", "フォルダID"]

# 元ファイルをドライブに保存できたか（解析のときに書く。未解析は空欄）
#   保存済み：保存できた　保存失敗：保存しようとしてエラーになった　保存なし：ドライブの設定がなかった
DRIVE_STATUS_COLUMN = "ドライブ保存"
DRIVE_STATUS_OPTIONS = ["保存済み", "保存失敗", "保存なし"]

COLUMNS = (
    [
        "ID",
        "試験片名",
        "状態",
        "試験日",
        "材料の種類",
        "板の名前",
        "端から",
        "角度",
        "引張速度 [mm/min]",
        "幅 [mm]",
        "厚み [mm]",
        "ゲージ長さ [mm]",
    ]
    + RESULT_COLUMNS
    + ["メモ", "担当者", "登録日時", "更新日時", "解析日時"]
    + [DRIVE_STATUS_COLUMN]
    + FILE_COLUMNS
    + WIDTH_DETAIL_COLUMNS
    + THICKNESS_DETAIL_COLUMNS
    + GAUGE_DETAIL_COLUMNS
    + FILE_ID_COLUMNS
)

# 数値として扱う列（それ以外は文字）
NUMBER_COLUMNS = (
    ["ID", "引張速度 [mm/min]", "幅 [mm]", "厚み [mm]", "ゲージ長さ [mm]"]
    + RESULT_COLUMNS
    + WIDTH_DETAIL_COLUMNS
    + THICKNESS_DETAIL_COLUMNS
    + GAUGE_DETAIL_COLUMNS
)


# ---------- 入力値の整理 ----------
def now_text():
    """いまの日本時間を「2026-10-14 15:30」の形の文字にする。"""
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def parse_detail_values(texts, name):
    """詳細寸法の入力（文字）を数値にする。空欄は None のまま。

    数値でない・0以下のときは ValueError（画面にそのまま表示する文）を出す。
    """
    values = []
    for text in texts:
        text = "" if text is None else str(text).strip()
        if text == "":
            values.append(None)
            continue
        try:
            value = float(text)
        except ValueError:
            raise ValueError(f"{name}の詳細寸法に、数値でない値「{text}」があります") from None
        if value <= 0:
            raise ValueError(f"{name}の詳細寸法は0より大きい値を入力してください")
        values.append(value)
    return values


def dimension_value(direct, details):
    """使う寸法：詳細寸法に1つでも入力があれば「入力した分だけの平均」、なければ直接入力の値。

    Excel 出力（概要シート）と同じ決め方。どちらもなければ None。
    """
    entered = [v for v in details if v is not None]
    if entered:
        return float(np.mean(entered))
    if direct is None or direct == "":
        return None
    return float(direct)


def build_record(form, existing=None):
    """入力フォームの値（辞書）から、台帳の1行（辞書）を作る。

    form のキー：試験日（date か None）、材料の種類、板の名前、端から、試験片名、角度、
                引張速度 [mm/min]、幅 [mm]、厚み [mm]、ゲージ長さ [mm]（直接入力。None 可）、
                幅の詳細・厚みの詳細・ゲージ長さの詳細（文字のリスト）、メモ、担当者、状態（編集のときだけ）
    existing：編集のときの元の行。ID・登録日時・結果の列はそのまま引き継ぐ。
    """
    width_details = parse_detail_values(form.get("幅の詳細", [""] * 9), "幅")
    thickness_details = parse_detail_values(form.get("厚みの詳細", [""] * 9), "厚み")
    gauge_details = parse_detail_values(form.get("ゲージ長さの詳細", [""] * 3), "ゲージ長さ")

    for name in ["引張速度 [mm/min]", "幅 [mm]", "厚み [mm]", "ゲージ長さ [mm]"]:
        value = form.get(name)
        if value is not None and value != "" and float(value) <= 0:
            raise ValueError(f"{name.split(' ')[0]}は0より大きい値を入力してください")

    record = dict(existing) if existing else {column: "" for column in COLUMNS}
    test_date = form.get("試験日")
    record.update(
        {
            "試験日": test_date.strftime("%Y-%m-%d") if test_date else "",
            "材料の種類": clean_text(form.get("材料の種類")),
            "板の名前": clean_text(form.get("板の名前")),
            "端から": clean_text(form.get("端から")),
            "試験片名": clean_text(form.get("試験片名")),
            "角度": clean_text(form.get("角度")),
            "引張速度 [mm/min]": blank_if_none(form.get("引張速度 [mm/min]")),
            "幅 [mm]": blank_if_none(dimension_value(form.get("幅 [mm]"), width_details)),
            "厚み [mm]": blank_if_none(dimension_value(form.get("厚み [mm]"), thickness_details)),
            "ゲージ長さ [mm]": blank_if_none(dimension_value(form.get("ゲージ長さ [mm]"), gauge_details)),
            "メモ": clean_text(form.get("メモ")),
            "担当者": clean_text(form.get("担当者")),
            "更新日時": now_text(),
        }
    )
    if form.get("状態"):
        record["状態"] = form["状態"]
    for columns, values in [
        (WIDTH_DETAIL_COLUMNS, width_details),
        (THICKNESS_DETAIL_COLUMNS, thickness_details),
        (GAUGE_DETAIL_COLUMNS, gauge_details),
    ]:
        for column, value in zip(columns, values):
            record[column] = blank_if_none(value)
    return record


def clean_text(value):
    return "" if value is None else str(value).strip()


def blank_if_none(value):
    """None は空欄（""）に。スプレッドシートには空欄で書く。"""
    if value is None:
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    return value


def auto_name(specimen_id):
    """試験片名が空欄のときの自動の名前（No.0001 など）。"""
    return f"No.{int(specimen_id):04d}"


def speed_setting(value):
    """データから求めたクロスヘッド速度を、有効数字2桁に丸めて設定値にする（10.03 → 10）。"""
    return float(f"{value:.2g}")


def record_with_analysis(record, dimensions, details, ss_result, ae_result, files=None, drive_status=None):
    """解析の結果を台帳の1行に書き込む（元の辞書は変えずに、新しい辞書を返す）。

    dimensions：解析に使った (幅, 厚み, ゲージ長さ)
    details：詳細寸法 (幅の9個, 厚みの9個, ゲージ長さの3個)。数値か None
    files：Google ドライブに保存したファイルの情報（保存しなかったときは None。前回のリンクが残る）
    drive_status：ドライブ保存の状態（DRIVE_STATUS_OPTIONS のどれか）。None なら前の値のまま
    """
    record = dict(record)
    record["幅 [mm]"], record["厚み [mm]"], record["ゲージ長さ [mm]"] = [float(v) for v in dimensions]
    for columns, values in zip(
        [WIDTH_DETAIL_COLUMNS, THICKNESS_DETAIL_COLUMNS, GAUGE_DETAIL_COLUMNS], details
    ):
        for column, value in zip(columns, values):
            record[column] = blank_if_none(value)
    record["引張強さ [MPa]"] = float(ss_result["max_stress[MPa]"])
    record["破断ひずみ [-]"] = float(ss_result["fracture_strain[%]"]) / 100
    modulus = ss_result.get("modulus[GPa]")
    record["弾性率 [GPa]"] = "" if modulus is None else float(modulus)
    record["AEイベント数"] = int(ae_result["event_count"])
    speed = ss_result.get("crosshead_speed[mm/min]")
    if record.get("引張速度 [mm/min]", "") == "" and speed is not None and np.isfinite(speed):
        record["引張速度 [mm/min]"] = speed_setting(speed)
    record["状態"] = "解析済み"
    record["解析日時"] = now_text()
    record["更新日時"] = record["解析日時"]
    if files:
        record.update(files)
    if drive_status is not None:
        record[DRIVE_STATUS_COLUMN] = drive_status
    return record


# ---------- 台帳の読み書き ----------
class SpecimenStore:
    """Google スプレッドシートの1枚のシート（ワークシート）を台帳として読み書きする。

    worksheet は gspread のワークシート。テストでは、同じ使い方ができるテスト用のモック（tests/mocks.py）を渡す。
    """

    def __init__(self, worksheet):
        self.worksheet = worksheet

    # 見出しの行（1行目）を用意する
    def ensure_header(self):
        """1行目の見出しを確かめ、足りない列があれば右に追加する。見出しの並びを返す。

        - 空のシート：見出しをすべて書く
        - あとでアプリに列が増えたとき：増えた列だけを右端に足す（今までのデータはそのまま）
        """
        header = [str(h).strip() for h in self.worksheet.row_values(1)]
        while header and header[-1] == "":
            header.pop()
        missing = [column for column in COLUMNS if column not in header]
        if not missing:
            return header
        new_header = header + missing
        if self.worksheet.col_count < len(new_header):
            self.worksheet.add_cols(len(new_header) - self.worksheet.col_count)
        self.worksheet.update(values=[new_header], range_name="A1")
        return new_header

    def load(self):
        """台帳をすべて読み込み、表（DataFrame）にする。列はアプリの並び（COLUMNS）にそろえる。"""
        header = self.ensure_header()
        # 数値は数値のまま、日付（スプレッドシートに直接打った場合）は見た目どおりの文字で受け取る
        rows = self.worksheet.get_all_values(
            value_render_option="UNFORMATTED_VALUE",
            date_time_render_option="FORMATTED_STRING",
        )
        body = [row for row in rows[1:] if any(str(cell).strip() != "" for cell in row)]
        width = len(header)
        body = [list(row[:width]) + [""] * (width - len(row)) for row in body]
        table = pd.DataFrame(body, columns=header) if body else pd.DataFrame(columns=header)
        table = table.reindex(columns=COLUMNS, fill_value="")
        for column in NUMBER_COLUMNS:
            table[column] = pd.to_numeric(table[column].replace("", np.nan), errors="coerce")
        for column in [c for c in COLUMNS if c not in NUMBER_COLUMNS]:
            table[column] = table[column].astype(str).replace({"nan": "", "None": ""})
        # 「ドライブ保存」の列を作る前に解析した行：SS・AE のファイル ID が両方あれば保存済み
        saved_before = (
            (table[DRIVE_STATUS_COLUMN] == "") & (table["SSファイルID"] != "") & (table["AEファイルID"] != "")
        )
        table.loc[saved_before, DRIVE_STATUS_COLUMN] = "保存済み"
        return table

    def next_id(self, header):
        """次の ID（今ある ID の最大 ＋ 1）。"""
        id_column = header.index("ID") + 1
        ids = pd.to_numeric(
            pd.Series(self.worksheet.col_values(id_column)[1:], dtype=object), errors="coerce"
        )
        return int(ids.max()) + 1 if ids.notna().any() else 1

    def add(self, record):
        """新しい試験片を1行追加する。ID・登録日時・状態・自動の名前をつけて、その行を返す。"""
        header = self.ensure_header()
        record = dict(record)
        record["ID"] = self.next_id(header)
        record["登録日時"] = now_text()
        record["更新日時"] = record["登録日時"]
        if not record.get("状態"):
            record["状態"] = "未試験"
        if not record.get("試験片名"):
            record["試験片名"] = auto_name(record["ID"])
        self.worksheet.append_row(
            [to_cell(record.get(column, "")) for column in header],
            value_input_option="RAW",
            table_range="A1",
        )
        return record

    def update(self, record):
        """ID が同じ行を書き換える。見つからなければ ValueError。"""
        header = self.ensure_header()
        row_number = self.find_row(header, record["ID"])
        if record.get("試験片名", "") == "":
            record = dict(record, 試験片名=auto_name(record["ID"]))
        self.worksheet.update(
            values=[[to_cell(record.get(column, "")) for column in header]],
            range_name=f"A{row_number}",
            value_input_option="RAW",
        )
        return record

    def find_row(self, header, specimen_id):
        """ID がある行の番号（1行目＝見出し）を探す。書き込む直前に読み直すので、
        ほかの人が行を足したり、スプレッドシートを並べ替えたりしていても正しい行を書き換える。"""
        id_column = header.index("ID") + 1
        for row_number, value in enumerate(self.worksheet.col_values(id_column), start=1):
            if row_number == 1:
                continue
            try:
                if int(float(value)) == int(specimen_id):
                    return row_number
            except (TypeError, ValueError):
                continue
        raise ValueError(
            f"ID {specimen_id} の試験片が台帳に見つかりません（スプレッドシートで消された可能性があります）"
        )


def to_cell(value):
    """スプレッドシートに書ける値にする（numpy の数・NaN を普通の数・空欄に）。"""
    if value is None:
        return ""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return "" if np.isnan(value) else float(value)
    return value


def record_from_row(row):
    """一覧の表の1行（pandas の Series）を、台帳の1行（辞書）に戻す。"""
    record = {}
    for column in COLUMNS:
        value = row.get(column, "")
        if column in NUMBER_COLUMNS:
            value = "" if pd.isna(value) else float(value)
            if column in ("ID", "AEイベント数") and value != "":
                value = int(value)
        record[column] = value
    return record


# ---------- Google への接続 ----------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def read_settings(secrets):
    """Streamlit の Secrets から、合鍵（サービスアカウントの情報）と台帳の ID を取り出す。

    どちらかが無いときは (None, None, 足りないものの説明) を返す。
    合鍵は次のどちらの書き方でもよい：
      gcp_service_account_json = '''{ JSON ファイルの中身 }'''
      [gcp_service_account] …（JSON の項目を TOML で書いたもの）
    """
    import json

    try:
        if "gcp_service_account_json" in secrets:
            info = json.loads(secrets["gcp_service_account_json"])
        elif "gcp_service_account" in secrets:
            info = dict(secrets["gcp_service_account"])
        else:
            info = None
    except json.JSONDecodeError:
        return (
            None,
            None,
            (
                "Secrets の合鍵（gcp_service_account_json）の中身が正しく貼り付けられていません。"
                "JSON ファイルの中身を丸ごと貼ってください。"
            ),
        )
    except Exception:
        info = None

    try:
        spreadsheet_id = secrets["specimen_list"]["spreadsheet_id"]
    except Exception:
        spreadsheet_id = None

    missing = []
    if info is None:
        missing.append("合鍵（gcp_service_account_json）")
    if not spreadsheet_id:
        missing.append("台帳の ID（[specimen_list] の spreadsheet_id）")
    if missing:
        return None, None, "、".join(missing) + " が Secrets に登録されていません。"
    return info, spreadsheet_id, ""


def connect(info, spreadsheet_id):
    """合鍵で Google にログインし、台帳（スプレッドシートの1枚目のシート）を開く。"""
    import gspread  # Google スプレッドシートを操作するライブラリ

    client = gspread.service_account_from_dict(info, scopes=SCOPES)
    worksheet = client.open_by_key(spreadsheet_id).sheet1
    return SpecimenStore(worksheet)


def explain_error(error, service_account_email=""):
    """Google との通信でエラーになったとき、原因の見当がつく文にする。"""
    text = str(error)
    name = type(error).__name__
    if name == "SpreadsheetNotFound" or "404" in text:
        return (
            "台帳（スプレッドシート）が見つかりません。Secrets の spreadsheet_id が正しいか確認してください。"
        )
    if "403" in text or "PERMISSION_DENIED" in text:
        who = f"（{service_account_email}）" if service_account_email else ""
        return (
            "台帳を開く権限がありません。スプレッドシートの「共有」に、サービスアカウント"
            f"{who}が「編集者」で入っているか確認してください。"
        )
    if "429" in text or "RATE_LIMIT" in text.upper():
        return "Google への読み書きが短い時間に多すぎました。1分ほど待ってからもう一度試してください。"
    return f"台帳との通信でエラーが起きました（{name}：{text[:200]}）"
