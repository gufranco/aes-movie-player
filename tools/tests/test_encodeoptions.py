from __future__ import annotations

from neogeomedia import encode, palettes
from neogeomedia.encodeoptions import EncodeOptions


class TestEncodeOptions:
    def test_the_encoder_takes_the_same_options(self):
        # Arrange
        expected = EncodeOptions

        # Act
        found = encode.EncodeOptions

        # Assert
        assert found is expected

    def test_the_default_dither_is_the_strongest(self):
        # Arrange
        options = EncodeOptions()

        # Act
        dither = options.dither

        # Assert
        assert dither == palettes.MAX_DITHER
