"""「新しく解析する」「保存済み解析を開く」の画面。"""

import pandas as pd
import streamlit as st

from tensile.analysis import (
    FIT_DEFAULTS,
    analyze_strength,
    prepare_ae_data,
    prepare_ss_mechanics,
    prepare_ss_raw,
    reanalyze_project_data,
)
from tensile.project_io import load_project_zip
from tensile.ui_common import (
    get_fit_settings,
    invalidate_analysis,
    render_dimension_detail_inputs,
    render_fit_settings,
    reset_project_selection,
)


def render_saved_analysis_mode():
    st.header("解析データを開く")

    project_file = st.file_uploader(
        "保存済み解析ファイル",
        type=["zip"],
        key="project_file",
        on_change=reset_project_selection,
    )

    if st.button("解析データを読み込む"):
        if project_file is None:
            st.error("解析データファイルを選択してください")
        else:
            try:
                (
                    loaded_name,
                    loaded_ss_data,
                    loaded_ae_data,
                    loaded_ss_result,
                    loaded_ae_result,
                    loaded_dimension_details,
                ) = load_project_zip(project_file)

                st.session_state.ss_data = loaded_ss_data
                st.session_state.ae_data = loaded_ae_data
                st.session_state.ss_result = loaded_ss_result
                st.session_state.ae_result = loaded_ae_result
                st.session_state.specimen_name = loaded_name

                st.session_state.width = loaded_ss_result["width[mm]"]
                st.session_state.thickness = loaded_ss_result["thickness[mm]"]
                st.session_state.gauge_length = loaded_ss_result["gauge_length[mm]"]

                width_values = loaded_dimension_details.get("width_values", [])
                thickness_values = loaded_dimension_details.get("thickness_values", [])
                gauge_values = loaded_dimension_details.get("gauge_values", [])

                for i in range(9):
                    st.session_state[f"detail_width_{i}"] = width_values[i] if i < len(width_values) else ""
                    st.session_state[f"detail_thickness_{i}"] = (
                        thickness_values[i] if i < len(thickness_values) else ""
                    )

                for i in range(3):
                    st.session_state[f"detail_gauge_{i}"] = gauge_values[i] if i < len(gauge_values) else ""

                # 直線区間の設定を復元（古いZIPには無いので初期値のまま）
                st.session_state.fit_mode = loaded_ss_result.get("fit_mode", FIT_DEFAULTS["fit_mode"])
                st.session_state.fit_manual_low = float(
                    loaded_ss_result.get("fit_manual_low[%]", FIT_DEFAULTS["fit_manual_low"])
                )
                st.session_state.fit_manual_high = float(
                    loaded_ss_result.get("fit_manual_high[%]", FIT_DEFAULTS["fit_manual_high"])
                )

                st.session_state.analysis_done = True
                st.session_state.analysis_source = "project"
                st.success("解析データを読み込みました")

            except Exception as error:
                st.error(f"読込エラー：{error}")

    if st.session_state.get("analysis_source") != "project":
        return

    st.caption("ZIPに保存されていた寸法です。必要な場合だけ変更してください。")

    dimension_cols = st.columns(3, gap="small")

    with dimension_cols[0]:
        project_width = st.number_input(
            "幅 [mm]",
            min_value=0.0,
            key="width",
            on_change=invalidate_analysis,
        )

    with dimension_cols[1]:
        project_thickness = st.number_input(
            "厚み [mm]",
            min_value=0.0,
            key="thickness",
            on_change=invalidate_analysis,
        )

    with dimension_cols[2]:
        project_gauge_length = st.number_input(
            "ゲージ長さ [mm]",
            min_value=0.0,
            key="gauge_length",
            on_change=invalidate_analysis,
        )

    render_dimension_detail_inputs(button_key="apply_project_dimension_details")
    render_fit_settings()

    if st.button("この条件で再解析"):
        if project_width <= 0 or project_thickness <= 0 or project_gauge_length <= 0:
            st.error("寸法は0より大きい値を入力してください")
            return

        try:
            (
                new_ss_data,
                new_ss_result,
                new_ae_data,
                new_ae_result,
            ) = reanalyze_project_data(
                st.session_state.ss_data,
                st.session_state.ae_data,
                project_width,
                project_thickness,
                project_gauge_length,
                *get_fit_settings(),
            )

            st.session_state.ss_data = new_ss_data
            st.session_state.ss_result = new_ss_result
            st.session_state.ae_data = new_ae_data
            st.session_state.ae_result = new_ae_result
            st.session_state.analysis_done = True
            st.session_state.analysis_source = "project"

            st.success("変更した条件で再解析しました")

        except Exception as error:
            st.error(f"再解析エラー：{error}")


def render_new_analysis_mode():
    st.header("解析条件")

    data_cols = st.columns([1, 1, 1], gap="small")

    with data_cols[0]:
        st.text_input(
            "試験片名",
            key="specimen_name",
        )

    with data_cols[1]:
        ss_file = st.file_uploader(
            "SSファイルを選択",
            type=["txt"],
            key="new_ss_file",
            on_change=invalidate_analysis,
        )

    with data_cols[2]:
        ae_file = st.file_uploader(
            "AEファイルを選択",
            type=["txt"],
            key="new_ae_file",
            on_change=invalidate_analysis,
        )

    dimension_cols = st.columns(3, gap="small")

    with dimension_cols[0]:
        width = st.number_input(
            "幅 [mm]",
            min_value=0.0,
            key="width",
            on_change=invalidate_analysis,
        )

    with dimension_cols[1]:
        thickness = st.number_input(
            "厚み [mm]",
            min_value=0.0,
            key="thickness",
            on_change=invalidate_analysis,
        )

    with dimension_cols[2]:
        gauge_length = st.number_input(
            "ゲージ長さ [mm]",
            min_value=0.0,
            key="gauge_length",
            on_change=invalidate_analysis,
        )

    render_dimension_detail_inputs()
    render_fit_settings()

    if not st.button("解析開始"):
        return

    if ss_file is None:
        st.error("SSファイルを選択してください")
        return

    if ae_file is None:
        st.error("AEファイルを選択してください")
        return

    if width <= 0 or thickness <= 0 or gauge_length <= 0:
        st.error("寸法は0より大きい値を入力してください")
        return

    try:
        ss_file.seek(0)
        ss_source = pd.read_csv(ss_file, sep="\t")
        ss_data, load_result = prepare_ss_raw(ss_source)

        ss_data, ss_result = prepare_ss_mechanics(
            ss_data,
            load_result,
            width,
            thickness,
            gauge_length,
            *get_fit_settings(),
        )

        strength_result = analyze_strength(ss_data)
        ss_result.update(strength_result)

        ae_data, ae_result = prepare_ae_data(
            ae_file,
            ss_data,
            ss_result,
        )

        st.session_state.ss_data = ss_data
        st.session_state.ss_result = ss_result
        st.session_state.ae_data = ae_data
        st.session_state.ae_result = ae_result
        st.session_state.analysis_done = True
        st.session_state.analysis_source = "new"

    except Exception as error:
        st.error(f"解析エラー：{error}")
