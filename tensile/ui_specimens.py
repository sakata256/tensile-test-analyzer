"""「試験片の一覧」の画面（登録・一覧・内容の修正・一覧からの解析）。

台帳（Google スプレッドシート）の読み書きは specimen_list.py、
元ファイルの保存（Google ドライブ）は drive_storage.py が受け持つ。
"""

import json
from datetime import date

import streamlit as st

from tensile import drive_storage, specimen_list
from tensile.analysis import analyze_file_bytes
from tensile.ui_common import (
    SESSION_DEFAULTS,
    get_fit_settings,
    invalidate_analysis,
    render_dimension_detail_inputs,
    render_fit_settings,
)

# 台帳（Google スプレッドシート）の読み書きは specimen_list.py。ここは画面だけ。
SPECIMEN_TEXT_FIELDS = {  # 入力欄の名前 → 台帳の列
    "material": "材料の種類",
    "plate": "板の名前",
    "position": "端から",
    "name": "試験片名",
    "angle": "角度",
    "memo": "メモ",
    "operator": "担当者",
}


SPECIMEN_NUMBER_FIELDS = {
    "speed": "引張速度 [mm/min]",
    "width": "幅 [mm]",
    "thickness": "厚み [mm]",
    "gauge": "ゲージ長さ [mm]",
}


SPECIMEN_DETAILS = {  # 詳細寸法：入力欄の頭文字 → (台帳の列, 名前)
    "w": (specimen_list.WIDTH_DETAIL_COLUMNS, "幅"),
    "t": (specimen_list.THICKNESS_DETAIL_COLUMNS, "厚み"),
    "g": (specimen_list.GAUGE_DETAIL_COLUMNS, "ゲージ長さ"),
}


# 続けて登録するときに、前回の値を残しておく欄（同じ板の試験片をまとめて登録しやすいように）
SPECIMEN_KEEP_FIELDS = ["date", "material", "plate", "angle", "speed", "operator"]


LIST_COLUMNS = [
    "試験片名",
    "状態",
    specimen_list.DRIVE_STATUS_COLUMN,
    "試験日",
    "材料の種類",
    "板の名前",
    "端から",
    "角度",
    "引張速度 [mm/min]",
    "幅 [mm]",
    "厚み [mm]",
    "ゲージ長さ [mm]",
    "引張強さ [MPa]",
    "破断ひずみ [-]",
    "弾性率 [GPa]",
    "AEイベント数",
    "メモ",
    "担当者",
]


LIST_FORMATS = {
    "引張速度 [mm/min]": "%.2g",
    "幅 [mm]": "%.3f",
    "厚み [mm]": "%.3f",
    "ゲージ長さ [mm]": "%.2f",
    "引張強さ [MPa]": "%.2f",
    "破断ひずみ [-]": "%.4f",
    "弾性率 [GPa]": "%.3f",
    "AEイベント数": "%d",
}


@st.cache_resource(show_spinner="台帳に接続しています…")
def connect_specimen_store(info_json, spreadsheet_id):
    """Google に接続する（1回つないだら使い回す）。"""
    return specimen_list.connect(json.loads(info_json), spreadsheet_id)


def specimen_list_configured():
    """台帳（Google スプレッドシート）の設定があるか。ないときは「試験片の一覧」を出さない。

    解析だけを使う公開版やパソコンでの起動では、Secrets に台帳の設定を入れないので False になる。
    """
    if "specimen_store" in st.session_state:  # テスト用：台帳をモックに差し替えたとき
        return True
    try:
        return any(
            key in st.secrets for key in ("gcp_service_account_json", "gcp_service_account", "specimen_list")
        )
    except Exception:
        return False


def get_specimen_store():
    """台帳を返す。使えないときは (None, 理由の文)。"""
    if "specimen_store" in st.session_state:  # テスト用：台帳をモックに差し替えたとき
        return st.session_state.specimen_store, ""
    info, spreadsheet_id, problem = specimen_list.read_settings(st.secrets)
    if problem:
        return None, problem
    try:
        return connect_specimen_store(json.dumps(info, sort_keys=True), spreadsheet_id), ""
    except Exception as error:
        return None, specimen_list.explain_error(error, info.get("client_email", ""))


