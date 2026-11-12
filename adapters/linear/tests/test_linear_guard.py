import unittest

from linearlib.linear import LinearClient, LinearError


class GuardTest(unittest.TestCase):
    def test_dry_run_records_and_never_sends(self):
        sent = []
        c = LinearClient("svc", apply=False, transport=lambda payload: sent.append(payload) or {"data": {}})
        out = c.mutate("issueCreate", "mutation { issueCreate { success } }", {"input": {}}, "make one")
        self.assertIsNone(out)
        self.assertEqual(sent, [])
        self.assertEqual([p.describe for p in c.planned], ["make one"])

    def test_query_refuses_a_mutation(self):
        c = LinearClient("svc", transport=lambda payload: {"data": {}})
        with self.assertRaises(LinearError):
            c.query("mutation { x }")

    def test_errors_carry_messages_only(self):
        c = LinearClient("svc", transport=lambda payload: {"errors": [{"message": "nope"}]})
        with self.assertRaises(LinearError) as ctx:
            c.query("{ viewer { id } }")
        self.assertEqual(str(ctx.exception), "Linear error: nope")


if __name__ == "__main__":
    unittest.main()
