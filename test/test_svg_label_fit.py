from designbridge.roomplan.svg_render import _fit_labels

DETAILS = [('1.8 m²', 11), ('1.50 × 1.20 m', 10)]


def test_large_room_keeps_full_size_labels():
    assert _fit_labels(200, 150, '客廳', DETAILS) == (1.0, True)


def test_medium_room_shrinks_but_keeps_details():
    k, show = _fit_labels(75, 75, '浴室', DETAILS)
    assert show and 0.75 <= k < 1.0


def test_tiny_room_shows_name_only():
    k, show = _fit_labels(24, 35, '小廁所', DETAILS)
    assert not show and k < 0.75
