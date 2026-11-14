import json
import unittest

from flowlib import backtest, config, estimating, github

from .helpers import cfg


def pr(number=10, files=None, changed=None, merged=True, closes=1):
    files = files if files is not None else [{"path": "src/a.py", "additions": 40, "deletions": 10}]
    return {
        "number": number, "merged": merged,
        "additions": sum(f["additions"] for f in files), "deletions": sum(f["deletions"] for f in files),
        "changedFiles": len(files) if changed is None else changed,
        "closingIssuesReferences": {"totalCount": closes},
        "files": {"nodes": files},
    }


def node(number=1, prs=None, reason="COMPLETED", labels=()):
    return {
        "number": number, "title": "T", "body": "b", "stateReason": reason,
        "labels": {"nodes": [{"name": l} for l in labels]},
        "closedByPullRequestsReferences": {"nodes": [pr()] if prs is None else prs},
    }


class CasesTest(unittest.TestCase):
    def test_only_one_merged_pr_closing_only_this_ticket_counts(self):
        nodes = [
            node(1),
            node(2, reason="NOT_PLANNED"),
            node(3, prs=[]),
            node(4, prs=[pr(), pr(11)]),
            node(5, prs=[pr(closes=2)]),
            node(6, prs=[pr(merged=False), pr(12)]),
        ]
        self.assertEqual([c["number"] for c in backtest.cases(nodes, cfg())], [1, 6])

    def test_generated_paths_are_left_out(self):
        files = [{"path": "src/a.py", "additions": 100, "deletions": 0},
                 {"path": "gen/api_pb.go", "additions": 5000, "deletions": 0}]
        c = backtest.cases([node(prs=[pr(files=files)])], cfg(generated_paths=["gen/**"]))[0]
        self.assertEqual((c["lines"], c["files"], c["generated_lines"], c["actual"]), (100, 1, 5000, "S"))

    def test_unlisted_files_count_in_full(self):
        m = backtest.measure(dict(pr(), changedFiles=150), cfg())
        self.assertTrue(m["truncated"])
        self.assertEqual(m["files"], 150)

    def test_label_size_is_read(self):
        self.assertEqual(backtest.cases([node(labels=["size:M"])], cfg())[0]["label_size"], "M")


class SizeAndScoreTest(unittest.TestCase):
    def test_bounds_are_inclusive(self):
        c = cfg(size_lines={"S": 50, "M": 400})
        self.assertEqual([backtest.actual_size(n, c) for n in (50, 51, 400, 401)], ["S", "M", "M", "L"])

    def test_score_counts_direction_and_far_misses(self):
        rows = [{"estimate": "S", "actual": "S"}, {"estimate": "S", "actual": "L"},
                {"estimate": "L", "actual": "M"}, {"estimate": None, "actual": "M"}]
        s = backtest.score(rows, "estimate")
        self.assertEqual((s["n"], s["exact"], s["under"], s["over"], s["far"]), (3, 1, 1, 1, 1))
        self.assertEqual(s["matrix"]["S"]["L"], 1)
        self.assertIn("Exact 1 (33%)", backtest.format_score("x", s))

    def test_bad_size_lines_are_refused(self):
        with self.assertRaises(config.ConfigError):
            cfg(size_lines={"S": 500, "M": 100})


class LinesStyleTest(unittest.TestCase):
    def test_prompt_asks_for_lines(self):
        prompt = estimating.build_prompt({"identifier": "#1", "title": "T", "description": "d"}, cfg(), style="lines")
        self.assertIn('"lines": <number>', prompt)
        self.assertNotIn("S|M|L", prompt)

    def test_size_comes_from_lines_and_size_lines(self):
        c = cfg(size_lines={"S": 100, "M": 500})
        a = estimating.parse_answer('{"lines": 120, "files": 3, "mostly": "code", "risk_kind": null, "reason": "r"}',
                                    c, style="lines")
        self.assertEqual((a["size"], a["lines"], a["files"]), ("M", 120, 3))
        self.assertEqual(estimating.parse_answer('{"lines": "80.5"}', c, style="lines")["size"], "S")

    def test_bad_lines_are_refused(self):
        for text in ('{"lines": "lots"}', '{"size": "S"}', '{"lines": -5}'):
            with self.assertRaises(ValueError):
                estimating.parse_answer(text, cfg(), style="lines")

    def test_lines_error(self):
        rows = [{"estimate_lines": 100, "lines": 100}, {"estimate_lines": 400, "lines": 100},
                {"estimate_lines": 60, "lines": 100}, {"lines": 5}]
        self.assertIn("within 2x of actual 2 of 3", backtest.format_lines_error(rows))


class GraphqlReadTest(unittest.TestCase):
    def test_a_query_is_a_read_and_a_mutation_is_not(self):
        self.assertTrue(github.is_read(["api", "graphql", "-f", "query=query { viewer { login } }", "-f", "x=1"]))
        self.assertFalse(github.is_read(["api", "graphql", "-f", "query= mutation { x }"]))
        self.assertFalse(github.is_read(["api", "graphql", "-X", "POST", "-f", "query=query { a }"]))

    def test_closed_with_prs_follows_pages(self):
        pages = iter([
            {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": True, "endCursor": "c1"}, "nodes": [1]}}}},
            {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [2]}}}},
        ])
        seen = []

        def runner(args, stdin=None):
            seen.append(args)
            return json.dumps(next(pages))

        self.assertEqual(github.Gh("a/b", runner=runner).closed_with_prs(), [1, 2])
        self.assertIn("cursor=c1", seen[1])


if __name__ == "__main__":
    unittest.main()
