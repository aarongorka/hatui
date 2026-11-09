import io

from PIL import Image
from rich.style import Style

from hatui.camera import camera_url, image_to_text
from hatui.lovelace import DisplayEntity, generate_cards
from hatui.translate import Translations


def _png(width: int, height: int, colour: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def test_camera_url_follows_websocket_scheme() -> None:
    assert (
        camera_url("wss://ha.local:8123/api/websocket", "camera.door")
        == "https://ha.local:8123/api/camera_proxy/camera.door"
    )
    assert camera_url("ws://ha/api/websocket", "camera.a").startswith("http://ha/")


def test_image_is_scaled_to_fit_and_uses_half_blocks() -> None:
    text = image_to_text(_png(400, 200, (255, 0, 0)), columns=20, rows=6)

    lines = text.plain.split("\n")
    assert len(lines) <= 6
    assert all(len(line) <= 20 for line in lines)
    assert set(text.plain) <= {"▀", "\n"}
    style = text.spans[0].style
    assert isinstance(style, Style)
    assert style.color is not None
    assert style.color.get_truecolor().red == 255


def test_cameras_only_appear_when_enabled() -> None:
    entities = [DisplayEntity("camera.door")]
    states = [{"entity_id": "camera.door", "state": "idle", "attributes": {}}]
    name = Translations().domain_name

    assert generate_cards([], [], entities, states, name) == []
    (card,) = generate_cards([], [], entities, states, name, show_cameras=True)
    assert [r.entity_id for r in card.rows] == ["camera.door"]
