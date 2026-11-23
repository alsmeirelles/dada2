"""Canonical decode of HEIC/HEIF sources and their lossless WebP rendition (P7-06).

The primary image is decoded once with its HEIF transformations applied by
the decoder, converted to 8-bit sRGB RGB or RGBA, and written as lossless WebP
in exact mode with the sRGB profile. Nothing is resized, cropped, or padded,
so the rendition has the source's oriented width and height and every
annotation coordinate maps to the retained original.
"""

import io
from pathlib import Path

import pillow_heif
from PIL import Image, ImageCms

pillow_heif.register_heif_opener()

HEIF_FORMAT = "HEIF"
ALPHA_MODES = frozenset({"RGBA", "LA", "PA", "RGBa", "La"})
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))


class ConversionError(Exception):
    """A valid decoded image that could not be written as the rendition."""


def canonical_image(source: Path) -> Image.Image:
    """Decode a source into the canonical 8-bit sRGB pixel plane.

    Args:
        source: Path of the HEIC/HEIF source.

    Returns:
        The oriented image in ``RGB`` or ``RGBA`` mode.

    Raises:
        OSError: When the file cannot be decoded.
    """
    with Image.open(source) as image:
        image.load()
        mode = "RGBA" if image.mode in ALPHA_MODES else "RGB"
        profile = image.info.get("icc_profile")
        if not profile:
            return image.convert(mode)
        colour = ImageCms.profileToProfile(
            image.convert("RGB"),
            ImageCms.ImageCmsProfile(io.BytesIO(profile)),
            SRGB,
            outputMode="RGB",
        )
        if mode == "RGB":
            return colour
        colour.putalpha(image.getchannel("A") if "A" in image.getbands() else 255)
        return colour


def write_rendition(source: Path, target: Path) -> tuple[int, int]:
    """Write a source's lossless WebP rendition and return its dimensions.

    Args:
        source: Path of the HEIC/HEIF source.
        target: Path the rendition is written to.

    Returns:
        The rendition's width and height.

    Raises:
        OSError: When the source cannot be decoded.
        ConversionError: When the decoded image cannot be encoded.
    """
    image = canonical_image(source)
    try:
        image.save(
            target,
            format="WEBP",
            lossless=True,
            exact=True,
            quality=100,
            method=6,
            icc_profile=SRGB.tobytes(),
        )
    except (OSError, ValueError) as error:
        raise ConversionError(str(error)) from error
    return image.size


def is_heif(path: Path) -> bool:
    """Return whether a file decodes as an HEIC/HEIF image.

    Raises:
        OSError: When the file cannot be read as any image.
    """
    with Image.open(path) as image:
        return image.format == HEIF_FORMAT
