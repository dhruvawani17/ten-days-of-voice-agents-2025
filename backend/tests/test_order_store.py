import json
import sys
from pathlib import Path

import pytest

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from order_store import BRAND_NAME, save_order_to_disk


@pytest.fixture()
def sample_order():
    return {
        "drinkType": "latte",
        "size": "medium",
        "milk": "oat",
        "extras": ["caramel drizzle"],
        "name": "Jordan",
    }


def test_save_order_to_disk_creates_json(tmp_path: Path, sample_order):
    result = save_order_to_disk(sample_order, directory=tmp_path)

    saved_path = Path(result["path"])
    assert saved_path.exists()

    data = json.loads(saved_path.read_text(encoding="utf-8"))
    assert data["order"] == result["order"]
    assert data["summary"] == result["summary"]
    assert data["summary"].startswith(f"{BRAND_NAME} order for {sample_order['name']}")


def test_save_order_normalizes_extras(tmp_path: Path, sample_order):
    sample_order["extras"] = "caramel drizzle, cinnamon"
    result = save_order_to_disk(sample_order, directory=tmp_path)

    assert result["order"]["extras"] == ["caramel drizzle", "cinnamon"]


def test_save_order_missing_field(tmp_path: Path, sample_order):
    sample_order.pop("milk")
    with pytest.raises(ValueError):
        save_order_to_disk(sample_order, directory=tmp_path)
