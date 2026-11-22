"""Drive API transport for server-verified binary artifacts and run metadata."""

from hashlib import sha256
import json
import re

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload, MediaIoBaseDownload

from ...stage1.provenance import canonical

FIELDS = "id,name,parents,mimeType,trashed,size,sha256Checksum,appProperties,webViewLink"
CHUNK = 32 * 1024**2
RETRIES = 3
FOLDER = "application/vnd.google-apps.folder"


def connect():
    import google.auth
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build
    import httplib2

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive"])
    http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=120))
    return Drive(build("drive", "v3", http=http, cache_discovery=False))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{10,150}", value),
            "ID folder atau berkas Drive tidak valid.")
    return value


class Drive:
    def __init__(self, service):
        self.service = service
        self.files = service.files()

    def free_bytes(self):
        quota = self.service.about().get(fields="storageQuota").execute(num_retries=RETRIES)["storageQuota"]
        require("limit" in quota and "usage" in quota, "Kuota Drive tidak dapat diukur melalui Drive API.")
        return max(0, int(quota["limit"]) - int(quota["usage"]))

    def ids(self, count):
        return self.files.generateIds(count=count, space="drive").execute(num_retries=RETRIES)["ids"]

    def get(self, file_id):
        try:
            return self.files.get(fileId=file_id, fields=FIELDS).execute(num_retries=RETRIES)
        except HttpError as error:
            if error.resp.status != 404:
                raise
            return None

    def find(self, folder, name):
        checked_id(folder)
        matches = self.files.list(
            q=f"'{folder}' in parents and name = '{name}' and trashed = false",
            fields="nextPageToken,incompleteSearch,files(id)", spaces="drive",
        ).execute(num_retries=RETRIES)
        files = matches["files"]
        require(len(files) == 1 and not matches.get("nextPageToken") and not matches.get("incompleteSearch"),
                f"Drive harus memiliki satu {name} di folder {folder}.")
        return files[0]["id"]

    def folder(self, name):
        return self.files.create(body={"name": name, "mimeType": FOLDER}, fields="id").execute(num_retries=RETRIES)["id"]

    def trash(self, file_id):
        self.files.update(fileId=file_id, body={"trashed": True}).execute(num_retries=RETRIES)

    def read_json(self, file_id):
        for _ in range(RETRIES):
            metadata = self.get(file_id)
            if metadata is None:
                return None
            require(not metadata.get("trashed") and 0 < int(metadata["size"]) <= 1024**2,
                    f"Manifest Drive tidak dapat dibaca ({file_id}).")
            raw = self.files.get_media(fileId=file_id).execute(num_retries=RETRIES)
            if blob_matches(metadata, len(raw), sha256(raw).hexdigest()):
                return json.loads(raw)
        raise ValueError(f"SHA-256 manifest Drive berbeda ({file_id}).")

    def write_json(self, file_id, value, *, folder=None, name=None):
        raw = canonical(value)
        media = MediaInMemoryUpload(raw, mimetype="application/json")
        if folder is None:
            request = self.files.update(fileId=file_id, media_body=media, fields=FIELDS)
        else:
            request = self.files.create(body={"id": file_id, "name": name, "parents": [folder]},
                                        media_body=media, fields=FIELDS)
        request.execute(num_retries=RETRIES)
        require(blob_matches(self.get(file_id), len(raw), sha256(raw).hexdigest()),
                f"Manifest Drive belum terverifikasi ({name or file_id}).")

    def release_claim(self, file_id):
        self.files.update(fileId=file_id, body={"appProperties": {"released": "yes"}}).execute(num_retries=RETRIES)

    def upload(self, file_id, folder, name, properties, archive, progress, *, replace=False):
        media = MediaFileUpload(str(archive), mimetype="application/x-tar", chunksize=CHUNK, resumable=True)
        body = {"name": name, "appProperties": properties}
        try:
            if replace:
                request = self.files.update(fileId=file_id, body=body, media_body=media, fields=FIELDS)
            else:
                request = self.files.create(body={**body, "id": file_id, "parents": [folder]},
                                            media_body=media, fields=FIELDS)
            result = None
            while result is None:
                moved, result = request.next_chunk(num_retries=RETRIES)
                if moved is not None:
                    progress(moved.progress())
        finally:
            media.stream().close()

    def rename(self, file_id, name):
        self.files.update(fileId=file_id, body={"name": name}, fields=FIELDS).execute(num_retries=RETRIES)

    def download(self, file_id, stream, progress):
        downloader = MediaIoBaseDownload(stream, self.files.get_media(fileId=file_id), chunksize=CHUNK)
        done = False
        while not done:
            moved, done = downloader.next_chunk(num_retries=RETRIES)
            if moved is not None:
                progress(moved.progress())


def blob_matches(metadata, size, digest):
    return (metadata is not None and not metadata.get("trashed")
            and int(metadata.get("size", -1)) == size and metadata.get("sha256Checksum") == digest)
