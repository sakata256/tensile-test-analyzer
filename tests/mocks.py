"""テスト用のモック：gspread のワークシートと、Google ドライブの REST API の代わりをする部品。

本物の Google には一切つながない。
"""

import itertools
import json as jsonlib
import re


class FakeWorksheet:
    def __init__(self, rows=None, col_count=26):
        self.cells = [list(r) for r in (rows or [])]
        self.col_count = col_count
        self.calls = []

    # --- 読み込み ---
    def _padded(self):
        width = max([len(r) for r in self.cells] + [0])
        return [r + [""] * (width - len(r)) for r in self.cells]

    def row_values(self, row):
        self.calls.append("read")
        if row > len(self.cells):
            return []
        values = [str(v) for v in self.cells[row - 1]]
        while values and values[-1] == "":
            values.pop()
        return values

    def col_values(self, col, value_render_option="FORMATTED_VALUE"):
        self.calls.append("read")
        values = [(r[col - 1] if col - 1 < len(r) else "") for r in self.cells]
        values = [str(v) for v in values]
        while values and values[-1] == "":
            values.pop()
        return values

    def get_all_values(self, value_render_option=None, **kwargs):
        self.calls.append("read")
        rows = self._padded()
        if value_render_option == "UNFORMATTED_VALUE":
            return [list(r) for r in rows]
        return [[str(v) for v in r] for r in rows]

    # --- 書き込み ---
    def add_cols(self, n):
        self.col_count += n

    def update(self, values, range_name=None, value_input_option=None, **kwargs):
        self.calls.append("write")
        assert value_input_option in (None, "RAW"), value_input_option
        m = re.fullmatch(r"([A-Z]+)(\d+)", range_name)
        assert m and m.group(1) == "A", range_name
        row = int(m.group(2))
        for offset, line in enumerate(values):
            if len(line) > self.col_count:
                raise RuntimeError("APIError: exceeds grid limits")
            index = row - 1 + offset
            while len(self.cells) <= index:
                self.cells.append([])
            target = self.cells[index]
            if len(target) < len(line):
                target.extend([""] * (len(line) - len(target)))
            target[: len(line)] = list(line)

    def append_row(self, values, value_input_option="RAW", table_range=None, **kwargs):
        self.calls.append("write")
        assert value_input_option == "RAW"
        for v in values:
            assert isinstance(v, (str, int, float)), (type(v), v)
        last = 0
        for i, r in enumerate(self.cells, start=1):
            if any(str(c) != "" for c in r):
                last = i
        self.cells = self.cells[:last] + [list(values)]


DRIVE_API = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"


class FakeResponse:
    def __init__(self, status_code, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.text = jsonlib.dumps(self._payload, ensure_ascii=False)

    def json(self):
        return self._payload


class FakeDriveSession:
    def __init__(self, fail_upload=False):
        self.files = {}
        self._ids = itertools.count(1)
        self.calls = []
        self.fail_upload = fail_upload

    def get(self, url, params=None):
        self.calls.append(("get", url))
        params = params or {}
        if url == DRIVE_API:
            q = params["q"]
            name = (
                re.search(r"name = '((?:[^'\\]|\\.)*)'", q).group(1).replace("\\'", "'").replace("\\\\", "\\")
            )
            parent = re.search(r"'([^']+)' in parents", q)
            assert "trashed = false" in q
            hits = [
                {"id": i, "name": f["name"]}
                for i, f in self.files.items()
                if f["name"] == name
                and f["mimeType"] == "application/vnd.google-apps.folder"
                and (parent is None or parent.group(1) in f["parents"])
            ]
            return FakeResponse(200, {"files": hits})
        file_id = url.rsplit("/", 1)[1]
        assert params.get("alt") == "media"
        if file_id not in self.files:
            return FakeResponse(404, {"error": {"message": "File not found"}})
        return FakeResponse(200, content=self.files[file_id]["content"])

    def post(self, url, params=None, json=None, data=None, headers=None):
        self.calls.append(("post", url))
        file_id = f"id{next(self._ids)}"
        if url == DRIVE_API:
            self.files[file_id] = {
                "name": json["name"],
                "mimeType": json["mimeType"],
                "parents": json.get("parents", ["root"]),
                "content": b"",
            }
            return FakeResponse(200, {"id": file_id})
        assert url == DRIVE_UPLOAD_API and params["uploadType"] == "multipart"
        if self.fail_upload:
            return FakeResponse(403, {"error": {"message": "insufficientPermissions"}})
        boundary = re.search(r"boundary=(\S+)", headers["Content-Type"]).group(1).encode()
        parts = data.split(b"--" + boundary)
        assert parts[-1].strip() == b"--", parts[-1][:20]
        meta_part, file_part = parts[1], parts[2]
        meta = jsonlib.loads(meta_part.split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n").decode("utf-8"))
        content = file_part.split(b"\r\n\r\n", 1)[1]
        assert content.endswith(b"\r\n")
        content = content[:-2]
        self.files[file_id] = {
            "name": meta["name"],
            "mimeType": "text/plain",
            "parents": meta["parents"],
            "content": content,
        }
        return FakeResponse(200, {"id": file_id})
