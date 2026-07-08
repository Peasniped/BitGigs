"""Allowlist SVG sanitizer — active/exfiltrating content must not survive."""
from django.test import SimpleTestCase

from core.utils import sanitize_svg


def _clean(svg: str) -> str:
    out = sanitize_svg(svg.encode("utf-8"))
    assert out is not None, "expected parseable SVG"
    return out.decode("utf-8")


class SanitizeSvgTest(SimpleTestCase):
    def test_benign_icon_survives(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<defs><linearGradient id="g"><stop offset="0" stop-color="#f00"/></linearGradient></defs>'
            '<path d="M2 2h20v20H2z" fill="url(#g)" stroke="#000" stroke-width="2"/>'
            '<circle cx="12" cy="12" r="4" fill="#00ff00" opacity="0.5"/>'
            "</svg>"
        )
        out = _clean(svg)
        self.assertIn("<path", out)
        self.assertIn('fill="url(#g)"', out)
        self.assertIn("linearGradient", out)
        self.assertIn("<circle", out)

    def test_script_element_removed(self):
        out = _clean('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><rect width="1" height="1"/></svg>')
        self.assertNotIn("script", out)
        self.assertNotIn("alert", out)
        self.assertIn("<rect", out)

    def test_event_handler_removed(self):
        out = _clean('<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect width="1" height="1" onclick="alert(2)"/></svg>')
        self.assertNotIn("onload", out)
        self.assertNotIn("onclick", out)

    def test_foreignobject_removed(self):
        out = _clean(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<foreignObject><body xmlns="http://www.w3.org/1999/xhtml" onload="alert(1)"/></foreignObject>'
            "</svg>"
        )
        self.assertNotIn("foreignObject", out)
        self.assertNotIn("body", out)

    def test_set_and_animate_attribute_injection_removed(self):
        out = _clean(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<a href="#x"><set attributeName="href" to="javascript:alert(1)"/>'
            '<animate attributeName="href" values="javascript:alert(1)"/></a>'
            "</svg>"
        )
        self.assertNotIn("set", out.replace("offset", ""))
        self.assertNotIn("animate", out)
        self.assertNotIn("javascript", out)

    def test_entity_encoded_javascript_href_removed(self):
        # &#106; == 'j' — the parser decodes it, so the decoded value is checked.
        out = _clean(
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
            '<use xlink:href="&#106;avascript:alert(1)"/>'
            "</svg>"
        )
        self.assertNotIn("javascript", out)

    def test_external_image_reference_removed(self):
        out = _clean(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<image href="https://evil.example/x.png" width="10" height="10"/>'
            '<use href="https://evil.example/x.svg#a"/>'
            "</svg>"
        )
        self.assertNotIn("image", out)
        self.assertNotIn("evil.example", out)

    def test_external_url_in_fill_and_style_removed(self):
        out = _clean(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<rect width="1" height="1" fill="url(https://evil.example/f)" style="fill:url(&quot;https://evil.example&quot;)"/>'
            '<style>@import url("https://evil.example/x.css");</style>'
            "</svg>"
        )
        self.assertNotIn("evil.example", out)
        self.assertNotIn("@import", out)

    def test_nested_tag_reassembly_does_not_survive(self):
        # A regex blocklist would strip the inner <script> and leave a working
        # outer one; the XML parser either rejects the file or the allowlist
        # drops the element — never a live script.
        out = sanitize_svg(
            b'<svg xmlns="http://www.w3.org/2000/svg"><scr<!-- -->ipt>alert(1)</scr<!-- -->ipt></svg>'
        )
        if out is not None:
            self.assertNotIn(b"script", out)
            self.assertNotIn(b"alert", out)

    def test_garbage_returns_none(self):
        self.assertIsNone(sanitize_svg(b"this is not xml <"))
        self.assertIsNone(sanitize_svg(b"<html><body>nope</body></html>"))

    def test_local_href_on_use_is_kept(self):
        out = _clean(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<defs><circle id="dot" r="2"/></defs><use href="#dot"/>'
            "</svg>"
        )
        self.assertIn('href="#dot"', out)
