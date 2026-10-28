"""画面の共通部品（スタイル・状態の管理・寸法と直線区間の入力欄・解析結果の表示）。"""

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from tensile.analysis import FIT_DEFAULTS
from tensile.excel_export import create_specimen_excel
from tensile.figures import GRAPH_TYPES, X_AXES, create_research_figure, create_zero_point_figure
from tensile.project_io import create_project_zip, result_signature

APP_CSS = """
<style>
/* 狭い画面でも columns を横並びに維持 */
div[data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    gap: 0.4rem !important;
}

/* 各列を画面幅に合わせて縮める */
div[data-testid="stColumn"] {
    min-width: 0 !important;
    flex: 1 1 0 !important;
}

/* 詳細寸法入力をコンパクトにする */
div[data-testid="stExpander"] div[data-testid="stTextInput"] input {
    height: 34px;
    min-height: 34px;
    padding: 4px 6px;
}

div[data-testid="stExpander"] div[data-testid="stTextInput"] {
    margin-bottom: -8px;
}

div[data-testid="stExpander"] div[data-testid="stColumn"] p {
    font-size: 0.9rem;
}

/* 見出し */
h2 {
    font-size: 2.0rem !important;
    margin-top: 0.6rem !important;
    margin-bottom: 0.5rem !important;
}

/* 通常の入力欄 */
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input,
div[data-testid="stNumberInput"] button {
    min-height: 38px !important;
    height: 38px !important;
}

/* ファイル選択欄 */
div[data-testid="stFileUploaderDropzone"] {
    padding-top: 8px !important;
    padding-bottom: 8px !important;
    min-height: 70px !important;
}

/* 各入力欄の下の余白 */
div[data-testid="stTextInput"],
div[data-testid="stNumberInput"],
div[data-testid="stFileUploader"] {
    margin-bottom: -6px !important;
}

/* 解析結果の数値 */
div[data-testid="stMetricValue"] {
    font-size: 1.8rem !important;
}
</style>
"""


SESSION_DEFAULTS = {
    "analysis_done": False,
    "analysis_source": None,
    "specimen_name": "",
    "width": 15.0,
    "thickness": 2.0,
    "gauge_length": 60.0,
}


def initialize_app():
    """CSS と初期セッション値を設定する。"""
    st.markdown(APP_CSS, unsafe_allow_html=True)

    for key, default_value in {**SESSION_DEFAULTS, **FIT_DEFAULTS}.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def invalidate_analysis():
    st.session_state.analysis_done = False


def reset_project_selection():
    st.session_state.analysis_done = False
    st.session_state.analysis_source = None


def get_dimension_details():
    """画面の「詳細寸法入力」に入っている値を集める。"""
    return {
        "width_values": [st.session_state.get(f"detail_width_{i}", "") for i in range(9)],
        "thickness_values": [st.session_state.get(f"detail_thickness_{i}", "") for i in range(9)],
        "gauge_values": [st.session_state.get(f"detail_gauge_{i}", "") for i in range(3)],
    }


def apply_dimension_details():
    try:

        def read_detail_values(prefix, count, name):
            values = []
            for i in range(count):
                text = st.session_state.get(f"{prefix}_{i}", "").strip()
                if text == "":
                    continue
                try:
                    value = float(text)
                except ValueError:
                    raise ValueError(f"{name}には数値を入力してください") from None
                if value <= 0:
                    raise ValueError(f"{name}は0より大きい値を入力してください")
                values.append(value)
            return values

        width_values = read_detail_values("detail_width", 9, "幅")
        if len(width_values) > 0:
            st.session_state.width = float(np.mean(width_values))
        thickness_values = read_detail_values("detail_thickness", 9, "厚み")
        if len(thickness_values) > 0:
            st.session_state.thickness = float(np.mean(thickness_values))
        gauge_values = read_detail_values("detail_gauge", 3, "ゲージ長さ")
        if len(gauge_values) > 0:
            st.session_state.gauge_length = float(np.mean(gauge_values))
        st.session_state.analysis_done = False
        st.session_state.dimension_detail_message = "詳細寸法の平均値を反映しました"
        st.session_state.dimension_detail_error = ""
    except ValueError as error:
        st.session_state.dimension_detail_error = str(error)
        st.session_state.dimension_detail_message = ""


