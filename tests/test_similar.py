import unittest

from flowlib import estimating, similar

from .helpers import cfg


def case(number, title, body="", closed="2026-01-01", lines=100):
    return {"number": number, "title": title, "body": body, "closed_at": closed, "lines": lines, "files": 2}


class SimilarTest(unittest.TestCase):
    def setUp(self):
        self.index = similar.Index([
            case(1, "ci: cache the Go build in the backend job", "Touches .github/workflows/ci.yml"),
            case(2, "feat(mobile): a settings screen for notifications", "apps/mobile/src/screens"),
            case(3, "ci: run only the jobs a change affects", "scripts/ci-changes.sh and .github/workflows/ci.yml",
                 closed="2026-03-01"),
        ])

    def test_nearest_ranks_by_shared_words_and_paths(self):
        got = self.index.nearest("ci: speed up the backend job", "Edit .github/workflows/ci.yml", k=2)
        self.assertEqual([c["number"] for c in got][:1], [1])
        self.assertNotIn(2, [c["number"] for c in got])

    def test_exclude_and_before(self):
        got = self.index.nearest("ci jobs", "ci.yml", k=5, before="2026-02-01", exclude=1)
        self.assertEqual([c["number"] for c in got], [])

    def test_paths_count_their_prefixes(self):
        self.assertIn("apps/mobile", similar.tokens("see apps/mobile/src/a.ts"))


class ExamplesPromptTest(unittest.TestCase):
    def test_examples_only_in_their_style(self):
        issue = {"identifier": "#9", "title": "T", "description": "d"}
        ex = [case(1, "ci: cache the build", lines=120)]
        self.assertIn("#1 ci: cache the build: 120 lines, 2 files",
                      estimating.build_prompt(issue, cfg(), style="examples", examples=ex))
        self.assertNotIn("#1 ci", estimating.build_prompt(issue, cfg(), style="lines", examples=ex))

    def test_lines_prompt_is_unchanged_without_examples(self):
        # the {examples} slot is empty, so cached lines-style answers stay valid
        issue = {"identifier": "#9", "title": "T", "description": "d"}
        self.assertIn("null.\n\nTicket #9: T", estimating.build_prompt(issue, cfg(), style="lines"))

    def test_examples_answers_parse_like_lines(self):
        self.assertEqual(estimating.parse_answer('{"lines": 1500}', cfg(), style="examples")["size"], "L")


if __name__ == "__main__":
    unittest.main()
