import os

import pytest


@pytest.fixture(autouse=True)
def restore_environ():
    """load_dotenv ve NO_PROXY güncellemesi os.environ'a yazar: her test temiz ortamla başlasın."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