def get_specimen_table(store):
    """台帳の表を返す。読み込みは「最初」と「登録・修正のあと」と「更新ボタン」のときだけ
    （画面を操作するたびに Google に読みに行くと、回数の上限にかかるため）。"""
    if st.session_state.get("specimen_table") is None:
        st.session_state.specimen_table = store.load()
    return st.session_state.specimen_table


def refresh_specimen_table():
    st.session_state.specimen_table = None


def specimen_label(table, specimen_id):
    """選ぶ欄に出す名前：「No.0003｜A-3（CF/PA6・板A・端から2）」。"""
    row = table[table["ID"] == specimen_id].iloc[0]
    extra = "・".join(
        v
        for v in [row["材料の種類"], row["板の名前"], f"端から{row['端から']}" if row["端から"] else ""]
        if v
    )
    number = specimen_list.auto_name(specimen_id)
    name = number if row["試験片名"] == number else f"{number}｜{row['試験片名']}"
    return name + (f"（{extra}）" if extra else "")


# ---------- 入力欄 ----------
def render_specimen_fields(prefix, include_status=False):
    """試験片の入力欄（登録と修正で共通）。どの欄も空欄でよい。"""
    cols = st.columns(2, gap="small")
    cols[0].date_input("試験日", value=None, key=f"{prefix}date", format="YYYY-MM-DD")
    cols[1].text_input("担当者", key=f"{prefix}operator")

    cols = st.columns(2, gap="small")
    cols[0].text_input("材料の種類", key=f"{prefix}material", placeholder="例：CF/PA6")
    cols[1].text_input("板の名前", key=f"{prefix}plate", placeholder="例：板A")

    cols = st.columns(2, gap="small")
    cols[0].text_input("端から", key=f"{prefix}position", placeholder="例：1")
    cols[1].text_input("試験片名", key=f"{prefix}name", placeholder="空欄なら自動で番号")

    cols = st.columns(2, gap="small")
    cols[0].text_input("角度 [°]", key=f"{prefix}angle", placeholder="例：45")
    cols[1].number_input(
        "引張速度 [mm/min]",
        value=None,
        min_value=0.0,
        step=1.0,
        key=f"{prefix}speed",
        placeholder="空欄で自動",
    )

    cols = st.columns(2, gap="small")
    cols[0].number_input("幅 [mm]", value=None, min_value=0.0, step=0.01, format="%.3f", key=f"{prefix}width")
    cols[1].number_input(
        "厚み [mm]", value=None, min_value=0.0, step=0.01, format="%.3f", key=f"{prefix}thickness"
    )

    cols = st.columns(2, gap="small")
    cols[0].number_input(
        "ゲージ長さ [mm]", value=None, min_value=0.0, step=1.0, format="%.2f", key=f"{prefix}gauge"
    )

    with st.expander("詳細寸法（必要な場合）"):
        st.caption("入力した欄だけで平均し、上の直接入力より優先します。")
        for letter, label, count in [("w", "幅 [mm]", 9), ("t", "厚み [mm]", 9), ("g", "ゲージ長さ [mm]", 3)]:
            st.markdown(f"**{label}**")
            if count == 9:
                header = st.columns([0.7, 1, 1, 1], gap="small")
                for i in range(3):
                    header[i + 1].caption(f"{i + 1}回目")
                for row_index, position in enumerate(specimen_list.DETAIL_POSITIONS):
                    cols = st.columns([0.7, 1, 1, 1], gap="small")
                    cols[0].write(position)
                    for column_index in range(3):
                        cols[column_index + 1].text_input(
                            f"{label} {position} {column_index + 1}回目",
                            key=f"{prefix}{letter}_{row_index * 3 + column_index}",
                            label_visibility="collapsed",
                        )
            else:
                cols = st.columns(3, gap="small")
                for i in range(3):
                    cols[i].text_input(
                        f"{label} {i + 1}回目",
                        key=f"{prefix}{letter}_{i}",
                        placeholder=f"{i + 1}回目",
                        label_visibility="collapsed",
                    )

    if include_status:
        st.selectbox("状態", specimen_list.STATUS_OPTIONS, key=f"{prefix}status")
    st.text_area("メモ", key=f"{prefix}memo", height=80)


