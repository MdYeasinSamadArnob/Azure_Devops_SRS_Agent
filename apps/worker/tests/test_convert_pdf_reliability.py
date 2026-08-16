"""Regression tests for a real reliability bug: PDF conversion "getting
stuck" on large documents. Root cause (confirmed live): a flat 120s timeout
regardless of document size, and no isolated LibreOffice profile — a
conversion killed on timeout left an orphaned `soffice.bin` holding the
shared profile lock, hanging every conversion after it. These tests mock
`subprocess.Popen` since reproducing a real multi-hundred-second hang isn't
practical in a unit test; the real conversion path is still exercised
end-to-end (against actual LibreOffice) by test_generate_flow.py.
"""

import signal
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.tasks.generate_pipeline import (
    CONVERSION_BASE_TIMEOUT_SECONDS,
    CONVERSION_MAX_TIMEOUT_SECONDS,
    _run_soffice_conversion,
    _timeout_for_size,
)


def test_timeout_for_size_scales_with_document_size():
    small = _timeout_for_size(1 * 1024 * 1024)
    large = _timeout_for_size(50 * 1024 * 1024)
    assert small == CONVERSION_BASE_TIMEOUT_SECONDS + 20
    assert large > small
    assert large <= CONVERSION_MAX_TIMEOUT_SECONDS


def test_timeout_for_size_is_capped_for_pathological_documents():
    huge = _timeout_for_size(10_000 * 1024 * 1024)
    assert huge == CONVERSION_MAX_TIMEOUT_SECONDS


def test_run_soffice_conversion_passes_isolated_profile_directory(tmp_path):
    fake_process = MagicMock()
    fake_process.communicate.return_value = (b"", b"")
    fake_process.returncode = 0
    fake_process.pid = 4242

    with patch("src.tasks.generate_pipeline.subprocess.Popen", return_value=fake_process) as popen:
        _run_soffice_conversion(tmp_path / "document.docx", str(tmp_path), tmp_path / "lo_profile", 180)

    args, kwargs = popen.call_args
    cmd = args[0]
    assert any(part.startswith("-env:UserInstallation=file://") for part in cmd)
    assert kwargs.get("start_new_session") is True


def test_run_soffice_conversion_kills_the_whole_process_group_on_timeout(tmp_path):
    """The actual mechanism behind the stale-lock cascade: subprocess.run's
    timeout only kills the immediate launcher, letting soffice.bin survive
    as an orphan holding the profile lock. Popen + killpg on the whole
    session prevents that orphan from ever existing.
    """
    fake_process = MagicMock()
    fake_process.communicate.side_effect = subprocess.TimeoutExpired(cmd="soffice", timeout=180)
    fake_process.pid = 9999

    with patch("src.tasks.generate_pipeline.subprocess.Popen", return_value=fake_process), patch(
        "src.tasks.generate_pipeline.os.killpg"
    ) as killpg:
        with pytest.raises(RuntimeError, match="exceeded 180s timeout"):
            _run_soffice_conversion(tmp_path / "document.docx", str(tmp_path), tmp_path / "lo_profile", 180)

    killpg.assert_called_once_with(9999, signal.SIGKILL)
    fake_process.wait.assert_called_once()


def test_run_soffice_conversion_raises_with_stderr_on_nonzero_exit(tmp_path):
    fake_process = MagicMock()
    fake_process.communicate.return_value = (b"", b"conversion crashed: bad input")
    fake_process.returncode = 1
    fake_process.pid = 111

    with patch("src.tasks.generate_pipeline.subprocess.Popen", return_value=fake_process):
        with pytest.raises(RuntimeError, match="conversion crashed: bad input"):
            _run_soffice_conversion(tmp_path / "document.docx", str(tmp_path), tmp_path / "lo_profile", 180)
