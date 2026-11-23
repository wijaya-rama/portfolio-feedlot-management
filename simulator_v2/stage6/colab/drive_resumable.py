"""Upload one TAR using the Drive protocol's 308 acknowledgement responses."""

import re
from time import sleep
from urllib.parse import urlparse

from requests.exceptions import RequestException

UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
MIME = "application/x-tar"
CHUNK = 64 * 1024**2  # Non-final chunks must be multiples of 256 KiB.
ATTEMPTS = 6
TIMEOUT = (20, 120)


class UploadError(RuntimeError):
    """A resumable transfer could not confirm success."""


def request(http, method, url, **kwargs):
    try:
        return http.request(method, url, timeout=TIMEOUT, allow_redirects=False, **kwargs)
    except RequestException:
        # A request exception can include the private resumable-session URL.
        return None


def retryable(response):
    if response is None or response.status_code in (408, 429) or response.status_code >= 500:
        return True
    if response.status_code == 403:
        try:
            errors = response.json()["error"]["errors"]
            return any(row.get("reason") in {"rateLimitExceeded", "userRateLimitExceeded"} for row in errors)
        except (ValueError, TypeError, KeyError):
            pass
    return False


def retry_request(http, method, url, **kwargs):
    for attempt in range(ATTEMPTS):
        reply = request(http, method, url, **kwargs)
        if not retryable(reply):
            return reply
        if attempt < ATTEMPTS - 1:
            sleep(min(2 ** (attempt + 1), 30))
    raise UploadError("Drive tidak merespons setelah beberapa percobaan. Periksa Status lalu ulangi tindakan.")


def offset_from(reply, limit):
    header = reply.headers.get("Range", "")
    matched = re.fullmatch(r"bytes=0-(\d+)", header, re.IGNORECASE)
    if header and not matched:
        raise UploadError("Drive mengirim header Range yang tidak valid.")
    offset = int(matched[1]) + 1 if matched else 0
    if offset > limit:
        raise UploadError("Drive mengonfirmasi byte di luar permintaan terakhir.")
    return offset


def upload_tar(http, file_id, body, archive, progress, *, replace):
    size = archive.stat().st_size
    if size <= 0:
        raise UploadError("Arsip unggah kosong.")
    target = f"{UPLOAD}/{file_id}" if replace else UPLOAD
    reply = retry_request(http, "PATCH" if replace else "POST", target,
                          params={"uploadType": "resumable", "fields": "id"}, json=body,
                          headers={"X-Upload-Content-Type": MIME, "X-Upload-Content-Length": str(size)})
    if reply.status_code not in (200, 201):
        raise UploadError(f"Pembukaan sesi unggah ditolak Drive (HTTP {reply.status_code}).")
    session = reply.headers.get("Location", "")
    url = urlparse(session)
    if (url.scheme != "https" or not (url.hostname or "").endswith(".googleapis.com")
            or url.username or url.password or url.port not in (None, 443)):
        raise UploadError("Drive tidak mengembalikan URL sesi HTTPS yang valid.")

    offset = high_water = stalled = 0
    with archive.open("rb") as stream:
        while stalled < ATTEMPTS:
            if offset < size:
                stream.seek(offset)
                data = stream.read(min(CHUNK, size - offset))
                if not data:
                    raise UploadError("Arsip lokal berubah selama unggahan.")
                limit = offset + len(data)
                reply = request(http, "PUT", session, data=data,
                                headers={"Content-Range": f"bytes {offset}-{limit - 1}/{size}",
                                         "Content-Type": MIME, "Content-Length": str(len(data))})
            else:
                limit = size
                reply = None

            if retryable(reply):
                reply = retry_request(http, "PUT", session, data=b"",
                                      headers={"Content-Range": f"bytes */{size}", "Content-Length": "0"})

            if reply.status_code in (200, 201):
                if limit != size:
                    raise UploadError("Drive menyatakan unggahan selesai sebelum semua byte dikirim.")
                progress(1.0)
                return
            if reply.status_code != 308:
                raise UploadError(f"Sesi unggah berhenti (HTTP {reply.status_code}). Periksa Status lalu ulangi tindakan.")

            # 308 is acknowledgement, not an HTTP redirect. No Location is expected here.
            offset = offset_from(reply, limit)
            if offset > high_water:
                high_water, stalled = offset, 0
                progress(offset / size)
            else:
                stalled += 1
                if stalled < ATTEMPTS:
                    sleep(min(2 ** stalled, 30))

    raise UploadError("Drive berhenti mengonfirmasi byte tambahan. Periksa Status lalu ulangi tindakan.")
