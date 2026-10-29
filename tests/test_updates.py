"""Проверка новой версии и замена папки программы — без настоящего GitHub."""

import io
import json
import os

import pytest

from konspekt import updates


def test_versions():
    assert updates.parse_version("v0.2.21") == (0, 2, 21)
    assert updates.is_newer("0.2.21", "0.2.9")
    assert not updates.is_newer("0.2.20", "0.2.20")
    assert not updates.is_newer("0.2.21", None)  # из исходников версия неизвестна


def test_versions_compare_as_numbers():
    # 0.2.40 новее 0.2.7 и 0.2.4, хотя как строка «0.2.40» < «0.2.7»
    assert updates.is_newer("0.2.40", "0.2.7")
    assert not updates.is_newer("0.2.7", "0.2.40")
    assert not updates.is_newer("0.2.4", "0.2.40")
    assert updates.is_newer("0.3.0", "0.2.99")


def test_in_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(updates.tempfile, "gettempdir", lambda: str(tmp_path))
    # так Windows распаковывает программу, открытую прямо в архиве
    assert updates.in_temp(tmp_path / "Temp1_Konspekt-windows.zip" / "Konspekt")
    assert not updates.in_temp(tmp_path / "konspekt-update-abc" / "new" / "Konspekt")
    assert not updates.in_temp(tmp_path.parent / "Downloads" / "Konspekt")


def test_update_outcome(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert updates.update_outcome("0.2.40", str(a), "0.2.40", a) == "ok"
    assert updates.update_outcome("0.2.40", str(a), "0.2.41", b) == "ok"
    assert updates.update_outcome("0.2.40", str(a), "0.2.38", a) == "failed"
    assert updates.update_outcome("0.2.40", str(a), "0.2.38", b) == "other_copy"


def test_fetch_latest(monkeypatch):
    data = {"tag_name": "v0.2.30", "body": "Что нового", "html_url": "https://example/rel",
            "assets": [{"name": "other.zip"}, {"name": updates.ASSET_NAME, "size": 5,
                                               "browser_download_url": "https://example/k.zip"}]}
    monkeypatch.setattr(updates, "_open", lambda url, timeout: io.BytesIO(json.dumps(data).encode()))
    rel = updates.fetch_latest()
    assert (rel.version, rel.download_url, rel.size, rel.notes) == ("0.2.30", "https://example/k.zip", 5, "Что нового")


def test_offline_raises_oserror(monkeypatch):
    def offline(url, timeout):
        raise OSError("нет сети")
    monkeypatch.setattr(updates, "_open", offline)
    with pytest.raises(OSError):
        updates.fetch_latest()


def test_replace_dir(tmp_path):
    target, new = tmp_path / "Konspekt", tmp_path / "new"
    target.mkdir()
    (target / "old.txt").write_text("1")
    new.mkdir()
    (new / "Konspekt.exe").write_text("2")
    updates.replace_dir(new, target)
    assert sorted(os.listdir(target)) == ["Konspekt.exe"]
    assert not (tmp_path / "Konspekt.old").exists()


def test_replace_dir_keeps_old_on_failure(tmp_path):
    target = tmp_path / "Konspekt"
    target.mkdir()
    (target / "old.txt").write_text("1")
    with pytest.raises(OSError):
        updates.replace_dir(tmp_path / "нет такой", target)
    assert (target / "old.txt").read_text() == "1"
