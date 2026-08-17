"""Internal-DTD entity expansion: lossless on the good cases, loud on the bad."""
import sys, pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
from svg_entities import (expand_internal_entities, read_svg_bytes,
                          SvgEntityError)

ILLUSTRATOR = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" [
\t<!ENTITY ns_extend "http://ns.adobe.com/Extensibility/1.0/">
\t<!ENTITY ns_ai "http://ns.adobe.com/AdobeIllustrator/10.0/">
]>
<svg version="1.1" xmlns:x="&ns_extend;" xmlns:i="&ns_ai;"
     xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<rect width="10" height="10" fill="#123456"/>
</svg>
"""

PLAIN = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<rect width="10" height="10" fill="#abcdef"/><text>a &amp; b &lt; c</text>
</svg>
"""


def test_illustrator_entities_expand_and_subset_goes():
    out, info = expand_internal_entities(ILLUSTRATOR)
    assert "<!ENTITY" not in out
    assert "&ns_extend;" not in out and "&ns_ai;" not in out
    assert 'xmlns:x="http://ns.adobe.com/Extensibility/1.0/"' in out
    assert 'xmlns:i="http://ns.adobe.com/AdobeIllustrator/10.0/"' in out
    assert info["expanded"] == {"ns_extend": 1, "ns_ai": 1}
    assert info["removed_subset"] is True
    assert 'fill="#123456"' in out           # artwork untouched


def test_expanded_document_parses_under_defusedxml():
    """The actual acceptance criterion: cairosvg's parser must accept it."""
    defused = pytest.importorskip("defusedxml.ElementTree")
    out, _ = expand_internal_entities(ILLUSTRATOR)
    root = defused.fromstring(out)
    assert root.tag.endswith("svg")


def test_document_without_subset_is_untouched():
    out, info = expand_internal_entities(PLAIN)
    assert out == PLAIN
    assert info["expanded"] == {} and info["removed_subset"] is False


def test_xml_builtins_survive():
    out, _ = expand_internal_entities(PLAIN)
    assert "&amp;" in out and "&lt;" in out


def test_builtins_survive_alongside_a_subset():
    doc = ILLUSTRATOR.replace("<rect", "<text>x &amp; y</text><rect")
    out, _ = expand_internal_entities(doc)
    assert "&amp;" in out


def test_undeclared_entity_is_an_error_not_a_silent_strip():
    doc = ILLUSTRATOR.replace('xmlns:i="&ns_ai;"', 'xmlns:i="&ns_nope;"')
    with pytest.raises(SvgEntityError, match="undeclared"):
        expand_internal_entities(doc)


def test_external_entity_is_refused():
    doc = ILLUSTRATOR.replace(
        '<!ENTITY ns_ai "http://ns.adobe.com/AdobeIllustrator/10.0/">',
        '<!ENTITY ns_ai SYSTEM "file:///etc/passwd">')
    with pytest.raises(SvgEntityError, match="EXTERNAL"):
        expand_internal_entities(doc)


def test_billion_laughs_is_refused():
    doc = ('<!DOCTYPE svg [\n'
           '<!ENTITY a "aaaaaaaaaa">\n'
           '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">\n'
           '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">\n'
           '<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">\n'
           '<!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;">\n'
           ']>\n<svg><desc>&e;</desc></svg>\n')
    with pytest.raises(SvgEntityError, match="grew past"):
        expand_internal_entities(doc)


def test_parameter_entity_is_refused():
    doc = ('<!DOCTYPE svg [\n<!ENTITY % p "<!ENTITY q \'x\'>">\n%p;\n]>\n'
           '<svg/>\n')
    with pytest.raises(SvgEntityError, match="parameter entity"):
        expand_internal_entities(doc)


def test_bracket_inside_a_quoted_entity_value_does_not_end_the_subset():
    doc = ('<!DOCTYPE svg PUBLIC "x" "y" [\n'
           '<!ENTITY tricky "a]>b">\n'
           ']>\n<svg xmlns="http://www.w3.org/2000/svg"><desc>&tricky;</desc></svg>\n')
    out, info = expand_internal_entities(doc)
    assert "<!ENTITY" not in out
    assert "a]>b" in out
    assert info["expanded"] == {"tricky": 1}


def test_nested_entities_resolve():
    doc = ('<!DOCTYPE svg [\n<!ENTITY base "http://x/">\n'
           '<!ENTITY full "&base;ns/1.0/">\n]>\n'
           '<svg xmlns="http://www.w3.org/2000/svg" xmlns:z="&full;"/>\n')
    out, _ = expand_internal_entities(doc)
    assert 'xmlns:z="http://x/ns/1.0/"' in out


def test_read_svg_bytes_roundtrips_a_plain_file(tmp_path):
    p = tmp_path / "p.svg"
    p.write_text(PLAIN, encoding="utf-8")
    data, info = read_svg_bytes(p)
    assert data == PLAIN.encode("utf-8")
    assert info["removed_subset"] is False


def test_real_mfb_badges_rasterise():
    """End to end on the two assets that were blocked, if they are present."""
    cairosvg = pytest.importorskip("cairosvg")
    base = pathlib.Path(
        "/mnt/c/Users/prael/OneDrive - blockscale.solutions/Clients/Reckless "
        "Systems/Hardware Designs/1-ASIC Satoshi Starter/SatoshiStarter/"
        "ZIP - MFB Logos/Brand-Book-main/Badges/Nodes")
    if not base.is_dir():
        pytest.skip("MFB badge sources not mounted")
    import io
    from PIL import Image
    for stem in ("Node Badge_full node.svg", "Node Badge_light node.svg"):
        src = base / stem
        if not src.exists():
            pytest.skip(f"missing {stem}")
        data, info = read_svg_bytes(src)
        assert info["removed_subset"] is True, stem
        png = cairosvg.svg2png(bytestring=data, output_width=128, url=str(src))
        im = Image.open(io.BytesIO(png)).convert("RGBA")
        assert im.size[0] == 128
        # and it must not be a blank canvas
        assert im.getchannel("A").getextrema()[1] > 0, f"{stem} rendered empty"
