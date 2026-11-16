# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT
"""Check the supplied brand artwork is available and accessible in Studio."""

import struct
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

WEB = Path(__file__).resolve().parents[1] / "web"


class _BrandMarkup(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.home_label = ""
        self.brand_images: list[dict[str, str | None]] = []
        self.favicons: list[dict[str, str | None]] = []
        self._in_brand = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and "brand" in (attributes.get("class") or "").split():
            self._in_brand = True
            self.home_label = attributes.get("aria-label") or ""
        elif tag == "img" and self._in_brand:
            self.brand_images.append(attributes)
        elif tag == "link" and attributes.get("rel") == "icon":
            self.favicons.append(attributes)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._in_brand = False


class BrandingTests(unittest.TestCase):
    """Preserve accessible branding and prevent broken local asset references."""

    def setUp(self) -> None:
        self.markup = _BrandMarkup()
        self.markup.feed((WEB / "index.html").read_text(encoding="utf-8"))

    def test_home_link_names_decorative_logos_once(self) -> None:
        assert "Panini-Animgx" in self.markup.home_label
        assert self.markup.brand_images
        for image in self.markup.brand_images:
            with self.subTest(source=image.get("src")):
                assert image.get("alt") == ""
                assert int(image.get("width") or "0") > 0
                assert int(image.get("height") or "0") > 0

    def test_brand_and_favicon_assets_exist_with_correct_metadata(self) -> None:
        assert self.markup.favicons
        for asset in self.markup.brand_images + self.markup.favicons:
            reference = asset.get("src") or asset.get("href") or ""
            with self.subTest(reference=reference):
                parsed = urlsplit(reference)
                assert parsed.scheme == ""
                assert parsed.netloc == ""
                assert parsed.path.startswith("/assets/branding/")
                path = WEB / parsed.path.lstrip("/")
                assert path.is_relative_to(WEB)
                assert path.is_file()
                if path.suffix == ".png":
                    data = path.read_bytes()
                    assert data[:8] == b"\x89PNG\r\n\x1a\n"
                    width, height = struct.unpack(">II", data[16:24])
                    if "width" in asset:
                        assert int(asset["width"] or "0") == width
                        assert int(asset["height"] or "0") == height
                    if "sizes" in asset:
                        assert asset["sizes"] == f"{width}x{height}"

    def test_svg_favicon_has_no_active_or_external_content(self) -> None:
        for asset in self.markup.favicons:
            reference = asset.get("href") or ""
            if not reference.endswith(".svg"):
                continue
            root = ElementTree.parse(WEB / reference.lstrip("/")).getroot()
            for element in root.iter():
                name = element.tag.rsplit("}", 1)[-1].lower()
                assert name not in {"script", "foreignobject", "iframe"}
                for attribute, value in element.attrib.items():
                    attribute_name = attribute.rsplit("}", 1)[-1].lower()
                    assert not attribute_name.startswith("on")
                    if attribute_name in {"href", "src"}:
                        assert value.startswith("#")
                    if "url(" in value:
                        assert value.startswith("url(#")


if __name__ == "__main__":
    unittest.main()
