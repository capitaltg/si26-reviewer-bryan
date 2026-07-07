import json
import os

import httpx
import pytest

from worker import blob


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.raise_for_status_called = False

    def raise_for_status(self):
        self.raise_for_status_called = True


def test_download_sends_bearer_token_and_returns_bytes(monkeypatch):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "test-token")

    calls = []
    fake_response = _FakeResponse(b"file-bytes")

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, headers, timeout))
        return fake_response

    monkeypatch.setattr(httpx, "get", fake_get)

    result = blob.download("https://example.com/blob/foo")

    assert result == b"file-bytes"
    assert fake_response.raise_for_status_called is True
    assert len(calls) == 1
    url, headers, timeout = calls[0]
    assert url == "https://example.com/blob/foo"
    assert headers == {"Authorization": "Bearer test-token"}


def test_helper_dir_points_to_a_real_directory_containing_put_mjs():
    assert blob.HELPER_DIR.is_dir()
    assert (blob.HELPER_DIR / "put.mjs").is_file()


def test_upload_invokes_node_helper_and_parses_result(monkeypatch):
    calls = {}

    class _FakeCompletedProcess:
        def __init__(self, stdout):
            self.stdout = stdout
            self.stderr = ""

    def fake_run(cmd, cwd=None, capture_output=None, text=None, check=None, env=None):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        calls["capture_output"] = capture_output
        calls["text"] = text
        calls["check"] = check
        calls["env"] = env
        return _FakeCompletedProcess(
            stdout=json.dumps({"url": "https://blob.example/x", "pathname": "docs/x.pdf"})
        )

    monkeypatch.setattr(blob.subprocess, "run", fake_run)

    result = blob.upload("docs/x.pdf", "/tmp/local.pdf", "application/pdf")

    assert result == blob.BlobResult(url="https://blob.example/x", pathname="docs/x.pdf")
    assert calls["cmd"] == ["node", "put.mjs", "docs/x.pdf", "/tmp/local.pdf", "application/pdf"]
    assert calls["cwd"] == blob.HELPER_DIR
    assert calls["capture_output"] is True
    assert calls["text"] is True
    assert calls["check"] is True


@pytest.mark.skipif(
    not os.environ.get("BLOB_READ_WRITE_TOKEN"),
    reason="BLOB_READ_WRITE_TOKEN not set; skipping live Blob round-trip",
)
def test_upload_then_download_round_trips_bytes(tmp_path):
    content = b"integration-test-bytes"
    local_path = tmp_path / "roundtrip.bin"
    local_path.write_bytes(content)

    result = blob.upload("test/roundtrip.bin", str(local_path), "application/octet-stream")
    downloaded = blob.download(result.url)

    assert downloaded == content
