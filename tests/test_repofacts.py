import unittest

from flowlib import backtest, estimating, repofacts, routing

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


class RiskTree:
    lines = {"backend/internal/identity/service.go": 100, "backend/internal/plans/handler.go": 80,
             "backend/internal/identity/handler.go": 90, "backend/internal/chat/handler.go": 70,
             "apps/web/wrangler.jsonc": 20}

    def files_with(self, name):
        return {"Standing": ["backend/internal/identity/service.go"],
                "Handler": ["backend/internal/plans/handler.go", "backend/internal/chat/handler.go",
                            "backend/internal/identity/handler.go"]}.get(name, [])


RISK = cfg(risk_paths=["backend/internal/identity/**", "config/**", "apps/*/wrangler.jsonc"])


class RiskPathsTest(unittest.TestCase):
    def risk(self, text):
        return repofacts.risk_paths(text, RiskTree(), RISK)

    def test_one_word_directories_must_start_a_path(self):
        self.assertEqual(self.risk("Read the config at startup."), [])
        self.assertEqual(self.risk("Edit config/deploy.yml."), ["path config/**"])

    def test_a_glob_needs_a_matching_path(self):
        self.assertEqual(self.risk("Every file under apps/mobile/src."), [])
        self.assertEqual(self.risk("Bump apps/web/wrangler.jsonc."), ["path apps/*/wrangler.jsonc"])

    def test_short_paths_new_files_and_names_resolve(self):
        self.assertEqual(self.risk("Change `identity/service.go`."),
                         ["names identity/service.go under backend/internal/identity/**"])
        self.assertEqual(self.risk("Add `identity/standing.go`."),
                         ["adds identity/standing.go under backend/internal/identity/**"])
        self.assertEqual(self.risk("Read `Standing` in the gate."),
                         ["uses Standing under backend/internal/identity/**"])

    def test_names_mostly_elsewhere_do_not_count(self):
        self.assertEqual(self.risk("Every `Handler` and `handler.go` returns errs."), [])

    def test_routing_resolves_paths_with_a_tree(self):
        f = routing.ticket_facts(RISK, ["size:S"], "", ["identity/x.go"], tree=RiskTree())
        self.assertTrue(f["risk"])
        self.assertFalse(routing.ticket_facts(RISK, ["size:S"], "", ["identity/x.go"])["risk"])


class RiskScoreTest(unittest.TestCase):
    def test_touched_and_score(self):
        self.assertEqual(backtest.touched_risk(["config/a.yml", "src/x.py"], RISK), ["config/**"])
        rows = [{"risk_paths": ["p"], "risk_touched": ["config/**"]}, {"risk_paths": [], "risk_touched": ["x"]},
                {"risk_paths": ["p"], "risk_touched": []}, {"risk_paths": [], "risk_touched": []}]
        s = backtest.risk_score(rows, "risk_paths")
        self.assertEqual((s["risky"], s["caught"], s["missed"], s["false"]), (2, 1, 1, 1))


if __name__ == "__main__":
    unittest.main()
