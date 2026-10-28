"""画面の動作テスト（Streamlit の AppTest）。台帳とドライブはモックに差し替える。"""

import io

import pytest
import streamlit
from streamlit.delta_generator import DeltaGenerator
from streamlit.testing.v1 import AppTest

from tensile import drive_storage as ds
from tensile import specimen_list as sl
from tests.conftest import ROOT
from tests.mocks import FakeDriveSession, FakeWorksheet

APP = str(ROOT / "app.py")


class FakeUpload(io.BytesIO):
    """ファイル選択欄で選んだファイルの代わり（AppTest ではファイルを選べないため）。"""

    def __init__(self, path):
        super().__init__(path.read_bytes())
        self.name = path.name


@pytest.fixture
def uploads(monkeypatch):
    """key → FakeUpload を登録すると、そのファイル選択欄が「選択済み」になる。"""
    files = {}
    original_method = DeltaGenerator.file_uploader

    def fake_method(self, label, *args, key=None, **kwargs):
        if key in files:
            streamlit.session_state[key] = files[key]
            return files[key]
        return original_method(self, label, *args, key=key, **kwargs)

    def fake_function(label, *args, key=None, **kwargs):
        return fake_method(streamlit._main, label, *args, key=key, **kwargs)

    monkeypatch.setattr(DeltaGenerator, "file_uploader", fake_method)
    monkeypatch.setattr(streamlit, "file_uploader", fake_function)
    return files


def messages(at):
    return [m.value for m in list(at.success) + list(at.error) + list(at.warning) + list(at.info)]


def test_analysis_only_without_ledger_settings():
    """台帳の設定がないとき（公開版など）は、「試験片の一覧」を出さない。"""
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    assert at.radio[0].options == ["新しく解析する", "保存済み解析を開く"]


def test_new_analysis_and_excel(uploads, sample_files):
    ss_path, ae_path = sample_files["sample_45deg"]
    uploads.update({"new_ss_file": FakeUpload(ss_path), "new_ae_file": FakeUpload(ae_path)})
    at = AppTest.from_file(APP, default_timeout=180).run()
    [b for b in at.button if b.label == "解析開始"][0].click().run()
    assert not at.exception, at.exception
    assert any(m.label == "最大応力" for m in at.metric)
    [b for b in at.button if b.label == "Excelファイルを作成"][0].click().run()
    assert not at.exception, at.exception
    assert at.session_state["excel_export"]["bytes"][:2] == b"PK"  # xlsx（ZIP 形式）


def test_specimen_register_open_analyze(uploads, sample_files):
    """登録 → 一覧から開く → 解析 → 結果が台帳に書かれ、元ファイルがドライブに保存される。"""
    worksheet, session = FakeWorksheet(), FakeDriveSession()
    store = sl.SpecimenStore(worksheet)
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["specimen_store"] = store
    at.session_state["drive_storage"] = ds.DriveStorage(session)
    at.run()
    assert at.radio[0].value == "試験片の一覧"

    at.text_input(key="reg_material").input("CF/PA6")
    at.text_input(key="reg_t_0").input("2.0")
    [b for b in at.button if b.label == "登録する"][0].click().run()
    assert any("No.0001" in m and "登録しました" in m for m in messages(at))

    at.selectbox(key="specimen_picker").set_value(1).run()
    ss_path, ae_path = sample_files["sample_50deg"]
    uploads.update({"specimen_ss_file": FakeUpload(ss_path), "specimen_ae_file": FakeUpload(ae_path)})
    at.run()
    at.button(key="specimen_analyze").click().run()
    assert not at.exception, at.exception
    assert any("ドライブに保存" in m for m in messages(at))

    row = sl.record_from_row(store.load().iloc[0])
    assert row["状態"] == "解析済み"
    assert row[sl.DRIVE_STATUS_COLUMN] == "保存済み"
    assert row["引張強さ [MPa]"] == pytest.approx(110.0, rel=0.005)
    assert session.files[row["SSファイルID"]]["content"] == ss_path.read_bytes()
