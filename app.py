"""引張試験・AE 解析ツール（Streamlit アプリの入口）。

起動: python -m streamlit run app.py
"""

import streamlit as st

from tensile.ui_analysis import render_new_analysis_mode, render_saved_analysis_mode
from tensile.ui_common import (
    initialize_app,
    render_research_graph,
    render_result_summary,
    render_zero_point_check,
)
from tensile.ui_specimens import render_specimen_mode, specimen_list_configured


def should_show_results(mode):
    """現在のモードに対応する解析結果だけを表示する。"""
    if not st.session_state.analysis_done:
        return False

    if mode == "試験片の一覧":
        # 開いている試験片を解析した結果だけを出す
        return (
            st.session_state.analysis_source == "specimen"
            and st.session_state.get("specimen_page_shown", False)
            and st.session_state.get("analysis_specimen_id") is not None
            and st.session_state.get("analysis_specimen_id") == st.session_state.get("opened_specimen_id")
        )

    if mode == "新しく解析する":
        return st.session_state.analysis_source == "new"

    return st.session_state.analysis_source == "project"


def main():
    initialize_app()
    st.session_state.specimen_page_shown = False

    st.title("引張試験・AE解析ツール")

    # 台帳の設定がないとき（解析だけの公開版など）は「試験片の一覧」を出さない
    modes = ["新しく解析する", "保存済み解析を開く"]
    if specimen_list_configured():
        modes.insert(0, "試験片の一覧")
    mode = st.radio("使用方法", modes, horizontal=True)

    if mode == "試験片の一覧":
        render_specimen_mode()
    elif mode == "新しく解析する":
        render_new_analysis_mode()
    else:
        render_saved_analysis_mode()

    if not should_show_results(mode):
        return

    specimen_name = st.session_state.specimen_name
    ss_data = st.session_state.ss_data
    ss_result = st.session_state.ss_result
    ae_data = st.session_state.ae_data
    ae_result = st.session_state.ae_result

    render_result_summary(
        specimen_name,
        ss_data,
        ss_result,
        ae_data,
        ae_result,
    )
    render_research_graph(ss_data, ae_data, ss_result)
    render_zero_point_check(ss_data, ss_result, ae_data)


if __name__ == "__main__":
    main()
