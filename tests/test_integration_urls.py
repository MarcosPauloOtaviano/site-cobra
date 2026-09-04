import unittest
from pathlib import Path

from integration_urls import validated_https_url


class IntegrationUrlTests(unittest.TestCase):
    def test_accepts_https_management_url(self):
        self.assertEqual(
            validated_https_url(' https://gestao.exemplo.com/ '),
            'https://gestao.exemplo.com',
        )

    def test_rejects_non_https_and_credentials(self):
        self.assertIsNone(validated_https_url('http://gestao.exemplo.com'))
        self.assertIsNone(validated_https_url('https://user:pass@gestao.exemplo.com'))

    def test_external_management_link_is_isolated(self):
        template = (Path(__file__).parents[1] / 'templates' / 'index.html').read_text()
        self.assertIn('href="{{ escolinha_url }}"', template)
        self.assertIn('rel="noopener noreferrer"', template)


if __name__ == '__main__':
    unittest.main()
