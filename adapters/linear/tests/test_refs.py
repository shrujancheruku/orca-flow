import unittest

from linearlib import refs

REPO = "acme/app"
TABLE = {
    42: {"kind": "issue", "label": "ABC-7", "url": "https://linear.app/acme/issue/ABC-7"},
    1: {"kind": "project", "label": "The app", "url": "https://linear.app/acme/project/the-app-1"},
}
PRS = {50}


def rw(text):
    return refs.rewrite_text(text, REPO, TABLE, PRS)


class RewriteTest(unittest.TestCase):
    def test_bare_issue_number(self):
        self.assertEqual(rw("See #42.").text, "See ABC-7.")

    def test_parenthesised_number(self):
        self.assertEqual(rw("done (#42)").text, "done (ABC-7)")

    def test_markdown_link_to_issue(self):
        out = rw("[#42](https://github.com/acme/app/issues/42)").text
        self.assertEqual(out, "[ABC-7](https://linear.app/acme/issue/ABC-7)")

    def test_link_with_other_text_keeps_text(self):
        out = rw("[the ticket](https://github.com/acme/app/issues/42)").text
        self.assertEqual(out, "[the ticket](https://linear.app/acme/issue/ABC-7)")

    def test_bare_issue_url(self):
        self.assertEqual(rw("at https://github.com/acme/app/issues/42 now").text,
                         "at https://linear.app/acme/issue/ABC-7 now")

    def test_cross_repo_form(self):
        self.assertEqual(rw("acme/app#42").text, "ABC-7")

    def test_map_number_links_to_the_project(self):
        self.assertEqual(rw("Map #1").text, "Map [The app](https://linear.app/acme/project/the-app-1)")

    def test_pr_numbers_are_left_and_reported(self):
        res = rw("Fixed in #50 and https://github.com/acme/app/pull/42.")
        self.assertEqual(res.text, "Fixed in #50 and https://github.com/acme/app/pull/42.")
        self.assertEqual(sorted(res.left_pr), [42, 50])
        self.assertFalse(res.changed)

    def test_unknown_numbers_are_flagged(self):
        res = rw("See #999")
        self.assertEqual(res.text, "See #999")
        self.assertEqual(res.flagged, [(999, "#999")])

    def test_code_is_untouched(self):
        text = "Use `#42` like this.\n```\n#42\n```\nBut #42 here."
        self.assertEqual(rw(text).text, "Use `#42` like this.\n```\n#42\n```\nBut ABC-7 here.")

    def test_hex_colours_entities_and_anchors_are_untouched(self):
        for text in ("color #42aa00", "&#42;", "[up](#42)", "page#42", "a/#42"):
            self.assertEqual(rw(text).text, text, text)

    def test_other_repos_are_untouched(self):
        text = "https://github.com/other/app/issues/42 and other/app#42"
        self.assertEqual(rw(text).text, text)

    def test_rewriting_twice_changes_nothing_more(self):
        once = rw("See #42 and [#1](https://github.com/acme/app/issues/1)").text
        self.assertEqual(rw(once).text, once)

    def test_binary_sniff(self):
        self.assertTrue(refs.is_binary(b"PNG\0\0"))
        self.assertFalse(refs.is_binary(b"# Title"))


if __name__ == "__main__":
    unittest.main()


class ProvenanceTest(unittest.TestCase):
    def test_footer_keeps_its_github_link(self):
        text = "Blocked by #42.\n\n_Moved from GitHub https://github.com/acme/app/issues/42, opened by @a._"
        out = refs.rewrite_keeping(text, "tail", REPO, TABLE, PRS)
        self.assertEqual(out.text, "Blocked by ABC-7.\n\n_Moved from GitHub https://github.com/acme/app/issues/42, opened by @a._")

    def test_comment_head_keeps_its_original_link(self):
        text = "**@a** on GitHub ([original](https://github.com/acme/app/issues/42#issuecomment-1)):\n\nSee #42."
        out = refs.rewrite_keeping(text, "head", REPO, TABLE, PRS)
        self.assertTrue(out.text.startswith("**@a** on GitHub ([original](https://github.com/acme/app/issues/42#issuecomment-1))"))
        self.assertTrue(out.text.endswith("See ABC-7."))
