from __future__ import annotations

import unittest

from standalone.gluetun_picker.runtime import ContainerRuntime


class RuntimeTests(unittest.TestCase):
    def test_dns_args_adds_public_resolvers(self) -> None:
        self.assertEqual(
            ContainerRuntime._dns_args(),
            ["--dns", "1.1.1.1", "--dns", "8.8.8.8"],
        )


if __name__ == "__main__":
    unittest.main()
