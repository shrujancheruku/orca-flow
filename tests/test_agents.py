import unittest

from flowlib import agents, config

from .helpers import cfg


class ProfileTest(unittest.TestCase):
    def test_a_bare_string_is_a_claude_model(self):
        self.assertEqual(agents.profile("Haiku", {"haiku": "claude-haiku-x"}),
                         {"name": "haiku", "agent": "claude", "model": "claude-haiku-x"})

    def test_an_object_names_its_agent(self):
        p = agents.profile("coder", {"coder": {"agent": "opencode", "model": "openrouter/x/y"}})
        self.assertEqual((p["agent"], p["model"]), ("opencode", "openrouter/x/y"))

    def test_unknown_or_empty_profiles_are_refused(self):
        with self.assertRaises(agents.AgentError):
            agents.profile("opus", {"haiku": "haiku"})
        self.assertTrue(agents.check_models({"coder": {"agent": "opencode"}}))
        self.assertTrue(agents.check_models({}))

    def test_the_default_config_routes_on_claude(self):
        self.assertEqual(agents.check_models(config.DEFAULTS["models"]), [])
        self.assertEqual(config.check(cfg()), [])

    def test_an_agent_without_a_runner_says_where_to_add_one(self):
        with self.assertRaisesRegex(agents.AgentError, "flowlib/agents.py"):
            agents.ask({"agent": "opencode", "model": "x"}, "hi", 1)
        self.assertIsNone(agents.transcript_root("opencode"))
        self.assertTrue(str(agents.transcript_root("claude")).endswith("projects"))


if __name__ == "__main__":
    unittest.main()
