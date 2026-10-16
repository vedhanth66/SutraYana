import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.blender_bridge import find_blender_binary, extract_plan_payload, generate_blender_twin


def test_find_blender_binary():
    exe = find_blender_binary()
    assert exe is not None, "Blender executable should be discovered"
    assert Path(exe).is_file(), f"Blender executable path must exist: {exe}"


def test_extract_plan_payload():
    payload = extract_plan_payload("examples/plan_00666.json")
    assert payload["plan_id"] == "5313"
    assert len(payload["rooms"]) == 8
    assert len(payload["walls"]) == 5
    assert len(payload["windows"]) == 3
    assert len(payload["doors"]) == 6
    assert len(payload["terminals"]) == 4
    assert len(payload["hubs"]) == 1
    assert len(payload["hubs"][0]["segments"]) == 5
    # Bounds should be centered around (0, 0)
    bx0, by0, bx1, by1 = payload["bounds"]
    assert abs((bx0 + bx1) / 2.0) < 1e-3
    assert abs((by0 + by1) / 2.0) < 1e-3


def test_generate_blender_twin(tmp_path):
    blend_out = tmp_path / "test_twin.blend"
    res = generate_blender_twin(
        plan_source="examples/plan_00666.json",
        output_blend_path=blend_out,
        wall_height=1.4,
    )
    assert Path(res["blend_file"]).is_file()
    assert Path(res["blend_file"]).stat().st_size > 10000
    assert res["rooms_count"] == 8
    assert res["doors_count"] == 6
    assert res["windows_count"] == 3
    assert res["terminals_count"] == 4
    assert res["hubs_count"] == 1
    assert res["cables_count"] == 5