def render_dimension_detail_inputs(button_key=None):
    """幅・厚み・ゲージ長さの詳細入力欄を表示する。"""
    with st.expander("詳細寸法入力（必要な場合）"):
        st.caption("空欄は無視し、入力した値だけで平均します。")

        positions = ["上部", "中央", "下部"]

        # 幅
        st.markdown("**幅 [mm]**")
        header_cols = st.columns([0.7, 1, 1, 1], gap="small")
        header_cols[0].write("")
        for i in range(3):
            header_cols[i + 1].write(f"{i + 1}回目")

        for row_index, position in enumerate(positions):
            cols = st.columns([0.7, 1, 1, 1], gap="small")
            cols[0].write(position)

            for column_index in range(3):
                index = row_index * 3 + column_index
                with cols[column_index + 1]:
                    st.text_input(
                        f"幅 {position} {column_index + 1}回目",
                        key=f"detail_width_{index}",
                        label_visibility="collapsed",
                        on_change=invalidate_analysis,
                    )

        # 厚み
        st.markdown("**厚み [mm]**")
        header_cols = st.columns([0.7, 1, 1, 1], gap="small")
        header_cols[0].write("")
        for i in range(3):
            header_cols[i + 1].write(f"{i + 1}回目")

        for row_index, position in enumerate(positions):
            cols = st.columns([0.7, 1, 1, 1], gap="small")
            cols[0].write(position)

            for column_index in range(3):
                index = row_index * 3 + column_index
                with cols[column_index + 1]:
                    st.text_input(
                        f"厚み {position} {column_index + 1}回目",
                        key=f"detail_thickness_{index}",
                        label_visibility="collapsed",
                        on_change=invalidate_analysis,
                    )

        # ゲージ長さ
        st.markdown("**ゲージ長さ [mm]**")
        gauge_header = st.columns(3, gap="small")
        for i in range(3):
            gauge_header[i].write(f"{i + 1}回目")

        gauge_cols = st.columns(3, gap="small")
        for i in range(3):
            with gauge_cols[i]:
                st.text_input(
                    f"ゲージ長さ {i + 1}回目",
                    key=f"detail_gauge_{i}",
                    label_visibility="collapsed",
                    on_change=invalidate_analysis,
                )

        button_args = {"key": button_key} if button_key else {}
        st.button(
            "平均値を反映",
            on_click=apply_dimension_details,
            **button_args,
        )

        if st.session_state.get("dimension_detail_message", ""):
            st.success(st.session_state["dimension_detail_message"])

        if st.session_state.get("dimension_detail_error", ""):
            st.error(st.session_state["dimension_detail_error"])


def render_fit_settings():
    """ひずみゼロ補正・弾性率に使う「初期の直線区間」の設定欄を表示する。"""
    with st.expander("直線区間の設定（ひずみゼロ補正・弾性率）"):
        st.caption(
            "自動：曲線の最初のきれいな直線部分（傾きが最も大きい直線区間）を探します。"
            "うまくいかない場合は手動で、最大応力に対する%で範囲を指定してください。"
        )
        st.radio(
            "決め方",
            ["自動", "手動"],
            key="fit_mode",
            horizontal=True,
            on_change=invalidate_analysis,
        )
        if st.session_state.fit_mode == "手動":
            fit_cols = st.columns(2, gap="small")
            with fit_cols[0]:
                st.number_input(
                    "下限 [最大応力の%]",
                    min_value=0.0,
                    max_value=100.0,
                    step=1.0,
                    key="fit_manual_low",
                    on_change=invalidate_analysis,
                )
            with fit_cols[1]:
                st.number_input(
                    "上限 [最大応力の%]",
                    min_value=0.0,
                    max_value=100.0,
                    step=1.0,
                    key="fit_manual_high",
                    on_change=invalidate_analysis,
                )


def get_fit_settings():
    return (
        st.session_state.fit_mode,
        float(st.session_state.fit_manual_low),
        float(st.session_state.fit_manual_high),
    )