def collect_specimen_form(prefix):
    """入力欄の値を、specimen_list.build_record に渡す形（辞書）にまとめる。"""
    state = st.session_state
    form = {"試験日": state.get(f"{prefix}date")}
    for field, column in SPECIMEN_TEXT_FIELDS.items():
        form[column] = state.get(f"{prefix}{field}", "")
    for field, column in SPECIMEN_NUMBER_FIELDS.items():
        form[column] = state.get(f"{prefix}{field}")
    form["幅の詳細"] = [state.get(f"{prefix}w_{i}", "") for i in range(9)]
    form["厚みの詳細"] = [state.get(f"{prefix}t_{i}", "") for i in range(9)]
    form["ゲージ長さの詳細"] = [state.get(f"{prefix}g_{i}", "") for i in range(3)]
    if f"{prefix}status" in state:
        form["状態"] = state[f"{prefix}status"]
    return form


def clear_specimen_fields(prefix, keep=()):
    """入力欄を空にする（keep に入っている欄は残す）。"""
    for field in list(SPECIMEN_TEXT_FIELDS) + list(SPECIMEN_NUMBER_FIELDS) + ["date"]:
        if field not in keep:
            st.session_state[f"{prefix}{field}"] = (
                None if field in SPECIMEN_NUMBER_FIELDS or field == "date" else ""
            )
    for letter, (columns, _) in SPECIMEN_DETAILS.items():
        for i in range(len(columns)):
            st.session_state[f"{prefix}{letter}_{i}"] = ""


def set_specimen_message(kind, text):
    st.session_state.specimen_message = (kind, text)


# ---------- 登録・修正（ボタンを押したときに動く） ----------
def register_specimen():
    store, problem = get_specimen_store()
    if store is None:
        set_specimen_message("error", problem)
        return
    try:
        record = store.add(specimen_list.build_record(collect_specimen_form("reg_")))
    except ValueError as error:
        set_specimen_message("error", str(error))
        return
    except Exception as error:
        set_specimen_message("error", specimen_list.explain_error(error))
        return
    # 次の試験片を続けて登録しやすいように、材料・板・角度などは残す
    st.session_state.specimen_keep = {f: st.session_state.get(f"reg_{f}") for f in SPECIMEN_KEEP_FIELDS}
    clear_specimen_fields("reg_", keep=SPECIMEN_KEEP_FIELDS)
    refresh_specimen_table()
    number = specimen_list.auto_name(record["ID"])
    name = record["試験片名"] if record["試験片名"] == number else f"{record['試験片名']}（{number}）"
    set_specimen_message("success", f"「{name}」を登録しました")


def load_specimen_into_edit(record):
    """修正する試験片の値を、修正用の入力欄に入れる。"""
    state = st.session_state
    try:
        state["edit_date"] = date.fromisoformat(str(record["試験日"])[:10]) if record["試験日"] else None
    except ValueError:
        state["edit_date"] = None
    for field, column in SPECIMEN_TEXT_FIELDS.items():
        state[f"edit_{field}"] = str(record[column])
    for letter, (columns, _) in SPECIMEN_DETAILS.items():
        for i, column in enumerate(columns):
            state[f"edit_{letter}_{i}"] = "" if record[column] == "" else f"{record[column]:.10g}"
    details_entered = {
        letter: any(record[c] != "" for c in columns) for letter, (columns, _) in SPECIMEN_DETAILS.items()
    }
    for field, column in SPECIMEN_NUMBER_FIELDS.items():
        value = None if record[column] == "" else float(record[column])
        # 詳細寸法から平均した値は、直接入力の欄には入れない（詳細のほうが優先されるため）
        letter = {"width": "w", "thickness": "t", "gauge": "g"}.get(field)
        state[f"edit_{field}"] = None if letter and details_entered[letter] else value
    state["edit_status"] = record["状態"] if record["状態"] in specimen_list.STATUS_OPTIONS else "未試験"
    state["edit_loaded_id"] = record["ID"]


