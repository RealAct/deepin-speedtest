import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import pytest  # noqa: E402

from deepin_speedtest import i18n  # noqa: E402


@pytest.fixture(autouse=True)
def _english_by_default():
    """Tests check English texts unless they switch the language themselves."""
    i18n.set_language("en")
    yield
    i18n.set_language("en")
