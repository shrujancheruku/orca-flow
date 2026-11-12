import unittest

from flowlib import proposals

from .helpers import cfg


class ProposalTest(unittest.TestCase):
    def issue(self, labs):
        return {"number": 7, "title": "T", "body": "", "labels": labs}

    def test_existing_label_is_copied_and_double_checked(self):
        ans = {"size": "L", "risk": False, "reason": "big"}
        p = proposals.make_proposal(self.issue(["size:M"]), cfg(), ans, [])
        self.assertEqual((p["size"], p["source"], p["agrees"], p["approved"]), ("M", "label", False, False))
        self.assertIn("label says M, Haiku says L", p["reason"])

    def test_no_label_takes_haiku(self):
        p = proposals.make_proposal(self.issue([]), cfg(), {"size": "S", "risk": True, "reason": "x"}, [])
        self.assertEqual((p["size"], p["source"], p["risk"], p["agrees"]), ("S", "haiku", True, None))

    def test_label_survives_a_failed_haiku_call(self):
        p = proposals.make_proposal(self.issue(["size:S", "risk"]), cfg(), None, [])
        self.assertEqual((p["size"], p["risk"]), ("S", True))
        with self.assertRaises(ValueError):
            proposals.make_proposal(self.issue([]), cfg(), None, [])

    def test_label_edits_swap_the_size_and_add_risk_once(self):
        p = {"size": "L", "risk": True}
        e = proposals.label_edits(p, cfg(), ["size:S", "bug"])
        self.assertEqual(e, {"add": ["size:L", "risk"], "remove": ["size:S"]})
        self.assertEqual(proposals.label_edits(p, cfg(), ["size:L", "risk"]), {"add": [], "remove": []})
        self.assertEqual(proposals.edit_args("acme/app", 7, e),
                         ["issue", "edit", "7", "--repo", "acme/app", "--add-label", "size:L",
                          "--add-label", "risk", "--remove-label", "size:S"])


if __name__ == "__main__":
    unittest.main()
