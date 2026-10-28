"""動作確認・テスト用の「作りもの」の引張試験（SS）・AE データを作る。

実際の研究データではない。CFRTP の角度材をクロスヘッド変位で測ったときの特徴をまねて作る。
  - 試験機を動かす前の数秒間（荷重計のずれとノイズつき）
  - 立ち上がりのトウ（つかみ具へのなじみ）
  - 直線部分と、早い段階から曲がり始める非線形
  - AE は、ひずみが進むにつれて増えていく。振幅とエネルギーは小さいものが多く、大きいものはまれ
  - 破断時の急な応力低下
  - ファイルの形は計測装置の出力に合わせる（タブ区切り、時刻は整数 [ms]、小数は 6 桁、
    決まった間隔の行に AE イベントの時刻の行が混ざる）

記録間隔は「間隔 × クロスヘッド速度 ＝ 一定」（1 mm/min は 1 秒、10 mm/min は 0.1 秒）。

使い方: python -m tests.make_sample_data 出力先のフォルダ（テストでは自動で作るので、ふだんは使わない）
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

WIDTH, THICKNESS, GAUGE = 15.0, 2.0, 60.0  # 寸法の初期値 [mm]
AREA = WIDTH * THICKNESS
LOAD_OFFSET_N = -30.0  # 荷重計のずれ [N]
STRAIN_OFFSET = -40.0  # 記録開始時の Strain[-] の値
IDLE_SECONDS = 8  # 試験機を動かす前の時間 [s]
AE_THRESHOLD_MV = 31.7  # AE 振幅のしきい値 [mV]（これより小さい信号は記録されない想定）

# 名前: 材料の形と試験の条件
CASES = {
    "sample_45deg": {
        "modulus": 3200.0,  # 直線部分の傾き [MPa]（クロスヘッド変位から求めた見かけの値）
        "max_stress": 150.0,  # 最大応力 [MPa]
        "fracture_strain": 0.40,  # 破断ひずみ [-]
        "power": 4.0,  # 曲がり方（大きいほど、はじめは直線に近く、後半で寝る）
        "toe": 0.003,  # トウの大きさ [-]
        "toe_stress": 3.0,  # トウが消える応力の目安 [MPa]
        "speed": 1.0,  # クロスヘッド速度 [mm/min]
        "n_events": 1500,
    },
    "sample_50deg": {
        "modulus": 3100.0,
        "max_stress": 110.0,
        "fracture_strain": 0.50,
        "power": 4.0,
        "toe": 0.004,
        "toe_stress": 2.5,
        "speed": 10.0,
        "n_events": 1200,
    },
    # 直線的な材料（0° 材のつもり）。弾性率の計算が正しいかをテストで確かめるためだけに使い、
    # ファイルには書き出さない
    "sample_0deg": {
        "modulus": 40000.0,
        "max_stress": 600.0,
        "fracture_strain": 0.015,
        "power": 1.0,
        "toe": 0.003,
        "toe_stress": 20.0,
        "speed": 1.0,
        "interval": 0.05,  # 計算の確認用なので、記録を細かくする
        "n_events": 300,
    },
}
SAMPLE_FILES = ["sample_45deg", "sample_50deg"]  # ファイルに書き出すもの


def strain_of(stress, case):
    """応力 [MPa] → ひずみ [-]。直線 ＋ 非線形 ＋ トウ。最大応力でちょうど破断ひずみになるようにする。"""
    linear = stress / case["modulus"]
    toe = case["toe"] * (1 - np.exp(-stress / case["toe_stress"]))
    end_linear = case["max_stress"] / case["modulus"]
    end_toe = case["toe"] * (1 - np.exp(-case["max_stress"] / case["toe_stress"]))
    room = max(case["fracture_strain"] - end_linear - end_toe, 0.0)
    nonlinear = room * (stress / case["max_stress"]) ** case["power"] if case["power"] > 1 else 0.0
    return linear + toe + nonlinear


def stress_at(strain, case):
    """ひずみ [-] → 応力 [MPa]（strain_of の逆。表を作って補間する）。"""
    stress_grid = np.linspace(0, case["max_stress"], 40000)
    return np.interp(strain, strain_of(stress_grid, case), stress_grid)


def make_case(name):
    """SS・AE の DataFrame を作る（名前ごとに乱数の種を固定するので、毎回同じデータになる）。"""
    case = CASES[name]
    rng = np.random.default_rng(list(CASES).index(name))

    interval_s = case.get("interval", 1.0 / case["speed"])  # ふつうは 間隔 × 速度 ＝ 一定
    speed_mm_s = case["speed"] / 60.0
    slack_mm = 0.1  # 動き始めのたるみ（荷重がかからない）
    end_strain = strain_of(case["max_stress"], case)
    test_seconds = (slack_mm + end_strain * GAUGE) / speed_mm_s

    def state(t_s):
        """時刻 [s]（記録開始から）→ 変位 [mm]・応力 [MPa]。"""
        moved = np.clip((t_s - IDLE_SECONDS) * speed_mm_s, 0, None)
        strain = np.clip(moved - slack_mm, 0, None) / GAUGE
        return moved, stress_at(np.minimum(strain, end_strain), case)

    # 決まった間隔の行
    regular = np.arange(0, IDLE_SECONDS + test_seconds, interval_s)

    # AE イベント：応力が最大応力の 15% を超えたあたりから増え始め、後半ほど多い
    progress = np.clip((regular - IDLE_SECONDS) / test_seconds, 0, 1)
    _, stress_regular = state(regular)
    weight = np.clip(stress_regular / case["max_stress"] - 0.15, 0, None) ** 1.5 * (0.3 + progress)
    weight[-1] *= 3  # 破断の直前は特に多い
    picked = rng.choice(len(regular), size=case["n_events"], p=weight / weight.sum())
    ae_times = np.sort(regular[picked] + rng.uniform(0, interval_s, case["n_events"]))
    ae_ms = np.unique(np.round(ae_times * 1000).astype(int) + 5)

    # SS ファイル：決まった間隔の行に、AE の時刻の行が混ざる。最後に破断の行を足す
    regular_ms = np.round(regular * 1000).astype(int)
    time_ms = np.unique(np.concatenate([regular_ms, ae_ms]))
    moved, stress = state(time_ms / 1000)
    load = stress * AREA
    after_ms = time_ms[-1] + np.round(np.array([1, 2, 3]) * interval_s * 1000).astype(int)
    time_ms = np.concatenate([time_ms, after_ms])
    moved = np.concatenate([moved, moved[-1] + speed_mm_s * interval_s * np.array([1, 2, 3])])
    load = np.concatenate([load, np.array([0.04, 0.01, 0.0]) * case["max_stress"] * AREA])

    load_recorded = load + LOAD_OFFSET_N + rng.normal(0, 4.0, len(load))
    strain_recorded = moved * 500 + STRAIN_OFFSET + rng.normal(0, 0.5, len(moved))
    ss = pd.DataFrame({"Time[ms]": time_ms, "Strain[-]": strain_recorded, "Load[N]": load_recorded})

    # AE ファイル：イベントの時刻の行の Strain・Load は、SS ファイルの同じ時刻の行と同じ値
    rows = ss.set_index("Time[ms]").loc[ae_ms].reset_index()
    n = len(rows)
    late = np.interp(ae_ms / 1000, regular, progress)  # 試験の進み具合（0〜1）

    def amplitude():
        # しきい値に近い小さな信号が多く、大きな信号はまれ。上限（約 9000 mV）を超えたものは引き直す
        level = rng.exponential(0.7 + 0.5 * late, n)
        too_large = level > np.log(9000.0 / AE_THRESHOLD_MV)
        level[too_large] = rng.uniform(4.0, np.log(9000.0 / AE_THRESHOLD_MV), too_large.sum())
        return AE_THRESHOLD_MV * np.exp(level)

    amp1, amp2 = amplitude(), amplitude()

    def energy(amp):
        return 0.02 * (amp / AE_THRESHOLD_MV) ** 1.6 * np.exp(rng.normal(0, 0.4, n))

    def frequency():
        # 低い帯（樹脂の割れ）と高い帯（繊維の破断）。後半ほど高い帯が増える
        high = rng.random(n) < 0.15 + 0.35 * late
        return np.where(high, rng.normal(330, 50, n), rng.normal(140, 35, n)).clip(30, 600)

    def counts(amp):
        return np.floor(np.log(amp / AE_THRESHOLD_MV) * 4 + rng.uniform(0, 2, n)).clip(0, None)

    ae = pd.DataFrame(
        {
            "Time[ms]": rows["Time[ms]"],
            "Strain[-]": rows["Strain[-]"],
            "Load[N]": rows["Load[N]"],
            "Ch.1 Amplitude [mV]": amp1,
            "Ch.2 Amplitude [mV]": amp2,
            "Ch.1 Energy [V^2/s]": energy(amp1),
            "Ch.2 Energy [V^2/s]": energy(amp2),
            "Ch.1 Rise Time [s]": rng.uniform(0, 0.0003, n),
            "Ch.2 Rise Time [s]": rng.uniform(0, 0.0003, n),
            "Ch.1 Duration Time [s]": rng.uniform(0.00001, 0.0004, n),
            "Ch.2 Duration Time [s]": rng.uniform(0.00001, 0.0004, n),
            "Ch.1 AE Count[-]": counts(amp1),
            "Ch.2 AE Count [-]": counts(amp2),
            "Ch.1 AE Peak Frequency [kHz]": frequency(),
            "Ch.2 AE Peak Frequency [kHz]": frequency(),
            "Arrival Time Difference [ms]": rng.choice([-0.0001, 0.0001], n),
        }
    )
    return ss, ae


def write_like_device(data, path):
    """計測装置の出力と同じ形（列の区切りは「空白・タブ・空白」、時刻は整数、小数は 6 桁、改行は CRLF）で書く。"""
    lines = [" \t ".join(data.columns) + " "]
    for row in data.itertuples(index=False):
        cells = [str(int(row[0]))] + [f"{value:.6f}" for value in row[1:]]
        lines.append(" \t ".join(cells) + " ")
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_data")
    out.mkdir(parents=True, exist_ok=True)
    for name in SAMPLE_FILES:
        ss, ae = make_case(name)
        write_like_device(ss, out / f"{name}_SS.txt")
        write_like_device(ae, out / f"{name}_AE.txt")
        print(f"{name}: SS {len(ss)}行, AE {len(ae)}行")
