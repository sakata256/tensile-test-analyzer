"""台帳（specimen_list）と Google ドライブ保存（drive_storage）のテスト。台帳とドライブはモックを使う。"""

from datetime import date

import numpy as np
import pytest

from tensile import drive_storage as ds
from tensile import specimen_list as sl
from tests.mocks import FakeDriveSession, FakeWorksheet

FORM = {
    "試験日": date(2026, 10, 14), "材料の種類": " CF/PA6 ", "板の名前": "板A", "端から": "1", "試験片名": "",
    "角度": "±45", "引張速度 [mm/min]": None, "幅 [mm]": 15.0, "厚み [mm]": None, "ゲージ長さ [mm]": None,
    "幅の詳細": ["15.02", "", "14.98"] + [""] * 6, "厚みの詳細": ["2.01", "2.03"] + [""] * 7,
    "ゲージ長さの詳細": [""] * 3, "メモ": "=1+1 は数式にしない", "担当者": "担当A",
}  # fmt: skip


@pytest.fixture
def store():
    return sl.SpecimenStore(FakeWorksheet())


def test_register_creates_header_and_auto_name(store):
    record = store.add(sl.build_record(FORM))
    assert store.worksheet.cells[0] == sl.COLUMNS
    assert (record["ID"], record["試験片名"], record["状態"]) == (1, "No.0001", "未試験")
    assert record["幅 [mm]"] == pytest.approx(15.0)  # 詳細寸法の入力分だけの平均
    assert record["厚み [mm]"] == pytest.approx(2.02)
    assert record["材料の種類"] == "CF/PA6"


def test_load_types_and_text(store):
    store.add(sl.build_record(FORM))
    store.add(sl.build_record(dict(FORM, 試験片名="A-2", **{"引張速度 [mm/min]": 10.0})))
    table = store.load()
    assert list(table["試験片名"]) == ["No.0001", "A-2"]
    assert np.isnan(table.loc[0, "引張速度 [mm/min]"]) and table.loc[1, "引張速度 [mm/min]"] == 10.0
    assert table.loc[0, "メモ"].startswith("=1+1")  # 数式として扱わない
    assert table.loc[0, "試験日"] == "2026-10-14"


def test_update_finds_row_by_id_even_after_sorting(store):
    store.add(sl.build_record(FORM))
    store.add(sl.build_record(dict(FORM, 試験片名="A-2")))
    store.add(sl.build_record(FORM))
    cells = store.worksheet.cells
    cells[1], cells[3] = cells[3], cells[1]  # スプレッドシートで並べ替えられた
    existing = sl.record_from_row(store.load().set_index("ID", drop=False).loc[2])
    store.update(sl.build_record(dict(FORM, 試験片名="", 状態="失敗"), existing=existing))
    table = store.load().set_index("ID")
    assert (table.loc[2, "試験片名"], table.loc[2, "状態"]) == ("No.0002", "失敗")
    assert set(table["試験片名"]) == {"No.0001", "No.0002", "No.0003"}


def test_old_ledger_gets_missing_columns_on_the_right():
    old = FakeWorksheet(
        [["ID", "メモ", "試験片名", "SSファイルID", "AEファイルID"], [5, "古いメモ", "X", "s1", "a1"]]
    )
    store = sl.SpecimenStore(old)
    table = store.load()
    assert old.cells[0][:5] == ["ID", "メモ", "試験片名", "SSファイルID", "AEファイルID"]
    assert len(old.cells[0]) == len(sl.COLUMNS)
    assert (table.loc[0, "試験片名"], table.loc[0, "メモ"]) == ("X", "古いメモ")
    # 「ドライブ保存」の列を作る前に保存できていた行は「保存済み」
    assert table.loc[0, sl.DRIVE_STATUS_COLUMN] == "保存済み"
    assert store.add(sl.build_record(FORM))["ID"] == 6


@pytest.mark.parametrize(
    "bad, message",
    [({"幅の詳細": ["abc"] + [""] * 8}, "数値でない"), ({"厚みの詳細": ["-1"] + [""] * 8}, "0より大きい"),
     ({"幅 [mm]": 0.0}, "0より大きい")],
)  # fmt: skip
def test_invalid_input(bad, message):
    with pytest.raises(ValueError, match=message):
        sl.build_record(dict(FORM, **bad))


def test_record_with_analysis_and_drive_status(sample):
    from tensile import analysis

    _, ss_result, _, ae_result = analysis.reanalyze_project_data(*sample["sample_50deg"], 15.0, 2.0, 60.0)
    base = sl.build_record(FORM)
    details = ([15.0] + [None] * 8, [None] * 9, [None] * 3)
    failed = sl.record_with_analysis(base, (15.0, 2.0, 60.0), details, ss_result, ae_result, None, "保存失敗")
    assert failed[sl.DRIVE_STATUS_COLUMN] == "保存失敗" and failed["状態"] == "解析済み"
    assert failed["破断ひずみ [-]"] == pytest.approx(ss_result["fracture_strain[%]"] / 100)
    assert failed["引張速度 [mm/min]"] == sl.speed_setting(ss_result["crosshead_speed[mm/min]"])
    unchanged = sl.record_with_analysis(
        dict(base, ドライブ保存="保存済み"), (15.0, 2.0, 60.0), details, ss_result, ae_result
    )
    assert unchanged[sl.DRIVE_STATUS_COLUMN] == "保存済み"


def test_read_settings():
    assert sl.read_settings({})[0] is None
    info, sid, problem = sl.read_settings(
        {"gcp_service_account_json": '{"private_key": "a\\nb"}', "specimen_list": {"spreadsheet_id": "XYZ"}}
    )
    assert info["private_key"] == "a\nb" and sid == "XYZ" and problem == ""
    assert (
        "正しく"
        in sl.read_settings({"gcp_service_account_json": "{x}", "specimen_list": {"spreadsheet_id": "X"}})[2]
    )


def test_drive_folder_upload_download():
    session = FakeDriveSession()
    drive = ds.DriveStorage(session)
    folder = drive.specimen_folder("No.0001_A'1/2")
    assert drive.specimen_folder("No.0001_A'1/2") == folder  # 同じ名前のフォルダは作り直さない
    assert session.files[folder]["name"] == "No.0001_A'1_2"
    file_id = drive.upload(folder, "日本語名.txt", "Time[ms]\tLoad\n1\t2\n".encode())
    assert drive.download(file_id).decode() == "Time[ms]\tLoad\n1\t2\n"
    with pytest.raises(ds.DriveError):
        drive.download("missing")


def test_drive_settings_and_errors():
    assert ds.read_drive_settings({})[0] is None
    settings, _ = ds.read_drive_settings(
        {"google_drive": {"client_id": "a", "client_secret": "b", "refresh_token": "c"}}
    )
    assert settings["root_folder"] == ds.DEFAULT_ROOT_FOLDER
    assert "発行し直して" in ds.explain_drive_error(Exception("invalid_grant: expired"))
