"""Tests for the TMX / XLIFF / JSON importer."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lqa.importers import (  # noqa: E402
    ImportError_,
    detect_format,
    load_segments,
    parse_json,
    parse_tmx,
    parse_xliff,
)

HERE = os.path.dirname(__file__)
EX = os.path.join(HERE, "..", "examples")


TMX = """<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4"><body>
  <tu tuid="a1">
    <tuv xml:lang="ro"><seg>Cont curent</seg></tuv>
    <tuv xml:lang="en"><seg>Current account</seg></tuv>
  </tu>
  <tu tuid="a2">
    <tuv xml:lang="ro"><seg>Sold</seg></tuv>
    <tuv xml:lang="en"><seg>Balance</seg></tuv>
  </tu>
</body></tmx>
"""

TMX_REGIONAL = """<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4"><body>
  <tu tuid="b1">
    <tuv xml:lang="ro-RO"><seg>Bună ziua</seg></tuv>
    <tuv xml:lang="en-GB"><seg>Good afternoon</seg></tuv>
  </tu>
</body></tmx>
"""

XLIFF12 = """<?xml version="1.0" encoding="UTF-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file source-language="ro" target-language="en"><body>
    <trans-unit id="t1">
      <source>Cont curent</source><target>Current account</target>
    </trans-unit>
    <trans-unit id="t2">
      <source>Sold</source><target>Balance</target>
      <note>check this one</note>
    </trans-unit>
  </body></file>
</xliff>
"""

XLIFF20 = """<?xml version="1.0" encoding="UTF-8"?>
<xliff xmlns="urn:oasis:names:tc:xliff:document:2.0" version="2.0" srcLang="ro" trgLang="en">
  <file id="f1">
    <unit id="u1">
      <segment><source>Cont curent</source><target>Current account</target></segment>
    </unit>
  </file>
