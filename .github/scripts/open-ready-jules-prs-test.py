import sys
import unittest
from unittest.mock import patch
import io
import importlib.util
import importlib.machinery

class TestOpenReadyJulesPrs(unittest.TestCase):
    def setUp(self):
        # Load the script as a module
        loader = importlib.machinery.SourceFileLoader('open_ready_jules_prs', '.github/scripts/open-ready-jules-prs.py')
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.module = importlib.util.module_from_spec(spec)
        # Mock os.environ to prevent sys.exit(0) at module level
        with patch.dict('os.environ', {'GITHUB_API_TOKEN': 'dummy_token', 'GITHUB_REPOSITORY': 'test/repo', 'GITHUB_API_URL': 'https://api.github.com'}):
            loader.exec_module(self.module)

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_stale_branches_summary(self, mock_stdout):
        # Mock the request function
        def mock_request(method, path, body=None, ok=(200, 201, 204)):
            if method == "GET" and "matching-refs/heads" in path:
                return [
                    {"ref": "refs/heads/jules-stale-1", "object": {"sha": "sha1"}},
                    {"ref": "refs/heads/jules-stale-2", "object": {"sha": "sha2"}},
                    {"ref": "refs/heads/jules-fresh", "object": {"sha": "sha3"}},
                    {"ref": "refs/heads/not-jules", "object": {"sha": "sha4"}},
                ]
            elif method == "GET" and "pulls" in path:
                return [] # No open/closed PRs
            elif method == "GET" and "compare" in path:
                if "jules-stale-1" in path:
                    return {"behind_by": 5, "ahead_by": 0}
                elif "jules-stale-2" in path:
                    return {"behind_by": 10, "ahead_by": 0}
                elif "jules-fresh" in path:
                    return {"behind_by": 0, "ahead_by": 1, "commits": [{"sha": "commit1"}]}
            elif method == "POST" and "pulls" in path:
                return {"number": 123}
            elif method == "POST" and "labels" in path:
                return {}
            return None

        with patch.object(self.module, 'request', side_effect=mock_request):
            self.module.main()

        output = mock_stdout.getvalue()

        # Verify the stale summary is present and formatted correctly
        self.assertIn("Stale ready Jules branches skipped:", output)
        self.assertIn("- jules-stale-2 (behind by 10 commits)", output)
        self.assertIn("- jules-stale-1 (behind by 5 commits)", output)
        self.assertIn("Action required: Review these branches and either rebase them on master or delete them manually if no longer needed.", output)

        # Verify order (descending by behind_by)
        idx_2 = output.find("jules-stale-2")
        idx_1 = output.find("jules-stale-1")
        self.assertTrue(idx_2 < idx_1)

        # Verify a fresh branch still triggers a PR
        self.assertIn("Opened PR #123 for jules-fresh.", output)

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_no_stale_branches(self, mock_stdout):
        # Mock the request function
        def mock_request(method, path, body=None, ok=(200, 201, 204)):
            if method == "GET" and "matching-refs/heads" in path:
                return [
                    {"ref": "refs/heads/jules-fresh", "object": {"sha": "sha1"}},
                ]
            elif method == "GET" and "pulls" in path:
                return []
            elif method == "GET" and "compare" in path:
                if "jules-fresh" in path:
                    return {"behind_by": 0, "ahead_by": 1, "commits": [{"sha": "commit1"}]}
            elif method == "POST" and "pulls" in path:
                return {"number": 124}
            elif method == "POST" and "labels" in path:
                return {}
            return None

        with patch.object(self.module, 'request', side_effect=mock_request):
            self.module.main()

        output = mock_stdout.getvalue()

        # Verify no stale summary is printed
        self.assertNotIn("Stale ready Jules branches skipped:", output)
        self.assertIn("Opened PR #124 for jules-fresh.", output)

if __name__ == '__main__':
    unittest.main()