def render_result_summary(specimen_name, ss_data, ss_result, ae_data, ae_result):
    st.success("解析済み")
    disp_gap_message = ss_result.get("disp_gap_message", "")
    if disp_gap_message:
        ae_filled = ae_result.get("disp_filled_count", 0)
        if ss_result.get("disp_fill_applied") and ae_filled:
            disp_gap_message += f"（AEイベント {ae_filled}件も同じ方法で補いました）"
        st.warning(disp_gap_message)
    fit_warning = ss_result.get("fit_warning", "")
    if fit_warning:
        st.warning(fit_warning)
    modulus = ss_result.get("modulus[GPa]")
    result_cols = st.columns(4, gap="small")
    with result_cols[0]:
        st.metric("最大応力", f"{ss_result['max_stress[MPa]']:.3f} MPa")
    with result_cols[1]:
        st.metric("破断ひずみ", f"{ss_result['fracture_strain[%]']:.3f} %")
    with result_cols[2]:
        st.metric("弾性率", f"{modulus:.3f} GPa" if modulus is not None else "―")
    with result_cols[3]:
        st.metric("AEイベント数", f"{ae_result['event_count']}")
    st.caption(
        "弾性率はクロスヘッド変位から求めた見かけの値です"
        "（試験機・つかみ具のたわみを含むため、実際より小さめに出ます）。"
    )
    with st.expander("解析詳細"):
        detail_cols = st.columns(4, gap="small")
        with detail_cols[0]:
            st.metric("断面積", f"{ss_result['area[mm2]']:.3f} mm²")
        with detail_cols[1]:
            st.metric("荷重ゼロ", f"{ss_result['load_zero[N]']:.3f} N")
        with detail_cols[2]:
            st.metric("ひずみゼロ", f"{ss_result['strain_zero[%]']:.5f} %")
        with detail_cols[3]:
            st.metric("直線近似 R²", f"{ss_result['fit_r2']:.5f}")
        if "fit_stress_low[MPa]" in ss_result:
            st.write(
                f"直線区間：応力 {ss_result['fit_stress_low[MPa]']:.2f}〜"
                f"{ss_result['fit_stress_high[MPa]']:.2f} MPa"
                f"（{ss_result.get('fit_mode', '自動')}、{ss_result['fit_point_count']}点）"
            )
        crosshead_speed = ss_result.get("crosshead_speed[mm/min]")
        if crosshead_speed is not None:
            # データから計算した値を有効数字2桁に丸めて、設定値（10、1 など）として表示する
            st.write(f"クロスヘッド速度：{crosshead_speed:.2g} mm/min")
    project_bytes = create_project_zip(
        specimen_name, ss_data, ae_data, ss_result, ae_result, get_dimension_details()
    )
    safe_name = specimen_name.strip() if specimen_name.strip() != "" else "analysis"
    safe_name = safe_name.replace("/", "_").replace("\\", "_")
    save_cols = st.columns(2, gap="small")
    with save_cols[0]:
        st.download_button(
            "解析データを保存（ZIP）",
            data=project_bytes,
            file_name=f"{safe_name}_tensile_AE.zip",
            mime="application/zip",
        )
        st.caption("このアプリで、あとから開き直すためのファイル")
    with save_cols[1]:
        # Excel はグラフ画像を作るので少し時間がかかる。ボタンを押したときだけ作る
        signature = result_signature(specimen_name, ss_result)
        excel_cache = st.session_state.get("excel_export")
        if excel_cache is None or excel_cache["signature"] != signature:
            if st.button("Excelファイルを作成"):
                with st.spinner("Excelファイルを作成しています…"):
                    excel_bytes = create_specimen_excel(
                        specimen_name, ss_data, ae_data, ss_result, ae_result, get_dimension_details()
                    )
                st.session_state.excel_export = {"signature": signature, "bytes": excel_bytes}
                st.rerun()
        else:
            st.download_button(
                "Excelファイルをダウンロード",
                data=excel_cache["bytes"],
                file_name=f"{safe_name}_tensile_AE.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        st.caption("寸法・結果・グラフ・データを1つにまとめたファイル")


def render_research_graph(ss_data, ae_data, ss_result=None):
    st.subheader("研究用グラフ")
    graph_setting_cols = st.columns([2, 1, 1, 1], gap="small")
    with graph_setting_cols[0]:
        graph_type = st.selectbox("グラフ種類", GRAPH_TYPES)
    with graph_setting_cols[1]:
        x_axis = st.selectbox("横軸", X_AXES)
    with graph_setting_cols[2]:
        if graph_type != "Stress":
            channel = st.radio("AEチャンネル", ["Ch.1", "Ch.2"], horizontal=True)
        else:
            channel = None
            st.write("AEチャンネル")
            st.caption("―")
    with graph_setting_cols[3]:
        range_mode = st.radio("表示範囲", ["Auto", "Manual"], horizontal=True)
    limit_texts = {}
    if range_mode == "Manual":
        st.caption("空欄の項目は自動設定のままにします")
        manual_cols = st.columns(4, gap="small")
        with manual_cols[0]:
            if x_axis == "Strain [%]":
                manual_x_label = "Strain最大 [%]"
            elif x_axis == "Time [s]":
                manual_x_label = "Time最大 [s]"
            else:
                manual_x_label = "Displacement最大 [mm]"
            limit_texts["x"] = st.text_input(manual_x_label, key="manual_x_max")
        with manual_cols[1]:
            limit_texts["stress"] = st.text_input("Stress最大 [MPa]", key="manual_stress_max")
        if "AE Amplitude" in graph_type:
            with manual_cols[2]:
                limit_texts["amplitude"] = st.text_input("Amplitude最大 [mV]", key="manual_amplitude_max")
        if "Peak Frequency" in graph_type:
            with manual_cols[2]:
                limit_texts["frequency"] = st.text_input("Frequency最大 [kHz]", key="manual_frequency_max")
        if "AE Energy" in graph_type:
            with manual_cols[3]:
                limit_texts["energy"] = st.text_input("Energy最大 [V²/s]", key="manual_energy_max")
    limits = {}
    has_invalid = False
    for key, text in limit_texts.items():
        if text.strip() == "":
            continue
        try:
            limits[key] = float(text)
        except ValueError:
            has_invalid = True
    if has_invalid:
        st.error("表示範囲には数値を入力してください")
    channel_number = 1 if channel != "Ch.2" else 2
    toe_index = None
    if ss_result is not None and ss_result.get("fit_indices"):
        toe_index = int(min(ss_result["fit_indices"]))
    fig, missing = create_research_figure(
        ss_data, ae_data, graph_type, x_axis, channel_number, limits, toe_index
    )
    for message in missing:
        st.error(message)
    st.pyplot(fig)
    plt.close(fig)
    if toe_index is not None:
        st.caption(
            "トウ補正：引っ張り始めの「トウ」の部分は、原点から直線区間の最初の点までを直線で結んで描いています"
            "（データは消していません。トウの部分は「ゼロ点補正・データ確認」で見られます）。"
        )


def render_zero_point_check(ss_data, ss_result, ae_data):
    with st.expander("ゼロ点補正・データ確認"):
        st.caption("必要な場合のみ、ゼロ点補正の状態と元データを確認できます。")
        fig_zero = create_zero_point_figure(ss_data, ss_result)
        st.pyplot(fig_zero)
        plt.close(fig_zero)
        st.write("荷重ゼロ：", f"{ss_result['load_zero[N]']:.3f} N")
        st.write("ひずみゼロ：", f"{ss_result['strain_zero[%]']:.5f} %")
        st.write("直線近似 R²：", f"{ss_result['fit_r2']:.5f}")
        st.subheader("SSデータ確認")
        st.dataframe(
            ss_data[
                [
                    "Time_raw[s]",
                    "Time_corrected[s]",
                    "Strain_raw[%]",
                    "Strain_corrected[%]",
                    "Load[N]",
                    "Load_corrected[N]",
                    "Stress[MPa]",
                ]
            ].head(10)
        )
        st.subheader("AEデータ確認")
        ae_display_columns = ["Strain[-]", "Strain_corrected[%]", "AE_Time_raw[s]", "Time_aligned[s]"]
        if "Ch.1 Amplitude [mV]" in ae_data.columns:
            ae_display_columns.append("Ch.1 Amplitude [mV]")
        st.dataframe(ae_data[ae_display_columns].head(10))
