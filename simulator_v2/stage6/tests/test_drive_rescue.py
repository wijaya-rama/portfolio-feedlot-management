"""Small protocol and sealed-checkpoint tests for the Drive rescue workflow."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestConnectionError

from simulator_v2.stage6.__main__ import build
from simulator_v2.stage6.colab import drive_resumable as http_upload
from simulator_v2.stage6.colab import production as prod
from simulator_v2.stage6.colab import drive_storage
from simulator_v2.stage6.colab.drive_storage import Drive
from simulator_v2.stage6.tests.test_production_colab import attempt_setup, reopen  # noqa: F401


SESSION = "https://www.googleapis.com/upload/drive/v3/files?upload_id=PRIVATE"


def response(code, **headers):
    return SimpleNamespace(status_code=code, headers=headers)


@pytest.fixture
def mock_transport(monkeypatch, tmp_path):
    archive = tmp_path / "test.tar"
    archive.write_bytes(b"0123456789")
    monkeypatch.setattr(http_upload, "CHUNK", 4)
    monkeypatch.setattr(http_upload, "sleep", lambda _delay: None)

    class Transport:
        def __init__(self, *responses):
            self.responses = iter(responses)
            self.calls = []

        def request(self, method, url, **kwargs):
            assert kwargs["allow_redirects"] is False
            self.calls.append((method, url, kwargs))
            item = next(self.responses)
            if isinstance(item, Exception):
                raise item
            return item

    return archive, Transport


def test_308_without_location_and_transfer_reconciles_after_network_error(mock_transport):
    archive, transport = mock_transport
    wire = transport(response(200, Location=SESSION), response(308, Range="bytes=0-3"),
                     RequestConnectionError("lost chunk response"), response(503), response(308, Range="bytes=0-7"),
                     response(200))
    progress = []
    http_upload.upload_tar(wire, "fixedId001", {"name": ".test.tar.partial"}, archive, progress.append, replace=False)
    assert progress == [0.4, 0.8, 1.0]
    assert wire.calls[0][0] == "POST"
    assert [call[2]["headers"]["Content-Range"] for call in wire.calls[1:]] == [
        "bytes 0-3/10", "bytes 4-7/10", "bytes */10", "bytes */10", "bytes 8-9/10"]
    assert wire.calls[-1][2]["data"] == b"89"


def test_update_uses_fixed_id_and_308_without_range_resends_from_zero(mock_transport):
    archive, transport = mock_transport
    wire = transport(response(200, Location=SESSION), response(308), response(308, Range="bytes=0-3"),
                     response(308, Range="bytes=0-7"), response(308, Range="bytes=0-9"), response(201))
    http_upload.upload_tar(wire, "fixedId001", {}, archive, lambda _: None, replace=True)
    assert wire.calls[0][:2] == ("PATCH", f"{http_upload.UPLOAD}/fixedId001")
    assert wire.calls[1][2]["data"] == wire.calls[2][2]["data"] == b"0123"
    assert wire.calls[-1][2]["headers"]["Content-Range"] == "bytes */10"


@pytest.mark.parametrize("location", ["https://example.com/transfer", "http://www.googleapis.com/upload",
                                     "https://user@www.googleapis.com/upload"])
def test_refuses_untrusted_session_url(mock_transport, location):
    archive, transport = mock_transport
    wire = transport(response(200, Location=location))
    with pytest.raises(http_upload.UploadError, match="URL sesi"):
        http_upload.upload_tar(wire, "fixedId001", {}, archive, lambda _: None, replace=False)
    assert len(wire.calls) == 1


@pytest.mark.parametrize("reply", [response(308, Range="bytes=0-8"), response(308, Range="broken"), response(200)])
def test_rejects_invalid_acknowledgement(mock_transport, reply):
    archive, transport = mock_transport
    wire = transport(response(200, Location=SESSION), reply)
    with pytest.raises(http_upload.UploadError):
        http_upload.upload_tar(wire, "fixedId001", {}, archive, lambda _: None, replace=False)


def test_ambiguous_final_response_requires_matching_cloud_metadata(mock_transport, monkeypatch):
    archive, transport = mock_transport
    content = archive.read_bytes()
    properties = {"sha256": sha256(content).hexdigest(), "seal": "a" * 64}
    file_id, folder, name = "fixedId001", "folder0001", ".test.tar.partial"
    meta = {"parents": [folder], "name": name, "size": str(len(content)),
            "sha256Checksum": properties["sha256"], "appProperties": properties.copy()}
    service = SimpleNamespace(files=lambda: None)
    wire = transport(response(200, Location=SESSION), response(308, Range="bytes=0-3"),
                     response(308, Range="bytes=0-7"), RequestConnectionError("final response lost"), response(404))
    drive = Drive(service, wire)
    monkeypatch.setattr(drive_storage, "sleep", lambda _: None)
    metadata = iter((None, {**meta, "sha256Checksum": None}, meta))
    monkeypatch.setattr(drive, "get", lambda _: next(metadata, meta))
    progress = []
    drive.upload(file_id, folder, name, properties, archive, progress.append)
    assert progress == [0.4, 0.8, 1.0]
    assert wire.calls[0][2]["json"]["id"] == file_id
    drive.upload_http = transport(response(200, Location=SESSION), response(410))
    meta["sha256Checksum"] = "0" * 64
    with pytest.raises(http_upload.UploadError, match="410"):
        drive.upload(file_id, folder, name, properties, archive, progress.append)


@pytest.fixture
def rescue_setup(attempt_setup, tmp_path):
    attempt, path, config, drive = attempt_setup
    work = tmp_path / "sealed-source"
    build(config, tmp_path / "unused-dataset", workspace=work, stop_after="operations")
    tar = tmp_path / "rescue.tar"
    prod.pack(work / "operations", tar, attempt.resources, lambda: None)
    raw = tar.read_bytes()
    info = prod.file_info(tar)
    rescue_id = drive.ids(1)[0]
    drive.files[rescue_id] = ({"name": "independent-rescue.tar", "parents": ["MyDriveRoot"],
                               "size": str(info["bytes"]), "sha256Checksum": info["sha256"]}, raw)
    return attempt, path, config, drive, work, tar, info, rescue_id


def test_fresh_registration_reuses_operations_and_publishes_to_original_slot(rescue_setup, tmp_path):
    attempt, path, config, drive, source, _, info, rescue_id = rescue_setup
    immutable = deepcopy(drive.files[rescue_id])
    prior_manifest = deepcopy(drive.files[attempt.slots["attempt"]])
    fresh = reopen(attempt, tmp_path / "fresh")

    with pytest.raises(ValueError, match="operations resmi belum terverifikasi"):
        fresh.run(config, path, require_operations=True)
    assert not drive.events

    official = fresh.register_operations(rescue_id, info["bytes"], info["sha256"])
    assert official == fresh.artifact("operations", None)
    assert official["id"] == attempt.slots["operations"]
    assert official["seal"] == prod.digest(source / "operations" / "checkpoint.json")
    assert drive.files[rescue_id] == immutable
    assert drive.files[attempt.slots["attempt"]] == prior_manifest
    assert drive.events == ["checkpoint-operations.tar"]
    assert fresh.inspect()["last_verified_checkpoint"] == "operations"
    assert fresh.register_operations(rescue_id, info["bytes"], info["sha256"]) == official
    assert drive.events == ["checkpoint-operations.tar"]

    # A second fresh runtime can restore the official archive instead of replaying operations.
    reopened = reopen(attempt, tmp_path / "second-fresh")
    reopened.run(config, path, require_operations=True)
    assert drive.events == ["checkpoint-operations.tar", "finance", "checkpoint-finance.tar",
                            "audit", "dataset-integrity-only.tar"]
    assert drive.get(attempt.slots["finance"])["appProperties"]["parent"] == official["seal"]


def test_registration_accepts_identical_local_tar_without_downloading(rescue_setup, tmp_path, monkeypatch):
    attempt, _, _, drive, _, tar, info, rescue_id = rescue_setup
    monkeypatch.setattr(drive, "download", lambda *args: pytest.fail("unexpected rescue download"))
    fresh = reopen(attempt, tmp_path / "fresh")
    fresh.register_operations(rescue_id, info["bytes"], info["sha256"], local_tar=tar)
    assert drive.events == ["checkpoint-operations.tar"]


def test_registration_rejects_wrong_sha_and_foreign_identity(rescue_setup, tmp_path):
    attempt, _, config, drive, _, _, info, rescue_id = rescue_setup
    fresh = reopen(attempt, tmp_path / "fresh")
    with pytest.raises(ValueError, match="arsip rescue Drive berbeda"):
        fresh.register_operations(rescue_id, info["bytes"], "0" * 64)

    other = tmp_path / "other"
    build({**config, "seed": config["seed"] + 1}, tmp_path / "no-dataset", workspace=other, stop_after="operations")
    archive = tmp_path / "different.tar"
    prod.pack(other / "operations", archive, attempt.resources, lambda: None)
    data = archive.read_bytes()
    checksum = sha256(data).hexdigest()
    drive.files[rescue_id] = ({"name": "different.tar", "size": str(len(data)), "sha256Checksum": checksum}, data)
    with pytest.raises(ValueError, match="checkpoint identity"):
        fresh.register_operations(rescue_id, len(data), checksum)
    assert not drive.events
    assert drive.get(attempt.slots["operations"]) is None


def test_registration_retries_a_verified_staged_upload_without_overwriting(rescue_setup, tmp_path, monkeypatch):
    attempt, _, _, drive, _, _, info, rescue_id = rescue_setup
    fresh = reopen(attempt, tmp_path / "fresh")
    drive.fault = ("operations", "after_server_commit")
    with pytest.raises(ConnectionError):
        fresh.register_operations(rescue_id, info["bytes"], info["sha256"])
    assert fresh.artifact("operations", None) is None

    monkeypatch.setattr(drive, "upload", lambda *args, **kwargs: pytest.fail("verified staged TAR uploaded again"))
    official = fresh.register_operations(rescue_id, info["bytes"], info["sha256"])
    assert official["sha256"] == info["sha256"]
    assert drive.events == ["checkpoint-operations.tar"]
