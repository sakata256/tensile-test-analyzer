"""解析（ゼロ点補正・直線区間・弾性率・変位の補完）のテスト。作りもののデータを使う。"""

import numpy as np
import pytest

from tensile import analysis

DIMENSIONS = (15.0, 2.0, 60.0)
DESIGNED_MAX_STRESS = {"sample_45deg": 150.0, "sample_50deg": 110.0, "sample_0deg": 600.0}


def run(ss, ae, dimensions=DIMENSIONS, **fit):
    return analysis.reanalyze_project_data(ss, ae, *dimensions, **fit)


@pytest.mark.parametrize("name", list(DESIGNED_MAX_STRESS))
def test_max_stress_matches_design(sample, name):
    """荷重計のずれ（−30 N）を取り除いたあとの最大応力が、作ったときの値と合う。"""
    ss, ae = sample[name]
    _, result, _, ae_result = run(ss, ae)
    assert result["max_stress[MPa]"] == pytest.approx(DESIGNED_MAX_STRESS[name], rel=0.005)
    assert result["load_zero[N]"] == pytest.approx(-30.0, abs=3.0)
    assert ae_result["event_count"] == len(ae)


def test_modulus_of_linear_material(sample):
    """直線的な材料（0°材のつもり）では、弾性率が作ったときの値（40 GPa）と合う。"""
    _, result, _, _ = run(*sample["sample_0deg"])
    assert result["modulus[GPa]"] == pytest.approx(40.0, rel=0.01)
    assert result["fit_r2"] >= 0.99


@pytest.mark.parametrize("name", list(DESIGNED_MAX_STRESS))
def test_toe_compensation_puts_fit_line_through_origin(sample, name):
    """トウ補正：直線区間の延長が、補正後の原点（応力 0・ひずみ 0）を通る。"""
    data, result, _, _ = run(*sample[name])
    fit = data.iloc[result["fit_indices"]]
    slope, intercept = np.polyfit(fit["Strain_corrected[%]"], fit["Stress[MPa]"], 1)
    assert abs(intercept) < 0.01 * result["max_stress[MPa]"]
    assert result["fit_r2"] >= 0.99


def test_scaling_dimensions_scales_stress(sample):
    """断面積を 1.05 倍にすると、最大応力は 1/1.05 倍になる（弾性率も同じ比で変わる）。"""
    ss, ae = sample["sample_50deg"]
    _, base, _, _ = run(ss, ae)
    _, wide, _, _ = run(ss, ae, dimensions=(15.0 * 1.05, 2.0, 60.0))
    assert wide["max_stress[MPa]"] == pytest.approx(base["max_stress[MPa]"] / 1.05, rel=1e-9)


def test_manual_fit_range(sample):
    """手動モード：指定した応力の範囲（最大応力の %）で直線を当てはめる。"""
    _, result, _, _ = run(*sample["sample_45deg"], fit_mode="手動", fit_manual_low=10.0, fit_manual_high=30.0)
    assert result["fit_mode"] == "手動"
    assert result["fit_stress_low[MPa]"] >= 0.10 * result["max_stress[MPa]"] - 1e-9
    assert result["fit_stress_high[MPa]"] <= 0.30 * result["max_stress[MPa]"] + 1e-9


def test_displacement_gap_is_filled(sample):
    """変位の記録が途中まで止まっていた（線のつなぎ忘れ）データを、速度 × 時間で補う。"""
    ss, ae = sample["sample_45deg"]
    _, original, _, _ = run(ss, ae)
    broken = ss.copy()
    gap_end = 400  # 400 行目（40 秒）までは変位が記録されていなかったことにする
    broken.loc[: gap_end - 1, "Strain[-]"] = broken.loc[0, "Strain[-]"]
    _, filled, _, _ = run(broken, ae)
    assert filled["disp_fill_applied"]
    assert filled["disp_gap_message"]
    assert filled["modulus[GPa]"] == pytest.approx(original["modulus[GPa]"], rel=0.03)
    assert filled["max_stress[MPa]"] == pytest.approx(original["max_stress[MPa]"], rel=1e-9)


def test_jump_while_moving_is_not_filled(sample):
    """記録が動いている途中で変位が跳んだときは、補わずに注意だけ出す。"""
    ss, ae = sample["sample_45deg"]
    glitch = ss.copy()
    glitch.loc[700:, "Strain[-]"] += 2.0 * 500  # 700 行目から 2 mm 跳ぶ
    _, result, _, _ = run(glitch, ae)
    assert not result["disp_fill_applied"]
    assert result["disp_gap_message"]


def test_analyze_file_bytes_matches_dataframe_path(sample_files):
    """ファイルの中身から解析しても、表から解析したときと同じ結果になる。"""
    import pandas as pd

    ss_path, ae_path = sample_files["sample_50deg"]
    fit = ("自動", 5.0, 20.0)
    _, from_bytes, _, _ = analysis.analyze_file_bytes(
        ss_path.read_bytes(), ae_path.read_bytes(), *DIMENSIONS, fit
    )
    _, from_frame, _, _ = run(pd.read_csv(ss_path, sep="\t"), pd.read_csv(ae_path, sep="\t"))
    for key in ["max_stress[MPa]", "fracture_strain[%]", "modulus[GPa]", "strain_zero[%]"]:
        assert from_bytes[key] == pytest.approx(from_frame[key], rel=1e-9)
