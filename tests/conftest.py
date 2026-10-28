"""テストの共通設定。リポジトリの直下を import できるようにし、作りもののデータを用意する。"""

import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from tests.make_sample_data import CASES, SAMPLE_FILES, make_case, write_like_device  # noqa: E402


@pytest.fixture(scope="session")
def sample():
    """作りもののデータ（名前 → (SS, AE) の DataFrame）。"""
    return {name: make_case(name) for name in CASES}


@pytest.fixture(scope="session")
def sample_files(sample, tmp_path_factory):
    """作りもののデータを、計測装置の出力と同じ形のファイルに書き出したもの（名前 → (SS, AE) の場所）。"""
    folder = tmp_path_factory.mktemp("sample_data")
    paths = {}
    for name in SAMPLE_FILES:
        ss, ae = sample[name]
        paths[name] = (folder / f"{name}_SS.txt", folder / f"{name}_AE.txt")
        write_like_device(ss, paths[name][0])
        write_like_device(ae, paths[name][1])
    return paths
