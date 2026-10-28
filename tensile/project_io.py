"""解析データの ZIP 保存・読み込み（アプリで開き直すためのファイル）。"""

import hashlib
import io
import json
import zipfile

import numpy as np
import pandas as pd


def convert_json_value(value):
    if isinstance(value, np.generic):
        return value.item()
    return value


def create_project_zip(specimen_name, ss_data, ae_data, ss_result, ae_result, dimension_details):
    """解析データを ZIP にまとめる（dimension_details：画面の詳細寸法の入力値）。"""
    metadata = {
        "version": 2,
        "specimen_name": specimen_name,
        "ss_result": {key: convert_json_value(value) for key, value in ss_result.items()},
        "ae_result": {key: convert_json_value(value) for key, value in ae_result.items()},
        "dimension_details": dimension_details,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        zip_file.writestr("ss_processed.csv", ss_data.to_csv(index=False))
        zip_file.writestr("ae_processed.csv", ae_data.to_csv(index=False))
    buffer.seek(0)
    return buffer.getvalue()


def load_project_zip(uploaded_file):
    uploaded_file.seek(0)
    with zipfile.ZipFile(uploaded_file, "r") as zip_file:
        required_files = ["metadata.json", "ss_processed.csv", "ae_processed.csv"]
        for file_name in required_files:
            if file_name not in zip_file.namelist():
                raise ValueError(f"{file_name} がありません")
        metadata = json.loads(zip_file.read("metadata.json").decode("utf-8"))
        ss_data = pd.read_csv(io.BytesIO(zip_file.read("ss_processed.csv")))
        ae_data = pd.read_csv(io.BytesIO(zip_file.read("ae_processed.csv")))
    ss_result = metadata["ss_result"]
    ae_result = metadata["ae_result"]
    specimen_name = metadata.get("specimen_name", "")
    dimension_details = metadata.get(
        "dimension_details",
        {"width_values": [""] * 9, "thickness_values": [""] * 9, "gauge_values": [""] * 3},
    )
    return (specimen_name, ss_data, ae_data, ss_result, ae_result, dimension_details)


def result_signature(specimen_name, ss_result):
    """解析結果が変わったかを見分けるための目印（Excel を作り直すかの判断に使う）。"""
    text = json.dumps(
        {"name": specimen_name, "result": {k: convert_json_value(v) for k, v in ss_result.items()}},
        sort_keys=True,
        default=str,
    )
    return hashlib.md5(text.encode("utf-8")).hexdigest()
