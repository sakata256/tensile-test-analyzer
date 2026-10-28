"""研究用グラフとゼロ点補正の確認グラフ（matplotlib）。"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

GRAPH_TYPES = [
    "Stress",
    "Stress + AE Amplitude",
    "Stress + AE Amplitude + AE Energy",
    "Stress + Peak Frequency",
    "Stress + Peak Frequency + AE Energy",
]


X_AXES = ["Strain [%]", "Time [s]", "Displacement [mm]"]


def create_research_figure(
    ss_data, ae_data, graph_type, x_axis, channel_number=1, limits=None, toe_index=None
):
    """研究用グラフの図を作る。

    limits：表示範囲の最大値 {'x', 'stress', 'amplitude', 'frequency', 'energy'}（None は自動）
    toe_index：直線区間の最初の点。指定すると、それより前（トウ）は描かずに、
               原点からその点までを直線で結ぶ（トウ補正したグラフ）
    戻り値：(図, 足りない列のメッセージのリスト)
    """
    limits = limits or {}
    missing = []
    if x_axis == "Strain [%]":
        ss_x = ss_data["Strain_corrected[%]"]
        ae_x = ae_data["Strain_corrected[%]"]
    elif x_axis == "Time [s]":
        ss_x = ss_data["Time_corrected[s]"]
        ae_x = ae_data["Time_aligned[s]"]
    else:
        ss_x = ss_data["Displacement_corrected[mm]"]
        ae_x = ae_data["Displacement_corrected[mm]"]
    fig, ax_stress = plt.subplots(figsize=(10, 6))
    ax_ae = None
    ax_energy = None
    stress = ss_data["Stress[MPa]"]
    if toe_index is not None and 0 < toe_index < len(ss_data):
        ss_x = pd.concat([pd.Series([0.0]), ss_x.iloc[toe_index:]], ignore_index=True)
        stress = pd.concat([pd.Series([0.0]), stress.iloc[toe_index:]], ignore_index=True)
    ax_stress.plot(ss_x, stress, linewidth=1.5, label="Stress")
    ax_stress.set_xlabel(x_axis)
    ax_stress.set_ylabel("Stress [MPa]")
    ax_stress.set_xlim(left=0)
    ax_stress.set_ylim(bottom=0)
    axes_for_legend = [ax_stress]
    if graph_type != "Stress":
        ax_ae = ax_stress.twinx()
        if "AE Amplitude" in graph_type:
            amplitude_column = f"Ch.{channel_number} Amplitude [mV]"
            if amplitude_column not in ae_data.columns:
                missing.append(f"{amplitude_column} がありません")
            else:
                ax_ae.scatter(
                    ae_x,
                    ae_data[amplitude_column],
                    color="red",
                    marker="x",
                    s=22,
                    alpha=0.7,
                    label="AE Amplitude",
                )
                ax_ae.set_ylabel("AE Amplitude [mV]")
        elif "Peak Frequency" in graph_type:
            frequency_column = f"Ch.{channel_number} AE Peak Frequency [kHz]"
            if frequency_column not in ae_data.columns:
                missing.append(f"{frequency_column} がありません")
            else:
                ax_ae.scatter(
                    ae_x,
                    ae_data[frequency_column],
                    color="red",
                    marker="x",
                    s=22,
                    alpha=0.7,
                    label="Peak Frequency",
                )
                ax_ae.set_ylabel("Peak Frequency [kHz]")
        ax_ae.set_ylim(bottom=0)
        axes_for_legend.append(ax_ae)
        if "AE Energy" in graph_type:
            energy_column = f"Ch.{channel_number} Cumulative Energy"
            if energy_column not in ae_data.columns:
                missing.append(f"{energy_column} がありません")
            else:
                ax_energy = ax_stress.twinx()
                ax_energy.spines["right"].set_position(("outward", 60))
                ax_energy.plot(
                    ae_x, ae_data[energy_column], color="green", linewidth=1.5, label="Cumulative AE Energy"
                )
                ax_energy.set_ylabel("Cumulative AE Energy [V²/s]")
                ax_energy.set_ylim(bottom=0)
                axes_for_legend.append(ax_energy)
    if limits.get("x") is not None:
        ax_stress.set_xlim(0, limits["x"])
    if limits.get("stress") is not None:
        ax_stress.set_ylim(0, limits["stress"])
    if ax_ae is not None and "AE Amplitude" in graph_type and limits.get("amplitude") is not None:
        ax_ae.set_ylim(0, limits["amplitude"])
    if ax_ae is not None and "Peak Frequency" in graph_type and limits.get("frequency") is not None:
        ax_ae.set_ylim(0, limits["frequency"])
    if ax_energy is not None and limits.get("energy") is not None:
        ax_energy.set_ylim(0, limits["energy"])
    handles = []
    labels = []
    for axis in axes_for_legend:
        axis_handles, axis_labels = axis.get_legend_handles_labels()
        handles.extend(axis_handles)
        labels.extend(axis_labels)
    ax_stress.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.05),
        ncol=max(len(labels), 1),
        frameon=False,
        borderaxespad=0,
    )
    fig.tight_layout()
    fig.subplots_adjust(top=0.82)
    return (fig, missing)


def create_zero_point_figure(ss_data, ss_result):
    """ゼロ点補正の前後を並べた図を作る（画面表示とExcel出力で共通）。"""
    area = ss_result["area[mm2]"]
    load_zero = ss_result["load_zero[N]"]
    final_zero = ss_result["strain_zero[%]"]
    fit_end = ss_result["fit_end[%]"]
    fit_slope = ss_result["fit_slope"]
    fit_indices = np.array(ss_result["fit_indices"], dtype=int)
    stress_raw = ss_data["Load[N]"] / area
    load_zero_stress = load_zero / area
    fit_x_raw = ss_data.loc[fit_indices, "Strain_raw[%]"].to_numpy()
    fit_x_corrected = ss_data.loc[fit_indices, "Strain_corrected[%]"].to_numpy()
    fit_line_raw = fit_slope * (fit_x_raw - final_zero) + load_zero_stress
    fit_line_corrected = fit_slope * fit_x_corrected
    zoom_x_min = -0.2
    zoom_x_max = fit_end + 0.3
    raw_zoom_mask = (ss_data["Strain_raw[%]"] >= zoom_x_min) & (ss_data["Strain_raw[%]"] <= zoom_x_max)
    corrected_zoom_mask = (ss_data["Strain_corrected[%]"] >= zoom_x_min) & (
        ss_data["Strain_corrected[%]"] <= zoom_x_max
    )
    y_candidates = np.concatenate(
        [stress_raw[raw_zoom_mask].to_numpy(), ss_data.loc[corrected_zoom_mask, "Stress[MPa]"].to_numpy()]
    )
    y_candidates = y_candidates[np.isfinite(y_candidates)]
    if len(y_candidates) > 0:
        y_min = np.min(y_candidates)
        y_max = np.max(y_candidates)
        y_margin = max(2.0, (y_max - y_min) * 0.1)
        zoom_y_min = y_min - y_margin
        zoom_y_max = y_max + y_margin
    else:
        zoom_y_min = -5
        zoom_y_max = 50
    fig_zero, (ax_before, ax_after) = plt.subplots(1, 2, figsize=(12, 5))
    ax_before.plot(ss_data["Strain_raw[%]"], stress_raw, linewidth=1.5, label="Before correction")
    ax_before.scatter(fit_x_raw, stress_raw.iloc[fit_indices], s=28, label="Fit points")
    ax_before.plot(fit_x_raw, fit_line_raw, linestyle="--", linewidth=1.5, label="Linear fit")
    ax_before.axhline(0, linewidth=0.8)
    ax_before.axvline(0, linewidth=0.8)
    ax_before.set_xlim(zoom_x_min, zoom_x_max)
    ax_before.set_ylim(zoom_y_min, zoom_y_max)
    ax_before.set_title("Before correction")
    ax_before.set_xlabel("Raw Strain [%]")
    ax_before.set_ylabel("Raw Stress [MPa]")
    ax_before.grid(alpha=0.2)
    ax_before.legend()
    ax_after.plot(
        ss_data["Strain_corrected[%]"], ss_data["Stress[MPa]"], linewidth=1.5, label="After correction"
    )
    ax_after.scatter(fit_x_corrected, ss_data.loc[fit_indices, "Stress[MPa]"], s=28, label="Fit points")
    ax_after.plot(fit_x_corrected, fit_line_corrected, linestyle="--", linewidth=1.5, label="Linear fit")
    ax_after.axhline(0, linewidth=0.8)
    ax_after.axvline(0, linewidth=0.8)
    ax_after.set_xlim(zoom_x_min, zoom_x_max)
    ax_after.set_ylim(zoom_y_min, zoom_y_max)
    ax_after.set_title("After correction")
    ax_after.set_xlabel("Corrected Strain [%]")
    ax_after.set_ylabel("Stress [MPa]")
    ax_after.grid(alpha=0.2)
    ax_after.legend()
    fig_zero.tight_layout()
    return fig_zero
