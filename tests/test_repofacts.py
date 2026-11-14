import unittest

from flowlib import estimating, repofacts

from .helpers import cfg


class Tree:
    lines = {"apps/mobile/src/app/(tabs)/index.tsx": 300, "apps/mobile/src/app/crew/[id].tsx": 200,
             "apps/mobile/src/components/screen-frame.tsx": 50}

    def files_with(self, name):
        return {"ScreenFrame": ["a.tsx", "b.tsx", "c.tsx"]}.get(name, [])


class RepoFactsTest(unittest.TestCase):
    def test_mentions_strip_line_refs_and_skip_commands(self):
        got = repofacts.mentions("See `app/(tabs)/index.tsx:64-76`, `npx expo lint` and backend/internal/plans/x.go.")
        self.assertEqual(got, ["app/(tabs)/index.tsx", "backend/internal/plans/x.go"])

    def test_links_are_not_paths(self):
        self.assertEqual(repofacts.mentions("[#155](https://github.com/a/b/issues/155)"), [])

    def test_paths_match_from_any_directory_down(self):
        self.assertEqual(repofacts.lookup_path("src/app", Tree.lines), (2, 500))
        self.assertEqual(repofacts.lookup_path("screen-frame.tsx", Tree.lines), (1, 50))
        self.assertEqual(repofacts.lookup_path("apps/mobile/**/*.tsx", Tree.lines), (3, 550))

    def test_facts(self):
        got = repofacts.facts("Every screen is a `ScreenFrame`; add `NewThing` in `src/app` and `docs/new.md`.", Tree())
        self.assertEqual(got, ["`ScreenFrame`: used in 3 file(s)", "`NewThing`: not in the repo yet",
                               "`src/app`: 2 file(s), 500 lines", "`docs/new.md`: not in the repo yet"])

    def test_facts_only_in_their_style(self):
        issue = {"identifier": "#9", "title": "T", "description": "d"}
        self.assertIn("- `X`: used in 3 file(s)", estimating.build_prompt(issue, cfg(), style="facts",
                                                                         facts=["`X`: used in 3 file(s)"]))
        self.assertNotIn("used in", estimating.build_prompt(issue, cfg(), style="lines", facts=["`X`: used in"]))


if __name__ == "__main__":
    unittest.main()
