from pathlib import Path

import pytest

from konspekt.extract import import_files
from konspekt.profile import Profile
from konspekt.synthetic import fill_template, photograph

FONT = str(Path(__file__).parents[1] / "konspekt" / "assets" / "DejaVuSans.ttf")


@pytest.fixture(scope="session")
def filled_photos(tmp_path_factory):
    from PIL import Image

    d = tmp_path_factory.mktemp("photos")
    paths = []
    for i, page in enumerate(fill_template(FONT, seed=1)):
        p = d / f"фото_{i}.jpg"
        # PIL, а не cv2.imwrite: OpenCV на Windows не пишет в пути с кириллицей
        Image.fromarray(photograph(page, seed=i)).save(p, quality=95)
        paths.append(p)
    return paths


@pytest.fixture(scope="session")
def import_report(filled_photos):
    return import_files(filled_photos)


@pytest.fixture(scope="session")
def profile(import_report, tmp_path_factory):
    prof = Profile.create(tmp_path_factory.mktemp("prof") / "Тест", "Тест")
    prof.add_extracted(import_report.samples)
    prof.save()
    return Profile.load(prof.root)
