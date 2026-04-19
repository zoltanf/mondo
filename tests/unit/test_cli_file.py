"""End-to-end CLI tests for `mondo file ...` (Phase 3g)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
FILE_ENDPOINT = "https://api.monday.com/v2/file"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


class TestUpload:
    def test_target_item_posts_to_file_endpoint(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        src = tmp_path / "report.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        httpx_mock.add_response(
            url=FILE_ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_file_to_column": {
                        "id": "asset-1",
                        "name": "report.pdf",
                        "url": "https://example.com/report.pdf",
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "file",
                "upload",
                "--file",
                str(src),
                "--item",
                "42",
                "--column",
                "files",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "report.pdf"
        # Verify we hit the /v2/file endpoint (not /v2).
        requests = httpx_mock.get_requests()
        assert len(requests) == 1
        assert requests[0].url == FILE_ENDPOINT
        # Verify it's multipart (Content-Type starts with multipart/form-data).
        ct = requests[0].headers.get("Content-Type", "")
        assert ct.startswith("multipart/form-data")

    def test_target_item_requires_item_and_column(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        src = tmp_path / "x.txt"
        src.write_text("x")
        result = runner.invoke(app, ["file", "upload", "--file", str(src), "--target", "item"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_target_update(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "x.png"
        src.write_bytes(b"\x89PNG")
        httpx_mock.add_response(
            url=FILE_ENDPOINT,
            method="POST",
            json=_ok({"add_file_to_update": {"id": "1", "name": "x.png"}}),
        )
        result = runner.invoke(
            app,
            [
                "file",
                "upload",
                "--file",
                str(src),
                "--target",
                "update",
                "--update",
                "777",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["id"] == "1"

    def test_target_update_requires_update(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "x.txt"
        src.write_text("x")
        result = runner.invoke(
            app,
            ["file", "upload", "--file", str(src), "--target", "update"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_missing_file_exits_2(self, httpx_mock: HTTPXMock) -> None:
        # Typer's exists=True check fires before any mutation.
        result = runner.invoke(
            app,
            [
                "file",
                "upload",
                "--file",
                "/nonexistent/file.xyz",
                "--item",
                "42",
                "--column",
                "files",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_dry_run(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "x.pdf"
        src.write_bytes(b"pdf")
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "file",
                "upload",
                "--file",
                str(src),
                "--item",
                "42",
                "--column",
                "files",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["endpoint"] == "/v2/file"
        assert "add_file_to_column" in parsed["query"]
        assert httpx_mock.get_requests() == []


class TestDownload:
    def test_basic(
        self, httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 1) assets(ids) lookup on /v2 returns url + name.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "assets": [
                        {
                            "id": "42",
                            "name": "report.pdf",
                            "url": "https://files.example.com/report.pdf",
                        }
                    ]
                }
            ),
        )
        # 2) HTTP GET on the pre-signed URL returns the file bytes.
        httpx_mock.add_response(
            url="https://files.example.com/report.pdf",
            method="GET",
            content=b"file-bytes",
        )
        # Run from tmp_path so the default output lands there.
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["file", "download", "--asset", "42"])
        assert result.exit_code == 0, result.stdout
        target = tmp_path / "report.pdf"
        assert target.exists()
        assert target.read_bytes() == b"file-bytes"
        parsed = json.loads(result.stdout)
        assert parsed["asset_id"] == "42"
        assert parsed["bytes"] == len(b"file-bytes")

    def test_with_out_path(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "assets": [
                        {
                            "id": "42",
                            "name": "report.pdf",
                            "url": "https://files.example.com/r.pdf",
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url="https://files.example.com/r.pdf",
            method="GET",
            content=b"xyz",
        )
        out = tmp_path / "out" / "saved.pdf"
        out.parent.mkdir()
        result = runner.invoke(
            app,
            ["file", "download", "--asset", "42", "--out", str(out)],
        )
        assert result.exit_code == 0, result.stdout
        assert out.read_bytes() == b"xyz"

    def test_missing_asset_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"assets": []}))
        result = runner.invoke(app, ["file", "download", "--asset", "999"])
        assert result.exit_code == 6

    def test_with_out_directory(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        """--out pointing at an existing directory appends the asset's name (curl -O / wget -P)."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "assets": [
                        {
                            "id": "42",
                            "name": "report.pdf",
                            "url": "https://files.example.com/r.pdf",
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url="https://files.example.com/r.pdf",
            method="GET",
            content=b"xyz",
        )
        result = runner.invoke(
            app,
            ["file", "download", "--asset", "42", "--out", str(tmp_path)],
        )
        assert result.exit_code == 0, result.stdout
        assert (tmp_path / "report.pdf").read_bytes() == b"xyz"

    def test_download_multiple_to_directory(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "assets": [
                        {
                            "id": "1",
                            "name": "a.txt",
                            "url": "https://files.example.com/a.txt",
                        },
                        {
                            "id": "2",
                            "name": "b.txt",
                            "url": "https://files.example.com/b.txt",
                        },
                    ]
                }
            ),
        )
        httpx_mock.add_response(url="https://files.example.com/a.txt", method="GET", content=b"AAA")
        httpx_mock.add_response(
            url="https://files.example.com/b.txt", method="GET", content=b"BBBB"
        )
        result = runner.invoke(
            app,
            ["file", "download", "--asset", "1", "--asset", "2", "--out", str(tmp_path)],
        )
        assert result.exit_code == 0, result.stdout
        assert (tmp_path / "a.txt").read_bytes() == b"AAA"
        assert (tmp_path / "b.txt").read_bytes() == b"BBBB"
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, list)
        assert [p["asset_id"] for p in parsed] == ["1", "2"]

    def test_download_multiple_rejects_file_out(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        bad = tmp_path / "not-a-dir.pdf"
        result = runner.invoke(
            app,
            ["file", "download", "--asset", "1", "--asset", "2", "--out", str(bad)],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_download_multiple_one_missing_fails_fast(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "assets": [
                        {
                            "id": "1",
                            "name": "a.txt",
                            "url": "https://files.example.com/a.txt",
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(
            app,
            ["file", "download", "--asset", "1", "--asset", "2", "--out", str(tmp_path)],
        )
        assert result.exit_code == 6
        # Only the metadata lookup — no downloads attempted.
        urls = [str(r.url) for r in httpx_mock.get_requests()]
        assert urls == [ENDPOINT]
