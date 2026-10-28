"""引張試験（SS）と AE データの解析（ゼロ点補正・直線区間の検出・変位の補完・強度・AE の時間合わせ）。

画面（Streamlit）には依存しない。
"""

import io

import numpy as np
import pandas as pd


def detect_load_zero(data, consecutive=2):
    load = data["Load[N]"].to_numpy()
    first_loads = load[:3]
    initial_median = np.median(first_loads)
    mad = np.median(np.abs(first_loads - initial_median))
    noise = 1.4826 * mad
    threshold = initial_median + max(15.0, 6.0 * noise)
    onset_index = None
    for i in range(len(load) - consecutive + 1):
        if np.all(load[i : i + consecutive] > threshold):
            onset_index = i
            break
    if onset_index is None:
        raise ValueError("荷重の立ち上がりを検出できません")
    if onset_index == 0:
        raise ValueError("無負荷区間を検出できません")
    load_zero = np.mean(load[:onset_index])
    return {"onset_index": onset_index, "load_zero": load_zero, "threshold": threshold}


# 初期直線区間の設定（初期値）
FIT_DEFAULTS = {
    "fit_mode": "自動",
    "fit_manual_low": 5.0,  # 手動指定の下限 [最大応力に対する%]
    "fit_manual_high": 20.0,  # 手動指定の上限 [最大応力に対する%]
}


FIT_SPAN_RATIO = 0.10  # 直線近似に使う区間の最小の応力幅（最大応力の10%）


FIT_SEARCH_MAX_RATIO = 0.60  # 探す範囲の上限（最大応力の60%まで）


FIT_R2_MIN = 0.99  # 「直線」とみなすR²の基準


FIT_MIN_POINTS = 3  # 直線近似に必要な最小点数


FIT_FEW_POINTS = 6  # これより少ないと「点が少ない」と注意を出す