def save_specimen_edit():
    store, problem = get_specimen_store()
    if store is None:
        set_specimen_message("error", problem)
        return
    existing = st.session_state.get("edit_original")
    try:
        record = store.update(specimen_list.build_record(collect_specimen_form("edit_"), existing=existing))
    except ValueError as error:
        set_specimen_message("error", str(error))
        return
    except Exception as error:
        set_specimen_message("error", specimen_list.explain_error(error))
        return
    refresh_specimen_table()
    st.session_state.edit_loaded_id = None  # 保存した内容で入力欄を読み直す
    fill_analysis_inputs(record)  # 解析の欄の寸法も、直した値にそろえる
    set_specimen_message("success", f"「{record['試験片名']}」の内容を保存しました")


# ---------- 試験片を開く・解析する ----------
def format_detail(value):
    return "" if value == "" or value is None else f"{float(value):.10g}"


def fill_analysis_inputs(record):
    """解析の入力欄（寸法・詳細寸法）に、台帳の値を入れる。空欄なら初期値（15・2・60）。"""
    state = st.session_state
    state["width"] = float(record["幅 [mm]"]) if record["幅 [mm]"] != "" else SESSION_DEFAULTS["width"]
    state["thickness"] = (
        float(record["厚み [mm]"]) if record["厚み [mm]"] != "" else SESSION_DEFAULTS["thickness"]
    )
    state["gauge_length"] = (
        float(record["ゲージ長さ [mm]"])
        if record["ゲージ長さ [mm]"] != ""
        else SESSION_DEFAULTS["gauge_length"]
    )
    for prefix, columns in [
        ("detail_width", specimen_list.WIDTH_DETAIL_COLUMNS),
        ("detail_thickness", specimen_list.THICKNESS_DETAIL_COLUMNS),
        ("detail_gauge", specimen_list.GAUGE_DETAIL_COLUMNS),
    ]:
        for i, column in enumerate(columns):
            state[f"{prefix}_{i}"] = format_detail(record[column])
    state["dimension_detail_message"] = ""
    state["dimension_detail_error"] = ""
    state["specimen_name"] = record["試験片名"]


def open_specimen(specimen_id):
    """一覧から試験片を開く。"""
    table = st.session_state.get("specimen_table")
    if table is None or specimen_id not in set(table["ID"]):
        return
    record = specimen_list.record_from_row(table[table["ID"] == specimen_id].iloc[0])
    st.session_state.opened_specimen_id = int(specimen_id)
    st.session_state.edit_loaded_id = None
    st.session_state.specimen_file_choice = None
    st.session_state.specimen_analysis_messages = []
    fill_analysis_inputs(record)
    if st.session_state.get("analysis_specimen_id") != specimen_id:
        st.session_state.analysis_done = False


def open_specimen_from_picker():
    specimen_id = st.session_state.get("specimen_picker")
    st.session_state.specimen_picker = None
    if specimen_id is not None:
        open_specimen(specimen_id)


def open_specimen_from_table():
    selection = st.session_state.get("specimen_table_view", {}).get("selection", {})
    rows = selection.get("rows", [])
    ids = st.session_state.get("specimen_view_ids", [])
    if rows and rows[0] < len(ids):
        open_specimen(ids[rows[0]])


def close_specimen():
    st.session_state.opened_specimen_id = None


