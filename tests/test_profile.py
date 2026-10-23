import pytest

from konspekt.charset import RU_LOWER
from konspekt.profile import Profile


def test_roundtrip(profile):
    again = Profile.load(profile.root)
    assert len(again.samples) == len(profile.samples)
    assert again.params == profile.params


def test_measured_params(profile):
    assert 2.5 < profile.params.x_height_mm < 5.0
    assert 0.1 < profile.params.stroke_mm < 1.0


def test_coverage_full(profile):
    cov = profile.coverage()
    assert cov["строчные"]["нет"] == ""
    assert all(len(profile.variants(c)) == 3 for c in RU_LOWER)


def test_create_twice_fails(profile):
    with pytest.raises(FileExistsError):
        Profile.create(profile.root, "x")


def test_load_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        Profile.load(tmp_path)


def test_baseline_refined_to_ink_bottom():
    import numpy as np

    from konspekt.profile import refine_baseline

    a = np.zeros((120, 80), np.float32)
    a[30:90, 20:60] = 1.0  # «о», дописанная ниже пунктира
    assert refine_baseline(a, 80.0, "о") == 89.0
    assert refine_baseline(a, 80.0, "р") == 80.0  # у «р» есть хвост вниз
    assert refine_baseline(a, 10.0, "о") == 10.0  # слишком далеко — не трогаем


def test_duplicate_import_detected(tmp_path, filled_photos):
    prof = Profile.create(tmp_path / "p", "p")
    assert not prof.is_imported(filled_photos[0])
    prof.mark_imported(filled_photos[0])
    prof.save()
    again = Profile.load(prof.root)
    assert again.is_imported(filled_photos[0])
    assert not again.is_imported(filled_photos[1])


def test_cli_skips_reimport(tmp_path, filled_photos, capsys):
    from konspekt.cli import main

    args = ["--profiles", str(tmp_path), "import", "Почерк", str(filled_photos[0])]
    assert main(args) == 0
    n = len(Profile.load(tmp_path / "Почерк").samples)
    assert main(args) == 0
    assert "уже импортирован" in capsys.readouterr().out
    assert len(Profile.load(tmp_path / "Почерк").samples) == n


def test_letter_adjust_saved_and_deleted_sample(profile, tmp_path):
    import shutil

    from konspekt.profile import Profile

    shutil.copytree(profile.root, tmp_path / "p")
    prof = Profile.load(tmp_path / "p")
    prof.set_letter_adjust("д", scale=0.8, raise_mm=-0.5)
    prof.set_letter_adjust("а", scale=5.0)  # за пределами — обрезается
    victim = prof.variants("о")[0]
    prof.set_sample_scale(victim.id, 1.2)
    prof.save()
    p2 = Profile.load(tmp_path / "p")
    assert p2.letter_scale("д") == 0.8 and p2.letter_raise_mm("д") == -0.5
    assert p2.letter_scale("а") == 1.8
    assert p2.user_scale(victim) == pytest.approx(1.2)
    p2.set_letter_adjust("д", scale=1.0, raise_mm=0.0)
    assert "д" not in p2.letter_adjust
    p2.remove(victim.id)
    p2.save()
    p3 = Profile.load(tmp_path / "p")
    assert victim.id not in {s.id for s in p3.samples} and victim.id not in p3.variant_scale
    assert not (tmp_path / "p" / victim.file).exists()
