from __future__ import annotations

import numpy as np
from PIL import Image

from designbridge.layout.vision import _write_segmentation_preview


def test_segmentation_preview_colorizes_labels_without_changing_source(tmp_path):
    labels = np.array([[0, 1], [1, 2]], dtype=np.uint16)
    source = tmp_path / "segmentation.png"
    preview = tmp_path / "segmentation_preview.png"
    Image.fromarray(labels).save(source)

    _write_segmentation_preview(source, preview)

    with Image.open(source) as image:
        np.testing.assert_array_equal(np.asarray(image, dtype=np.uint16), labels)
    with Image.open(preview) as image:
        colors = np.asarray(image.convert("RGB"))
        assert colors.shape == (2, 2, 3)
        assert len(np.unique(colors.reshape(-1, 3), axis=0)) == 3
        assert np.all(colors[0, 0] > 0)