def read_dimensions_for_analysis():
    """解析に使う寸法：詳細寸法に入力があれば、その平均（台帳・Excel と同じ決め方）。"""
    state = st.session_state
    details = (
        specimen_list.parse_detail_values([state.get(f"detail_width_{i}", "") for i in range(9)], "幅"),
        specimen_list.parse_detail_values([state.get(f"detail_thickness_{i}", "") for i in range(9)], "厚み"),
        specimen_list.parse_detail_values(
            [state.get(f"detail_gauge_{i}", "") for i in range(3)], "ゲージ長さ"
        ),
    )
    dimensions = (
        specimen_list.dimension_value(state.get("width"), details[0]),
        specimen_list.dimension_value(state.get("thickness"), details[1]),
        specimen_list.dimension_value(state.get("gauge_length"), details[2]),
    )
    if any(v is None or v <= 0 for v in dimensions):
        raise ValueError("寸法は0より大きい値を入力してください")
    return dimensions, details


def run_specimen_analysis():
    """「解析開始」を押したとき：解析 → ドライブに元ファイルを保存 → 結果を台帳に書き込む。"""
    state = st.session_state
    state.specimen_analysis_messages = []
    messages = state.specimen_analysis_messages
    store, problem = get_specimen_store()
    specimen_id = state.get("opened_specimen_id")
    table = state.get("specimen_table")
    if store is None or specimen_id is None or table is None:
        messages.append(("error", problem or "試験片が選ばれていません"))
        return
    record = specimen_list.record_from_row(table[table["ID"] == specimen_id].iloc[0])
    use_saved = (
        state.get("specimen_file_choice") == "saved" and record["SSファイルID"] and record["AEファイルID"]
    )

    # 1. 寸法とファイル
    try:
        dimensions, details = read_dimensions_for_analysis()
    except ValueError as error:
        messages.append(("error", str(error)))
        return
    drive, drive_problem = get_drive_storage()
    if use_saved:
        if drive is None:
            messages.append(("error", drive_problem))
            return
        try:
            with st.spinner("Google ドライブからファイルを読み込んでいます…"):
                ss_bytes = drive.download(record["SSファイルID"])
                ae_bytes = drive.download(record["AEファイルID"])
        except Exception as error:
            messages.append(("error", drive_storage.explain_drive_error(error)))
            return
        ss_name, ae_name = record["SSファイル"], record["AEファイル"]
    else:
        ss_file, ae_file = state.get("specimen_ss_file"), state.get("specimen_ae_file")
        if ss_file is None or ae_file is None:
            messages.append(("error", "SSファイルとAEファイルを選択してください"))
            return
        ss_bytes, ae_bytes = ss_file.getvalue(), ae_file.getvalue()
        ss_name, ae_name = ss_file.name, ae_file.name

    # 2. 解析
    try:
        with st.spinner("解析しています…"):
            results = analyze_file_bytes(ss_bytes, ae_bytes, *dimensions, get_fit_settings())
    except Exception as error:
        messages.append(("error", f"解析エラー：{error}"))
        return
    state.ss_data, state.ss_result, state.ae_data, state.ae_result = results
    state.analysis_done = True
    state.analysis_source = "specimen"
    state.analysis_specimen_id = specimen_id
    # 詳細寸法の平均を使ったときは、上の入力欄にもその値を出す
    state.width, state.thickness, state.gauge_length = dimensions

    # 3. 新しいファイルなら、Google ドライブに保存
    files = None
    drive_status = None  # 保存済みのファイルで解析し直したときは、前の値のまま
    if not use_saved:
        if drive is None:
            drive_status = "保存なし"
            messages.append(("info", f"元ファイルはドライブに保存していません（{drive_problem}）"))
        else:
            try:
                with st.spinner("Google ドライブにファイルを保存しています…"):
                    number = specimen_list.auto_name(specimen_id)
                    folder_name = number if record["試験片名"] == number else f"{number}_{record['試験片名']}"
                    folder_id = record["フォルダID"] or drive.specimen_folder(folder_name)
                    ss_id = drive.upload(folder_id, ss_name, ss_bytes)
                    ae_id = drive.upload(folder_id, ae_name, ae_bytes)
                files = {
                    "SSファイル": ss_name,
                    "AEファイル": ae_name,
                    "データフォルダ": drive_storage.folder_link(folder_id),
                    "SSファイルID": ss_id,
                    "AEファイルID": ae_id,
                    "フォルダID": folder_id,
                }
                drive_status = "保存済み"
            except Exception as error:
                drive_status = "保存失敗"
                messages.append(
                    (
                        "warning",
                        drive_storage.explain_drive_error(error)
                        + "（解析の結果は一覧に保存します。一覧の「ドライブ保存」は「保存失敗」になります。"
                        "SSファイルだけドライブのフォルダに残っていることがあります）",
                    )
                )

    # 4. 結果を台帳に書き込む
    try:
        new_record = specimen_list.record_with_analysis(
            record, dimensions, details, state.ss_result, state.ae_result, files, drive_status
        )
        store.update(new_record)
    except Exception as error:
        messages.append(
            (
                "error",
                "解析はできましたが、一覧への書き込みに失敗しました：" + specimen_list.explain_error(error),
            )
        )
        return
    refresh_specimen_table()
    state.edit_loaded_id = None
    state.specimen_file_choice = "saved" if (use_saved or files) else None
    saved_note = "、元ファイルを Google ドライブに保存しました" if files else ""
    messages.insert(0, ("success", f"解析して、結果を一覧に書き込みました{saved_note}"))