def fit_line(x, y, indices):
    """指定した点に直線を当てはめ、傾き・切片・R²を返す。"""
    if len(indices) < FIT_MIN_POINTS:
        return None
    x_section = x[indices]
    y_section = y[indices]
    if np.ptp(x_section) == 0:
        return None
    slope, intercept = np.polyfit(x_section, y_section, 1)
    y_pred = slope * x_section + intercept
    ss_res = np.sum((y_section - y_pred) ** 2)
    ss_tot = np.sum((y_section - np.mean(y_section)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {
        "slope": slope,
        "intercept": intercept,
        "r2": r2,
        "indices": np.asarray(indices),
    }


def detect_strain_zero_region(data, fit_mode="自動", manual_low=5.0, manual_high=20.0):
    """ひずみゼロを決めるための「初期の直線部分」を探す。

    自動：連続した点のまとまり（応力の幅が最大応力の10%以上、3点以上）を
          1点ずつずらしながら直線を当てはめる。
          「直線」とみなせる区間（R²≥0.99）のうち、傾きが一番大きい区間を選ぶ。
          トウ（立ち上がりのカーブ）と非線形部分はどちらも傾きが小さくなるので、
          傾きが最大の区間 ＝ 最初のきれいな直線部分 になる。
          点の数ではなく「応力の幅」で区間を決めるので、
          記録間隔が長く直線部分の点が少ないデータでも使える。
    手動：最大応力の manual_low%〜manual_high% の区間を使う。
    """
    x = data["Strain_provisional[%]"].to_numpy()
    y = data["Stress[MPa]"].to_numpy()
    valid = np.isfinite(x) & np.isfinite(y)
    if not np.any(valid):
        raise ValueError("応力・ひずみのデータが読み込めませんでした")
    max_index = int(np.nanargmax(np.where(valid, y, -np.inf)))
    max_stress = y[max_index]
    if max_stress <= 0:
        raise ValueError("最大応力が0以下です。荷重データを確認してください")

    # 最大応力までの「引っ張っている途中」のデータだけを使う
    candidate_indices = np.where(valid[: max_index + 1])[0]
    warning = ""

    if fit_mode == "手動":
        if not (0 <= manual_low < manual_high <= 100):
            raise ValueError("直線区間の下限・上限は 0〜100% で、下限 < 上限 になるように入力してください")
        stress_low = max_stress * manual_low / 100
        stress_high = max_stress * manual_high / 100
        mask = (y[candidate_indices] >= stress_low) & (y[candidate_indices] <= stress_high)
        fit = fit_line(x, y, candidate_indices[mask])
        if fit is None:
            raise ValueError(
                f"最大応力の {manual_low:g}〜{manual_high:g}% の範囲にデータが足りません"
                f"（{FIT_MIN_POINTS}点以上必要）。範囲を広げてください"
            )
        if fit["r2"] < FIT_R2_MIN:
            warning = f"指定した区間の直線性が低めです（R²={fit['r2']:.4f}）。範囲を見直してください"
    else:
        # 探す範囲：応力が最大応力の60%を初めて超えるまで
        over = np.where(y[candidate_indices] > max_stress * FIT_SEARCH_MAX_RATIO)[0]
        search = candidate_indices[: over[0]] if len(over) > 0 else candidate_indices
        min_span = max_stress * FIT_SPAN_RATIO

        candidates = []
        for start in range(len(search)):
            low = high = y[search[start]]
            for end in range(start, len(search)):
                low = min(low, y[search[end]])
                high = max(high, y[search[end]])
                if end - start + 1 >= FIT_MIN_POINTS and high - low >= min_span:
                    fit = fit_line(x, y, search[start : end + 1])
                    if fit is not None and fit["slope"] > 0:
                        candidates.append(fit)
                    break

        if len(candidates) == 0:
            raise ValueError(
                "初期の直線部分を自動で見つけられませんでした。"
                "「直線区間の設定」を「手動」にして、範囲を指定してください"
            )
        good = [c for c in candidates if c["r2"] >= FIT_R2_MIN]
        if good:
            fit = max(good, key=lambda c: c["slope"])
        else:
            fit = max(candidates, key=lambda c: c["slope"])
            warning = (
                f"直線性の高い区間が見つからなかったため、最も傾きが大きい区間を使いました"
                f"（R²={fit['r2']:.4f}）。ゼロ点補正のグラフを確認してください"
            )

    if fit["slope"] <= 0:
        raise ValueError("直線区間の傾きが0以下です。範囲を見直してください")

    indices = fit["indices"]
    if len(indices) < FIT_FEW_POINTS:
        few_points = (
            f"直線部分のデータが{len(indices)}点しかないため、ひずみゼロと弾性率の精度が低い可能性があります。"
            "データの記録間隔を短くすると改善します"
        )
        warning = f"{warning}　{few_points}" if warning else few_points

    return {
        "start[%]": float(np.min(x[indices])),
        "end[%]": float(np.max(x[indices])),
        "stress_low[MPa]": float(np.min(y[indices])),
        "stress_high[MPa]": float(np.max(y[indices])),
        "slope": fit["slope"],
        "intercept": fit["intercept"],
        "r2": fit["r2"],
        "point_count": len(indices),
        "zero_in_provisional[%]": -fit["intercept"] / fit["slope"],
        "indices": indices,
        "warning": warning,
        "mode": fit_mode,
    }


def prepare_ss_mechanics(
    data,
    load_result,
    width,
    thickness,
    gauge_length,
    fit_mode="自動",
    fit_manual_low=5.0,
    fit_manual_high=20.0,
):
    data = data.copy()
    area = width * thickness
    data["Stress[MPa]"] = data["Load_corrected[N]"] / area
    data["Displacement_raw[mm]"] = data["Strain[-]"] / 500
    data["Strain_raw"] = data["Displacement_raw[mm]"] / gauge_length
    data["Strain_raw[%]"] = data["Strain_raw"] * 100
    onset_index = load_result["onset_index"]
    previous_index = onset_index - 1
    x1 = data.loc[previous_index, "Strain_raw[%]"]
    x2 = data.loc[onset_index, "Strain_raw[%]"]
    y1 = data.loc[previous_index, "Load_corrected[N]"]
    y2 = data.loc[onset_index, "Load_corrected[N]"]
    if y2 == y1:
        provisional_zero = x1
    else:
        provisional_zero = x1 + (0 - y1) * (x2 - x1) / (y2 - y1)
    data["Strain_provisional[%]"] = data["Strain_raw[%]"] - provisional_zero
    fit_result = detect_strain_zero_region(data, fit_mode, fit_manual_low, fit_manual_high)
    zero_shift = fit_result["zero_in_provisional[%]"]
    final_zero = provisional_zero + zero_shift
    data["Strain_corrected[%]"] = data["Strain_raw[%]"] - final_zero
    strain_corrected = data["Strain_corrected[%]"].to_numpy()
    time_raw = data["Time_raw[s]"].to_numpy()
    crossing_indices = np.where((strain_corrected[:-1] < 0) & (strain_corrected[1:] >= 0))[0]
    if len(crossing_indices) > 0:
        i = crossing_indices[0]
        strain1 = strain_corrected[i]
        strain2 = strain_corrected[i + 1]
        time1 = time_raw[i]
        time2 = time_raw[i + 1]
        if strain2 == strain1:
            time_zero = time1
        else:
            time_zero = time1 + (0 - strain1) * (time2 - time1) / (strain2 - strain1)
    else:
        # ひずみ0%がデータの記録開始より前にある場合：
        # クロスヘッドは一定の速さで動くので、直線区間の「時間-ひずみ」の関係を延長して求める
        fit_indices = fit_result["indices"]
        time_slope, time_intercept = np.polyfit(strain_corrected[fit_indices], time_raw[fit_indices], 1)
        time_zero = time_intercept
    data["Time_corrected[s]"] = data["Time_raw[s]"] - time_zero
    data["Strain_corrected"] = data["Strain_corrected[%]"] / 100
    data["Displacement_corrected[mm]"] = data["Strain_corrected"] * gauge_length
    result = {
        "width[mm]": width,
        "thickness[mm]": thickness,
        "gauge_length[mm]": gauge_length,
        "area[mm2]": area,
        "load_zero[N]": load_result["load_zero"],
        "strain_zero[%]": final_zero,
        "time_zero[s]": time_zero,
        "fit_start[%]": fit_result["start[%]"],
        "fit_end[%]": fit_result["end[%]"],
        "fit_r2": fit_result["r2"],
        "fit_point_count": fit_result["point_count"],
        "fit_slope": fit_result["slope"],
        "fit_intercept": fit_result["intercept"],
        "fit_indices": fit_result["indices"].tolist(),
    }
    # 弾性率：直線部分の傾き [MPa/%] → [MPa] → [GPa]
    result["modulus[GPa]"] = fit_result["slope"] * 100 / 1000
    result["fit_stress_low[MPa]"] = fit_result["stress_low[MPa]"]
    result["fit_stress_high[MPa]"] = fit_result["stress_high[MPa]"]
    result["fit_mode"] = fit_result["mode"]
    result["fit_manual_low[%]"] = fit_manual_low
    result["fit_manual_high[%]"] = fit_manual_high
    result["fit_warning"] = fit_result["warning"]
    # 変位の途切れと、データから求めたクロスヘッド速度
    gap = load_result.get("displacement_gap")
    result["disp_gap_message"] = gap["message"] if gap else ""
    result["disp_fill_applied"] = bool(gap and gap["applied"])
    if result["disp_fill_applied"]:
        for key in ["start_time[ms]", "end_time[ms]", "slope[mm/s]", "intercept[mm]", "filled_points"]:
            result[f"disp_fill_{key}"] = gap[key]
    result["crosshead_speed[mm/min]"] = estimate_crosshead_speed(data, onset_index)
    return (data, result)


def analyze_strength(data):
    stress = data["Stress[MPa]"].to_numpy()
    strain = data["Strain_corrected[%]"].to_numpy()
    max_index = np.argmax(stress)
    max_stress = stress[max_index]
    stress_after_max = stress[max_index:]
    if len(stress_after_max) < 2:
        raise ValueError("最大応力後のデータが不足しています")
    stress_difference = np.diff(stress_after_max)
    largest_drop_local_index = np.argmin(stress_difference)
    largest_drop = stress_difference[largest_drop_local_index]
    if largest_drop >= 0:
        raise ValueError("最大応力後に応力低下が見つかりません")
    fracture_index = max_index + largest_drop_local_index
    fracture_strain = strain[fracture_index]
    return {
        "max_stress[MPa]": max_stress,
        "max_index": max_index,
        "fracture_strain[%]": fracture_strain,
        "fracture_index": fracture_index,
        "fracture_drop[MPa]": largest_drop,
    }


def read_ae_data(uploaded_file):
    uploaded_file.seek(0)
    data = pd.read_csv(uploaded_file, sep="\t")
    data.columns = data.columns.str.strip()
    required_columns = ["Time[ms]", "Strain[-]"]
    for column in required_columns:
        if column not in data.columns:
            raise ValueError(f"AEファイルに {column} がありません")
    possible_columns = [
        "Time[ms]",
        "Strain[-]",
        "Strain_recorded[-]",
        "Load[N]",
        "Ch.1 Amplitude [mV]",
        "Ch.2 Amplitude [mV]",
        "Ch.1 Energy [V^2/s]",
        "Ch.2 Energy [V^2/s]",
        "Ch.1 AE Peak Frequency [kHz]",
        "Ch.2 AE Peak Frequency [kHz]",
    ]
    for column in possible_columns:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["Time[ms]", "Strain[-]"]).reset_index(drop=True)
    if len(data) == 0:
        raise ValueError("AEデータを読み込めませんでした")
    return data


def fill_ae_displacement(data, ss_result):
    """SSで変位の途切れを補った場合、同じ時間帯のAEイベントの変位も同じ直線で補う。

    AEファイルとSSファイルは同じ時計で記録されている前提。補った件数を返す。
    """
    # 保存済みZIPのデータには、補う前の変位が Strain_recorded[-] として残っている
    if "Strain_recorded[-]" in data.columns:
        data["Strain[-]"] = data["Strain_recorded[-]"]
    else:
        data["Strain_recorded[-]"] = data["Strain[-]"]
    if not ss_result.get("disp_fill_applied"):
        return 0
    gap = {
        "start_time[ms]": ss_result["disp_fill_start_time[ms]"],
        "slope[mm/s]": ss_result["disp_fill_slope[mm/s]"],
        "intercept[mm]": ss_result["disp_fill_intercept[mm]"],
    }
    in_gap = (data["Time[ms]"] >= gap["start_time[ms]"]) & (
        data["Time[ms]"] < ss_result["disp_fill_end_time[ms]"]
    )
    data.loc[in_gap, "Strain[-]"] = displacement_from_fill(data.loc[in_gap, "Time[ms]"].to_numpy(), gap) * 500
    return int(in_gap.sum())


def prepare_ae_data(uploaded_file, ss_data, ss_result):
    data = read_ae_data(uploaded_file)
    filled_count = fill_ae_displacement(data, ss_result)
    gauge_length = ss_result["gauge_length[mm]"]
    data["AE_Time_raw[s]"] = (data["Time[ms]"] - data["Time[ms]"].iloc[0]) / 1000
    data["Displacement_raw[mm]"] = data["Strain[-]"] / 500
    data["Strain_raw"] = data["Displacement_raw[mm]"] / gauge_length
    data["Strain_raw[%]"] = data["Strain_raw"] * 100
    strain_zero = ss_result["strain_zero[%]"]
    data["Strain_corrected[%]"] = data["Strain_raw[%]"] - strain_zero
    data["Strain_corrected"] = data["Strain_corrected[%]"] / 100
    data["Displacement_corrected[mm]"] = data["Strain_corrected"] * gauge_length
    ss_strain = ss_data["Strain_corrected[%]"].to_numpy()
    ss_time = ss_data["Time_corrected[s]"].to_numpy()
    valid = np.isfinite(ss_strain) & np.isfinite(ss_time)
    ss_strain_valid = ss_strain[valid]
    ss_time_valid = ss_time[valid]
    order = np.argsort(ss_strain_valid)
    ss_strain_sorted = ss_strain_valid[order]
    ss_time_sorted = ss_time_valid[order]
    unique_strain, unique_index = np.unique(ss_strain_sorted, return_index=True)
    unique_time = ss_time_sorted[unique_index]
    data["Time_aligned[s]"] = np.interp(
        data["Strain_corrected[%]"], unique_strain, unique_time, left=np.nan, right=np.nan
    )
    for channel in [1, 2]:
        energy_column = f"Ch.{channel} Energy [V^2/s]"
        cumulative_column = f"Ch.{channel} Cumulative Energy"
        if energy_column in data.columns:
            energy = pd.to_numeric(data[energy_column], errors="coerce").fillna(0)
            data[cumulative_column] = energy.cumsum()
    result = {
        "event_count": len(data),
        "strain_min[%]": data["Strain_corrected[%]"].min(),
        "strain_max[%]": data["Strain_corrected[%]"].max(),
        "disp_filled_count": filled_count,
    }
    return (data, result)


# 変位の線をつなぎ忘れて途中でつないだ場合など、変位の記録が途切れると、
# つないだ瞬間に変位が大きく「跳ぶ」。クロスヘッドは一定の速さで動いているので、
# つないだ後の「変位-時間」の直線を延長して（速度 × 時間）、途切れていた区間を補う。
DISP_JUMP_MIN_MM = 0.5  # これより大きく変位が跳んだら「途切れ」の候補


DISP_JUMP_RATIO = 20  # ふだんの1点あたりの変化の何倍以上なら「跳んだ」とみなすか


DISP_FIT_MAX_RESIDUAL_MM = 0.05  # 補うための直線からのずれの許容値


DISP_FIT_MIN_POINTS = 10  # 補うための直線に必要な最小点数


def detect_displacement_gap(time_ms, disp_mm, load):
    """変位の記録が途切れていたかを調べ、補うための直線を求める。

    途切れが無ければ None を返す。
    途切れがあれば、補えるときは applied=True と直線の情報、
    補えないときは applied=False と理由を返す。
    """
    n = len(disp_mm)
    if n < DISP_FIT_MIN_POINTS:
        return None
    max_index = int(np.argmax(load))
    if max_index < 5:
        return None

    # 引っ張っている途中（最大荷重まで）の、1点ごとの変位の変化
    steps = np.diff(disp_mm[: max_index + 1])
    typical_step = np.median(np.abs(steps))
    jump_limit = max(DISP_JUMP_MIN_MM, DISP_JUMP_RATIO * typical_step)
    jump_candidates = np.where(steps > jump_limit)[0]
    if len(jump_candidates) == 0:
        return None

    jump_at = int(jump_candidates[np.argmax(steps[jump_candidates])])
    first_after = jump_at + 1
    jump_size = steps[jump_at]
    end_time_s = (time_ms[first_after] - time_ms[0]) / 1000
    not_filled = {
        "applied": False,
        "message": (
            f"変位の記録が {end_time_s:.0f} 秒あたりで {jump_size:.2f} mm 跳んでいます。"
            "自動で補えなかったので、変位のデータと結果を確認してください"
        ),
    }

    # 跳ぶ前に変位がほとんど動いていない（＝記録が止まっていた）場合だけ補う
    if np.ptp(disp_mm[:first_after]) > 0.5 * jump_size:
        return not_filled

    # つないだ後（最大荷重まで）の「変位-時間」の直線
    segment = np.arange(first_after, max_index + 1)
    if len(segment) < DISP_FIT_MIN_POINTS:
        return not_filled
    time_s = (time_ms - time_ms[0]) / 1000
    slope, intercept = np.polyfit(time_s[segment], disp_mm[segment], 1)
    residual = np.std(disp_mm[segment] - (slope * time_s[segment] + intercept))
    if slope <= 0 or residual > DISP_FIT_MAX_RESIDUAL_MM:
        return not_filled

    return {
        "applied": True,
        "first_after_index": first_after,
        "start_time[ms]": float(time_ms[0]),
        "end_time[ms]": float(time_ms[first_after]),
        "slope[mm/s]": float(slope),
        "intercept[mm]": float(intercept),
        "residual[mm]": float(residual),
        "filled_points": first_after,
        "message": (
            f"変位の記録が {end_time_s:.0f} 秒まで途切れていたため（{first_after}点）、"
            f"その区間の変位を「クロスヘッド速度 × 時間」（{slope * 60:.2g} mm/min）で補いました"
        ),
    }


def displacement_from_fill(time_ms, gap):
    """補うための直線から、指定した時刻の変位 [mm] を求める。"""
    return gap["intercept[mm]"] + gap["slope[mm/s]"] * (time_ms - gap["start_time[ms]"]) / 1000


def estimate_crosshead_speed(data, onset_index):
    """引っ張り始めから最大荷重までの「変位-時間」の傾きから、クロスヘッド速度 [mm/min] を求める。"""
    max_index = int(np.argmax(data["Load[N]"].to_numpy()))
    if max_index - onset_index < 3:
        return None
    time_s = data["Time_raw[s]"].to_numpy()[onset_index : max_index + 1]
    disp_mm = data["Strain[-]"].to_numpy()[onset_index : max_index + 1] / 500
    if np.ptp(time_s) == 0:
        return None
    return float(np.polyfit(time_s, disp_mm, 1)[0] * 60)


def prepare_ss_raw(ss_source):
    """SSデータの列をそろえ、変位の途切れを補い、荷重のゼロ点を補正する。"""
    ss_source = ss_source.copy()
    ss_source.columns = ss_source.columns.astype(str).str.strip()
    # 保存済みZIPのデータには、補う前の変位が Strain_recorded[-] として残っている
    if "Strain_recorded[-]" in ss_source.columns:
        ss_source["Strain[-]"] = ss_source["Strain_recorded[-]"]
    required_columns = ["Time[ms]", "Strain[-]", "Load[N]"]
    for column in required_columns:
        if column not in ss_source.columns:
            raise ValueError(f"SSファイルに {column} の列がありません")
    ss_data = ss_source[required_columns].copy()
    for column in required_columns:
        ss_data[column] = pd.to_numeric(ss_data[column], errors="coerce")
    ss_data = ss_data.dropna(subset=required_columns).reset_index(drop=True)
    if len(ss_data) < 10:
        raise ValueError("SSファイルのデータが少なすぎます")

    # 変位の途切れを補う（補う前の値は Strain_recorded[-] に残す）
    ss_data["Strain_recorded[-]"] = ss_data["Strain[-]"]
    time_ms = ss_data["Time[ms]"].to_numpy()
    gap = detect_displacement_gap(
        time_ms,
        ss_data["Strain[-]"].to_numpy() / 500,
        ss_data["Load[N]"].to_numpy(),
    )
    if gap is not None and gap["applied"]:
        filled = ss_data.index[: gap["first_after_index"]]
        ss_data.loc[filled, "Strain[-]"] = (
            displacement_from_fill(time_ms[: gap["first_after_index"]], gap) * 500
        )

    ss_data["Time_raw[s]"] = (ss_data["Time[ms]"] - ss_data["Time[ms]"].iloc[0]) / 1000
    load_result = detect_load_zero(ss_data)
    load_result["displacement_gap"] = gap
    ss_data["Load_corrected[N]"] = ss_data["Load[N]"] - load_result["load_zero"]
    return (ss_data, load_result)


def reanalyze_project_data(
    ss_source,
    ae_source,
    width,
    thickness,
    gauge_length,
    fit_mode="自動",
    fit_manual_low=5.0,
    fit_manual_high=20.0,
):
    ss_data, load_result = prepare_ss_raw(ss_source)
    ss_data, ss_result = prepare_ss_mechanics(
        ss_data, load_result, width, thickness, gauge_length, fit_mode, fit_manual_low, fit_manual_high
    )
    strength_result = analyze_strength(ss_data)
    ss_result.update(strength_result)
    ae_buffer = io.BytesIO(ae_source.to_csv(sep="\t", index=False).encode("utf-8"))
    ae_data, ae_result = prepare_ae_data(ae_buffer, ss_data, ss_result)
    return (ss_data, ss_result, ae_data, ae_result)


def analyze_file_bytes(ss_bytes, ae_bytes, width, thickness, gauge_length, fit_settings):
    """SS・AE ファイルの中身から解析する（「新しく解析する」と同じ手順）。"""
    ss_source = pd.read_csv(io.BytesIO(ss_bytes), sep="\t")
    ss_data, load_result = prepare_ss_raw(ss_source)
    ss_data, ss_result = prepare_ss_mechanics(
        ss_data, load_result, width, thickness, gauge_length, *fit_settings
    )
    ss_result.update(analyze_strength(ss_data))
    ae_data, ae_result = prepare_ae_data(io.BytesIO(ae_bytes), ss_data, ss_result)
    return ss_data, ss_result, ae_data, ae_result
