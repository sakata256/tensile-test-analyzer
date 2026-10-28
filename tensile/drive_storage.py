# ======================================
# Google ドライブへの元ファイルの保存
# ======================================
# SS・AE の元ファイルを、ユーザーの Google ドライブの「引張試験_データ」フォルダに保存する。
#
# サービスアカウント（スプレッドシートに使っているロボット）はドライブの容量を持たないので、
# ファイルは置けない。そこで、ユーザー本人が1回だけ発行した「許可証（リフレッシュトークン）」を使う。
# 許可の範囲は drive.file ＝「このアプリが自分で作ったファイルだけ」。ほかのファイルは見えない。
#
# 構成（ドライブの中）：
#   引張試験_データ/
#       No.0003_A-3/
#           SS_00002.txt
#           AE_00002.txt

import json
import uuid

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3/files"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_ROOT_FOLDER = "引張試験_データ"


def folder_link(folder_id):
    return f"https://drive.google.com/drive/folders/{folder_id}"


def file_link(file_id):
    return f"https://drive.google.com/file/d/{file_id}/view"


def safe_folder_name(text):
    """フォルダ名に使えない・紛らわしい文字を置き換える。"""
    for ch in '/\\:*?"<>|':
        text = text.replace(ch, "_")
    return text.strip() or "no_name"


class DriveStorage:
    """ドライブの読み書き。session は requests と同じ使い方（get / post）ができるもの。

    本物では google-auth の AuthorizedSession（許可証つきで通信する部品）を渡す。
    テストでは、同じ使い方ができるテスト用のモック（tests/mocks.py）を渡す。
    """

    def __init__(self, session, root_folder_name=DEFAULT_ROOT_FOLDER):
        self.session = session
        self.root_folder_name = root_folder_name
        self._root_id = None

    def _check(self, response):
        if response.status_code >= 400:
            raise DriveError(response.status_code, response.text[:300])
        return response

    def find_folder(self, name, parent_id=None):
        """このアプリが作ったフォルダの中から、名前で探す。なければ None。"""
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        query = f"name = '{escaped}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        response = self._check(
            self.session.get(API, params={"q": query, "fields": "files(id,name)", "spaces": "drive"})
        )
        files = response.json().get("files", [])
        return files[0]["id"] if files else None

    def create_folder(self, name, parent_id=None):
        metadata = {"name": name, "mimeType": FOLDER_MIME}
        if parent_id:
            metadata["parents"] = [parent_id]
        response = self._check(self.session.post(API, params={"fields": "id"}, json=metadata))
        return response.json()["id"]

    def root_folder_id(self):
        """「引張試験_データ」フォルダ（なければ作る）。"""
        if self._root_id is None:
            self._root_id = self.find_folder(self.root_folder_name) or self.create_folder(
                self.root_folder_name
            )
        return self._root_id

    def specimen_folder(self, folder_name):
        """試験片のフォルダを作り、その ID を返す（同じ名前があればそれを使う）。"""
        root = self.root_folder_id()
        name = safe_folder_name(folder_name)
        return self.find_folder(name, root) or self.create_folder(name, root)

    def upload(self, folder_id, file_name, content, mime_type="text/plain"):
        """ファイルを1つ保存して、その ID を返す。"""
        boundary = uuid.uuid4().hex
        metadata = json.dumps({"name": file_name, "parents": [folder_id]}, ensure_ascii=False)
        body = (
            (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n"
                f"--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8")
            + content
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        response = self._check(
            self.session.post(
                UPLOAD_API,
                params={"uploadType": "multipart", "fields": "id"},
                data=body,
                headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            )
        )
        return response.json()["id"]

    def download(self, file_id):
        """保存したファイルの中身（バイト）を読み込む。"""
        return self._check(self.session.get(f"{API}/{file_id}", params={"alt": "media"})).content


class DriveError(Exception):
    def __init__(self, status, text):
        super().__init__(f"{status}: {text}")
        self.status = status


def read_drive_settings(secrets):
    """Secrets から、ドライブの許可証を読み取る。なければ (None, 理由)。"""
    try:
        section = secrets["google_drive"]
        settings = {key: str(section[key]).strip() for key in ["client_id", "client_secret", "refresh_token"]}
    except Exception:
        return None, "Google ドライブの設定（[google_drive]）が Secrets にありません。"
    try:
        settings["root_folder"] = str(section.get("root_folder", DEFAULT_ROOT_FOLDER))
    except Exception:
        settings["root_folder"] = DEFAULT_ROOT_FOLDER
    if not all(settings[k] for k in ["client_id", "client_secret", "refresh_token"]):
        return None, "Google ドライブの設定（[google_drive]）に空の項目があります。"
    return settings, ""


def connect_drive(settings):
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials

    credentials = Credentials(
        token=None,
        refresh_token=settings["refresh_token"],
        token_uri=TOKEN_URI,
        client_id=settings["client_id"],
        client_secret=settings["client_secret"],
        scopes=DRIVE_SCOPES,
    )
    return DriveStorage(AuthorizedSession(credentials), settings.get("root_folder", DEFAULT_ROOT_FOLDER))


def explain_drive_error(error):
    text = str(error)
    if "invalid_grant" in text:
        return (
            "Google ドライブの許可証（リフレッシュトークン）が使えなくなっています。"
            "期限切れか取り消しの可能性があります。許可証を発行し直して、Secrets を更新してください。"
        )
    if "invalid_client" in text or "unauthorized_client" in text:
        return "Google ドライブの設定（client_id / client_secret）がまちがっています。Secrets を確認してください。"
    if isinstance(error, DriveError) and error.status == 404:
        return "Google ドライブに保存したファイルが見つかりません（ドライブで消された可能性があります）。"
    if isinstance(error, DriveError) and error.status == 403:
        return (
            "Google ドライブを使う権限がありません（ドライブの API が有効か、許可の範囲を確認してください）。"
        )
    return f"Google ドライブとの通信でエラーが起きました（{type(error).__name__}：{text[:200]}）"