# ---------- Google ドライブ ----------
@st.cache_resource(show_spinner=False)
def connect_drive_storage(settings_json):
    return drive_storage.connect_drive(json.loads(settings_json))


def get_drive_storage():
    """ドライブを返す。使えないときは (None, 理由の文)。"""
    if "drive_storage" in st.session_state:  # テスト用：ドライブをモックに差し替えたとき
        return st.session_state.drive_storage, ""
    settings, problem = drive_storage.read_drive_settings(st.secrets)
    if settings is None:
        return None, problem
    return connect_drive_storage(json.dumps(settings, sort_keys=True)), ""


# ---------- 画面 ----------
def render_specimen_list_tab(table):
    top = st.columns([3, 2], gap="small")
    top[0].write(f"登録数：**{len(table)}本**")
    top[1].button("最新の状態に更新", on_click=refresh_specimen_table, key="specimen_refresh")
    if table.empty:
        st.info("まだ登録がありません。「新しく登録」から試験片を登録してください。")
        return

    view = table.sort_values("ID", ascending=False)
    with st.expander("絞り込み・検索"):
        for column in ["材料の種類", "板の名前", "角度", "状態", specimen_list.DRIVE_STATUS_COLUMN]:
            options = sorted(v for v in table[column].unique() if v != "")
            if options:
                chosen = st.multiselect(column, options, key=f"filter_{column}")
                if chosen:
                    view = view[view[column].isin(chosen)]
        keyword = st.text_input("キーワード（試験片名・メモ・担当者）", key="filter_keyword").strip()
        if keyword:
            hit = (
                view["試験片名"].str.contains(keyword, case=False, regex=False)
                | view["メモ"].str.contains(keyword, case=False, regex=False)
                | view["担当者"].str.contains(keyword, case=False, regex=False)
            )
            view = view[hit]
        show_all = st.checkbox("詳細寸法・登録日時の列も表示", key="filter_show_all")

    ids = view["ID"].astype(int).tolist()
    st.selectbox(
        "試験片を開く（解析・内容の修正）",
        ids,
        index=None,
        key="specimen_picker",
        placeholder="試験片を選ぶ",
        format_func=lambda i: specimen_label(table, i),
        on_change=open_specimen_from_picker,
    )

    columns = LIST_COLUMNS + (
        ["登録日時", "更新日時", "解析日時"]
        + specimen_list.FILE_COLUMNS
        + specimen_list.WIDTH_DETAIL_COLUMNS
        + specimen_list.THICKNESS_DETAIL_COLUMNS
        + specimen_list.GAUGE_DETAIL_COLUMNS
        if show_all
        else []
    )
    if len(view) != len(table):
        st.caption(f"{len(view)}本を表示中（全{len(table)}本）")
    st.session_state.specimen_view_ids = ids
    column_config = {c: st.column_config.NumberColumn(c, format=f) for c, f in LIST_FORMATS.items()}
    column_config["データフォルダ"] = st.column_config.LinkColumn("データフォルダ", display_text="開く")
    st.dataframe(
        view[columns],
        hide_index=True,
        column_config=column_config,
        on_select=open_specimen_from_table,
        selection_mode="single-row",
        key="specimen_table_view",
    )
    st.caption(
        "表の左端を押しても試験片を開けます。列の名前を押すと並べ替え。"
        "行を消したいときは、スプレッドシートで直接消してください。"
    )


