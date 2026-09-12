"""Test suite for the Localization QA agent.

Run:  python -m unittest discover -s tests -v
No third-party dependencies, no network, no API key needed.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lqa.glossary import check_glossary, load_glossary, required_targets  # noqa: E402
from lqa.providers import HeuristicProvider, heuristic_review  # noqa: E402
from lqa.report import to_json, to_markdown  # noqa: E402
from lqa.reviewer import Segment, review_document, review_segment, score_from_issues  # noqa: E402

GLOSSARY_CSV = """source,target,note
cont curent,current account,Banking
termen de valabilitate,expiry date,Payment
notificare push,push notification,UI
"""


class TestGlossary(unittest.TestCase):
    def test_loads_header_csv(self):
        g = load_glossary(GLOSSARY_CSV)
        self.assertEqual(len(g), 3)
        self.assertEqual(g["cont curent"].target, "current account")
        self.assertEqual(g["cont curent"].note, "Banking")

    def test_handles_semicolon_delimiter(self):
        g = load_glossary("source;target\ncont curent;current account\n")
        self.assertEqual(g["cont curent"].target, "current account")

    def test_positional_without_header(self):
        g = load_glossary("cont curent,current account\n")
        self.assertIn("cont curent", g)

    def test_empty_input_is_empty_dict(self):
        self.assertEqual(load_glossary(""), {})

    def test_required_targets_only_when_source_present(self):
        g = load_glossary(GLOSSARY_CSV)
        req = required_targets(g, "Soldul contului curent este zero.")
        self.assertIn("current account", req)
        self.assertNotIn("push notification", req)

    def test_violation_detected(self):
        g = load_glossary(GLOSSARY_CSV)
        v = check_glossary(g, "Soldul contului curent", "Your checking balance")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["expected"], "current account")
        self.assertEqual(v[0]["severity"], "high")

    def test_no_violation_when_term_present(self):
        g = load_glossary(GLOSSARY_CSV)
        self.assertEqual(check_glossary(g, "cont curent", "your current account"), [])


class TestHeuristics(unittest.TestCase):
    def test_ro_leakage_flagged(self):
        r = heuristic_review(
            "Pentru mai multe informații contactați echipa noastră",
            "For more information va rugam contactati echipa noastra",
            "ro", "en", [])
        kinds = {i["kind"] for i in r["issues"]}
        self.assertIn("untranslated", kinds)

    def test_omission_flagged(self):
        r = heuristic_review(
            "Dacă întâmpinați probleme la efectuarea plății verificați termenul de valabilitate al cardului",
            "Try again.",
            "ro", "en", [])
        self.assertIn("omission", {i["kind"] for i in r["issues"]})

    def test_empty_target_flagged(self):
        r = heuristic_review("ceva", "   ", "ro", "en", [])
        self.assertIn("empty", {i["kind"] for i in r["issues"]})

    def test_duplicated_word_flagged(self):
        r = heuristic_review("Accesați setările", "Go to the the settings", "ro", "en", [])
        self.assertIn("fluency", {i["kind"] for i in r["issues"]})

    def test_unbalanced_bracket_flagged(self):
        r = heuristic_review("Accesați setările (Setări)", "Go to settings (Settings", "ro", "en", [])
        self.assertIn("formatting", {i["kind"] for i in r["issues"]})

    def test_missing_required_term_flagged(self):
        r = heuristic_review("cont curent", "your balance", "ro", "en", ["current account"])
        self.assertIn("terminology", {i["kind"] for i in r["issues"]})

    def test_clean_segment_yields_no_issues(self):
        r = heuristic_review(
            "Vă rugăm să vă autentificați pentru a continua.",
            "Please sign in to continue.",
            "ro", "en", [])
        self.assertEqual(r["issues"], [])


class TestScoring(unittest.TestCase):
    def test_clean_scores_100(self):
        self.assertEqual(score_from_issues([]), 100.0)

    def test_penalty_never_below_zero(self):
        issues = [{"kind": "empty", "severity": "high"}] * 20
        self.assertEqual(score_from_issues(issues), 0.0)

    def test_high_severity_costs_more_than_low(self):
        high = score_from_issues([{"kind": "terminology", "severity": "high"}])
        low = score_from_issues([{"kind": "fluency", "severity": "low"}])
        self.assertLess(high, low)


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.g = load_glossary(GLOSSARY_CSV)
        self.p = HeuristicProvider()

    def test_clean_segment_passes(self):
        seg = Segment("s1", "Vă rugăm să vă autentificați.", "Please sign in to continue.")
        res = review_segment(self.p, seg, self.g)
        self.assertEqual(res.status, "pass")
        self.assertEqual(res.score, 100.0)

    def test_glossary_violation_blocks(self):
        seg = Segment("s2", "Soldul contului curent este disponibil.",
                      "Your checking account balance is available.")
        res = review_segment(self.p, seg, self.g)
        self.assertEqual(res.status, "block")
        self.assertTrue(any(i["kind"] == "terminology" for i in res.issues))

    def test_document_report_shape(self):
        segs = [
            Segment("a", "Vă rugăm să vă autentificați.", "Please sign in."),
            Segment("b", "Soldul contului curent este zero.", "Your checking balance is zero."),
        ]
        rep = review_document(self.p, segs, self.g)
        self.assertEqual(len(rep.segments), 2)
        self.assertEqual(rep.counts["block"], 1)
        self.assertLess(rep.score, 100.0)
        self.assertIn("score", rep.to_dict())

    def test_markdown_and_json_render(self):
        segs = [Segment("a", "Soldul contului curent", "Your checking balance")]
        rep = review_document(self.p, segs, self.g)
        md = to_markdown(rep)
        self.assertIn("Localization QA Report", md)
        self.assertIn("BLOCK", md)
        parsed = json.loads(to_json(rep))
        self.assertEqual(parsed["segments"][0]["id"], "a")

    def test_use_model_false_still_reviews(self):
        segs = [Segment("a", "Soldul contului curent", "Your checking balance")]
        rep = review_document(self.p, segs, self.g, use_model=False)
        self.assertTrue(rep.segments[0].issues)

    def test_terminology_reported_once_not_twice(self):
        """The authoritative checker and the model layer both see the missing
        term; it must be charged to the score only once."""
        seg = Segment("s", "Soldul contului curent este disponibil.",
                      "Your checking account balance is available.")
        res = review_segment(self.p, seg, self.g)
        term_issues = [i for i in res.issues if i["kind"] == "terminology"]
        self.assertEqual(len(term_issues), 1, f"expected 1, got {term_issues}")

    def test_inflected_glossary_term_is_detected(self):
        """Romanian inflects: 'cont curent' must match inside 'contului curent'."""
        seg = Segment("s", "Soldul contului curent este zero.",
                      "Your balance is zero.")
        res = review_segment(self.p, seg, self.g)
        self.assertTrue(any(i["kind"] == "terminology" for i in res.issues))

    def test_glossary_does_not_overmatch_unrelated_words(self):
        """'cont' must not match 'contact'."""
        from lqa.glossary import term_present
        self.assertFalse(term_present("cont", "please contact us"))
        self.assertTrue(term_present("cont", "soldul contului"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
