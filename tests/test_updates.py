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