def render_specimen_register_tab():
    keep = st.session_state.get("specimen_keep", {})
    for field, value in keep.items():
        st.session_state.setdefault(f"reg_{field}", value)
    with st.form("specimen_register_form"):
        render_specimen_fields("reg_")
        st.form_submit_button("登録する", type="primary", on_click=register_specimen)


def render_specimen_edit_tab(record):
    # ほかの試験片を開いたとき・ほかの画面から戻ってきて入力欄が空になったときに、値を入れ直す
    if st.session_state.get("edit_loaded_id") != record["ID"] or "edit_status" not in st.session_state:
        st.session_state.edit_original = record
        load_specimen_into_edit(record)
    with st.form("specimen_edit_form"):
        render_specimen_fields("edit_", include_status=True)
        st.form_submit_button("保存する", type="primary", on_click=save_specimen_edit)


def render_specimen_analysis_tab(record):
    has_saved = bool(record["SSファイルID"] and record["AEファイルID"])
    if has_saved:
        if st.session_state.get("specimen_file_choice") not in ("saved", "new"):
            st.session_state.specimen_file_choice = "saved"
        st.radio(
            "使うファイル",
            ["saved", "new"],
            key="specimen_file_choice",
            horizontal=True,
            format_func=lambda v: "保存済みのファイル" if v == "saved" else "新しいファイルを選ぶ",
            on_change=invalidate_analysis,
        )
    if has_saved and st.session_state.specimen_file_choice == "saved":
        st.caption(f"SS：{record['SSファイル']}　AE：{record['AEファイル']}（Google ドライブ）")
    else:
        cols = st.columns(2, gap="small")
        cols[0].file_uploader(
            "SSファイル", type=["txt"], key="specimen_ss_file", on_change=invalidate_analysis
        )
        cols[1].file_uploader(
            "AEファイル", type=["txt"], key="specimen_ae_file", on_change=invalidate_analysis
        )

    cols = st.columns(3, gap="small")
    cols[0].number_input("幅 [mm]", min_value=0.0, key="width", on_change=invalidate_analysis)
    cols[1].number_input("厚み [mm]", min_value=0.0, key="thickness", on_change=invalidate_analysis)
    cols[2].number_input("ゲージ長さ [mm]", min_value=0.0, key="gauge_length", on_change=invalidate_analysis)
    st.caption(
        "寸法は一覧に登録した値です（空欄だった寸法は 15・2・60）。詳細寸法に入力があれば、その平均を使います。"
        "解析すると、使った寸法と結果が一覧に保存されます。"
    )
    render_dimension_detail_inputs(button_key="apply_specimen_dimension_details")
    render_fit_settings()
    st.button("解析開始", type="primary", on_click=run_specimen_analysis, key="specimen_analyze")
    for kind, text in st.session_state.get("specimen_analysis_messages", []):
        {"success": st.success, "error": st.error, "warning": st.warning, "info": st.info}[kind](text)


