import unittest

from aiops.serve import server_address


class ServerAddressTest(unittest.TestCase):
    def test_requires_environment_config_without_defaults(self):
        with self.assertRaises(RuntimeError):
            server_address({})

    def test_reads_validated_host_and_port(self):
        self.assertEqual(
            server_address({"AIOPS_API_BIND_HOST": "0.0.0.0", "AIOPS_API_BIND_PORT": "8080"}),
            ("0.0.0.0", 8080),
        )

    def test_rejects_invalid_port(self):
        with self.assertRaises(RuntimeError):
            server_address({"AIOPS_API_BIND_HOST": "127.0.0.1", "AIOPS_API_BIND_PORT": "70000"})


if __name__ == "__main__":
    unittest.main()