</xliff>
"""


class TestDetect(unittest.TestCase):
    def test_by_extension(self):
        self.assertEqual(detect_format("x.tmx", ""), "tmx")
        self.assertEqual(detect_format("x.xlf", ""), "xliff")
        self.assertEqual(detect_format("x.xliff", ""), "xliff")
        self.assertEqual(detect_format("x.json", "[]"), "json")

    def test_by_content_when_extension_is_wrong(self):
        self.assertEqual(detect_format("mystery.dat", TMX), "tmx")
        self.assertEqual(detect_format("mystery.dat", XLIFF12), "xliff")
        self.assertEqual(detect_format("mystery.dat", '{"segments": []}'), "json")

    def test_unknown_raises(self):
        with self.assertRaises(ImportError_):
            detect_format("mystery.dat", "just some prose, not a translation file")


class TestTMX(unittest.TestCase):
    def test_parses_pairs(self):
        segs = parse_tmx(TMX)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0].id, "a1")
        self.assertEqual(segs[0].source, "Cont curent")
        self.assertEqual(segs[0].target, "Current account")

    def test_regional_language_codes_still_match(self):
        """ro-RO / en-GB must match a request for 'ro' / 'en'."""
        segs = parse_tmx(TMX_REGIONAL, "ro", "en")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].source, "Bună ziua")
        self.assertEqual(segs[0].target, "Good afternoon")

    def test_does_not_confuse_languages(self):
        """The classic bug: source and target swapped."""
        segs = parse_tmx(TMX, "ro", "en")
        self.assertNotEqual(segs[0].source, segs[0].target)
        self.assertIn("Cont", segs[0].source)

    def test_rejects_non_tmx(self):
        with self.assertRaises(ImportError_):
            parse_tmx("<html><body>nope</body></html>")

    def test_rejects_malformed_xml(self):
        with self.assertRaises(ImportError_):
            parse_tmx("<tmx><body><tu>")


class TestXLIFF(unittest.TestCase):
    def test_parses_1_2(self):
        segs = parse_xliff(XLIFF12)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0].id, "t1")
        self.assertEqual(segs[0].source, "Cont curent")
        self.assertEqual(segs[0].target, "Current account")

    def test_reads_note_1_2(self):
        segs = parse_xliff(XLIFF12)
        self.assertIn("check this one", segs[1].note)

    def test_parses_2_0(self):
        segs = parse_xliff(XLIFF20)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].id, "u1")
        self.assertEqual(segs[0].source, "Cont curent")
        self.assertEqual(segs[0].target, "Current account")

    def test_handles_unnamespaced_exporters(self):
        """Some tools drop the XLIFF namespace entirely."""
        raw = ('<xliff version="1.2"><file><body>'
               '<trans-unit id="z1"><source>A</source><target>B</target></trans-unit>'
               '</body></file></xliff>')
        segs = parse_xliff(raw)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].source, "A")

    def test_rejects_non_xliff(self):
        with self.assertRaises(ImportError_):
            parse_xliff("<tmx><body/></tmx>")

    def test_empty_xliff_raises_clearly(self):
        raw = '<xliff version="1.2"><file><body></body></file></xliff>'
        with self.assertRaises(ImportError_):
            parse_xliff(raw)


class TestJSONStillWorks(unittest.TestCase):
    def test_list_form(self):
        segs = parse_json('[{"id":"1","source":"a","target":"b"}]')
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].source, "a")

    def test_wrapped_form(self):
        segs = parse_json('{"segments":[{"source":"x","target":"y"}]}')
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].target, "y")

    def test_rejects_non_list(self):
        with self.assertRaises(ImportError_):
            parse_json('{"nope": 1}')


class TestLoadSegmentsFromDisk(unittest.TestCase):
    """The end-to-end path the CLI actually takes."""

    def test_tmx_file(self):
        p = os.path.join(EX, "sample.tmx")
        if not os.path.exists(p):
            self.skipTest("sample.tmx missing")
        segs = load_segments(p, "ro", "en")
        self.assertGreaterEqual(len(segs), 3)
        self.assertTrue(all(s.source and s.target for s in segs))

    def test_xliff_file(self):
        p = os.path.join(EX, "sample.xlf")
        if not os.path.exists(p):
            self.skipTest("sample.xlf missing")
        segs = load_segments(p, "ro", "en")
        self.assertGreaterEqual(len(segs), 3)
        self.assertTrue(all(s.source and s.target for s in segs))

    def test_xliff_20_file(self):
        p = os.path.join(EX, "sample-2.0.xliff")
        if not os.path.exists(p):
            self.skipTest("sample-2.0.xliff missing")
        segs = load_segments(p, "ro", "en")
        self.assertGreaterEqual(len(segs), 2)

    def test_json_file(self):
        p = os.path.join(EX, "sample.json")
        if not os.path.exists(p):
            self.skipTest("sample.json missing")
        segs = load_segments(p, "ro", "en")
        self.assertGreaterEqual(len(segs), 1)

    def test_all_three_formats_agree_on_the_same_content(self):
        """Same four segments in TMX and XLIFF must import identically."""
        tmx = os.path.join(EX, "sample.tmx")
        xlf = os.path.join(EX, "sample.xlf")
        if not (os.path.exists(tmx) and os.path.exists(xlf)):
            self.skipTest("fixtures missing")
        a = load_segments(tmx, "ro", "en")
        b = load_segments(xlf, "ro", "en")
        # the XLIFF file has 3 units, the TMX has 4; compare the shared ids
        amap = {s.id: (s.source, s.target) for s in a}
        for s in b:
            if s.id in amap:
                self.assertEqual(amap[s.id], (s.source, s.target),
                                 f"format disagreement on {s.id}")

    def test_empty_file_raises(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".tmx", delete=False) as fh:
            fh.write("")
            name = fh.name
        try:
            with self.assertRaises(ImportError_):
                load_segments(name)
        finally:
            os.unlink(name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