def render_specimen_page(table, specimen_id):
    st.session_state.specimen_page_shown = True  # この下に解析結果を出してよい、という目印
    record = specimen_list.record_from_row(table[table["ID"] == specimen_id].iloc[0])
    st.button("← 一覧に戻る", on_click=close_specimen, key="specimen_back")
    st.subheader(specimen_label(table, specimen_id))
    facts = [f"状態：{record['状態']}"]
    if record["角度"]:
        facts.append(f"角度：{record['角度']}°")
    if record["引張速度 [mm/min]"] != "":
        facts.append(f"引張速度：{record['引張速度 [mm/min]']:g} mm/min")
    if record["試験日"]:
        facts.append(f"試験日：{record['試験日']}")
    if record["担当者"]:
        facts.append(f"担当者：{record['担当者']}")
    st.write("　".join(facts))
    if record["引張強さ [MPa]"] != "":
        modulus = f"{record['弾性率 [GPa]']:.3f} GPa" if record["弾性率 [GPa]"] != "" else "―"
        when = f"（{record['解析日時']}）" if record["解析日時"] else ""
        st.caption(
            f"前回の結果{when}：引張強さ {record['引張強さ [MPa]']:.2f} MPa、"
            f"破断ひずみ {record['破断ひずみ [-]']:.4f}、弾性率 {modulus}"
        )
    if record["メモ"]:
        st.caption(f"メモ：{record['メモ']}")
    drive_status = record[specimen_list.DRIVE_STATUS_COLUMN]
    # 保存できなかったときはリンクを書かないので、リンクが残っていれば前回のもの
    old_link_note = (
        "下のリンク先は前回保存したファイルで、今の結果の解析に使ったファイルではありません。"
        if record["SSファイルID"]
        else ""
    )
    if drive_status == "保存失敗":
        st.warning(
            "元ファイルを Google ドライブに保存できていません。"
            "新しいファイルを選んで解析し直すと、もう一度保存します。" + old_link_note
        )
    elif drive_status == "保存なし":
        st.caption(
            "元ファイルは Google ドライブに保存していません"
            "（解析したときにドライブの設定がありませんでした）。" + old_link_note
        )
    if record["データフォルダ"]:
        st.markdown(f"[Google ドライブのフォルダを開く]({record['データフォルダ']})")

    analysis_tab, edit_tab = st.tabs(["解析", "内容を直す"])
    with analysis_tab:
        render_specimen_analysis_tab(record)
    with edit_tab:
        render_specimen_edit_tab(record)


def render_specimen_mode():
    store, problem = get_specimen_store()
    if store is None:
        st.header("試験片の一覧")
        if "Secrets" in problem:  # 設定がまだ・まちがっている
            st.info(
                "試験片の一覧を使うには、Google スプレッドシート（台帳）の設定が必要です。\n\n"
                f"{problem}\n\n"
                "Streamlit の Settings → Secrets に、合鍵と台帳の ID を登録してください"
                "（パソコンで動かすときは `.streamlit/secrets.toml` に書きます）。"
                "登録しないで解析するときは、上の「新しく解析する」を選んでください。"
            )
        else:  # 設定はあるが、Google につながらない
            st.error(problem)
            st.button("もう一度つなぐ", key="specimen_reconnect")
        return

    message = st.session_state.pop("specimen_message", None)
    if message:
        (st.success if message[0] == "success" else st.error)(message[1])

    try:
        table = get_specimen_table(store)
    except Exception as error:
        st.error(specimen_list.explain_error(error))
        st.button("もう一度読み込む", on_click=refresh_specimen_table, key="specimen_retry")
        return

    opened = st.session_state.get("opened_specimen_id")
    if opened is not None and opened in set(table["ID"]):
        render_specimen_page(table, opened)
        return

    st.header("試験片の一覧")
    list_tab, register_tab = st.tabs(["一覧", "新しく登録"])
    with list_tab:
        render_specimen_list_tab(table)
    with register_tab:
        render_specimen_register_tab()
