"""出力（Excel・ZIP）のテスト。"""

import io

import openpyxl
import pytest

from tensile import analysis, excel_export, project_io

DETAILS = {
    "width_values": ["15.02", "", "14.98"] + [""] * 6,
    "thickness_values": [""] * 9,
    "gauge_values": [""] * 3,
}


def analyzed(sample, name="sample_45deg"):
    return analysis.reanalyze_project_data(*sample[name], 15.0, 2.0, 60.0)


def test_excel_has_sheets_formulas_and_charts(sample):
    ss_data, ss_result, ae_data, ae_result = analyzed(sample)
    content = excel_export.create_specimen_excel("A-1", ss_data, ae_data, ss_result, ae_result, DETAILS)
    wb = openpyxl.load_workbook(io.BytesIO(content))
    assert wb.sheetnames == ["概要", "グラフ", "SS補正後データ", "AE補正後データ", "SS元データ", "AE元データ"]
    summary = wb["概要"]
    # 寸法は「詳細寸法に入力があれば平均、なければ直接入力」の数式
    assert str(summary["B10"].value).startswith("=IF(COUNT(")
    assert summary["B13"].value == "=B10*B11"
    assert len(wb["グラフ"]._charts) >= 4


def test_project_zip_round_trip(sample):
    ss_data, ss_result, ae_data, ae_result = analyzed(sample)
    content = project_io.create_project_zip("A-1", ss_data, ae_data, ss_result, ae_result, DETAILS)
    name, ss2, ae2, ss_result2, _, details2 = project_io.load_project_zip(io.BytesIO(content))
    assert name == "A-1"
    assert details2 == DETAILS
    assert ss_result2["max_stress[MPa]"] == ss_result["max_stress[MPa]"]
    # 開き直したデータで解析し直しても、同じ結果になる
    _, again, _, _ = analysis.reanalyze_project_data(ss2, ae2, 15.0, 2.0, 60.0)
    assert again["modulus[GPa]"] == pytest.approx(ss_result["modulus[GPa]"], rel=1e-9)


def test_result_signature_changes_with_result(sample):
    _, ss_result, _, _ = analyzed(sample)
    other = dict(ss_result, **{"width[mm]": 14.0})
    assert project_io.result_signature("A", ss_result) != project_io.result_signature("A", other)
    assert project_io.result_signature("A", ss_result) == project_io.result_signature("A", dict(ss_result))
