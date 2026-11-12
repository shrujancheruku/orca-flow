import json
import os
import unittest

from flowlib import config

from .helpers import cfg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(*parts):
    with open(os.path.join(ROOT, *parts)) as fh:
        return json.load(fh)


class ConfigTest(unittest.TestCase):
    def test_github_is_the_default_tracker(self):
        self.assertEqual(cfg()["tracker"], "github")

    def test_repo_is_required_and_shaped(self):
        with self.assertRaises(config.ConfigError):
            config.from_dict({})
        with self.assertRaises(config.ConfigError):
            config.from_dict({"github_repo": "nope"})

    def test_bad_tracker_and_duplicate_size_names(self):
        with self.assertRaises(config.ConfigError):
            cfg(tracker="jira")
        with self.assertRaises(config.ConfigError):
            cfg(labels={"size": {"S": "size", "M": "size", "L": "size:L"}})

    def test_linear_tracker_loads_but_core_scripts_refuse_it(self):
        c = cfg(tracker="linear")
        with self.assertRaises(config.ConfigError) as ctx:
            config.require_github(c)
        self.assertIn("adapters/linear", str(ctx.exception))

    def test_size_and_risk_from_labels(self):
        c = cfg(labels={"size": {"S": "s", "M": "m", "L": "l"}, "risk": "danger"})
        self.assertEqual(config.size_from_labels(c, ["x", "size:M"]), None)
        self.assertEqual(config.size_from_labels(c, ["m"]), "M")
        self.assertTrue(config.has_risk_label(c, ["Danger"]))

    def test_missing_config_file_is_its_own_error(self):
        with self.assertRaises(config.ConfigMissing):
            config.load("/nonexistent/flow.json")


class SchemaTest(unittest.TestCase):
    def test_schema_covers_every_config_key(self):
        props = load("schema", "flow.schema.json")["properties"]
        for key, value in config.DEFAULTS.items():
            self.assertIn(key, props)
            if isinstance(value, dict) and "properties" in props[key]:
                for sub in value:
                    self.assertIn(sub, props[key]["properties"], f"{key}.{sub}")
        for path in config.REQUIRED:
            self.assertIn(path[0], props)

    def test_example_loads_and_uses_only_schema_keys(self):
        raw = load("examples", "flow.json")
        props = load("schema", "flow.schema.json")["properties"]
        for key in raw:
            self.assertIn(key, props)
        config.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
