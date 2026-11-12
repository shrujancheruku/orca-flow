import json
import os
import unittest

from linearlib import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(*parts):
    with open(os.path.join(ROOT, *parts)) as fh:
        return json.load(fh)


class SchemaTest(unittest.TestCase):
    def test_schema_covers_every_config_key(self):
        props = load("schema", "linear.schema.json")["properties"]
        for key, value in config.DEFAULTS.items():
            self.assertIn(key, props)
            if isinstance(value, dict) and "properties" in props[key]:
                for sub in value:
                    self.assertIn(sub, props[key]["properties"], f"{key}.{sub}")
        for path in config.REQUIRED:
            self.assertIn(path[0], props)

    def test_examples_load(self):
        for name in os.listdir(os.path.join(ROOT, "examples")):
            raw = load("examples", name)
            props = load("schema", "linear.schema.json")["properties"]
            for key in raw:
                self.assertIn(key, props, f"{name}: {key}")
            config.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
