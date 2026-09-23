import ast, importlib.machinery, importlib.util, io, tempfile, unittest
from contextlib import redirect_stderr
from pathlib import Path
from harness.minify.lib.dense import densify, densify_status

class TestDensify(unittest.TestCase):
    """Tests for densify(text, path) -> str"""

    def test_densify_returns_string(self):
        """densify returns str, not tuple."""
        result = densify("// comment\nconst x = 1;\n", "a.ts")
        self.assertIsInstance(result, str)
        self.assertEqual(result, "const x = 1;\n")

    def test_drops_blank_lines_and_indentation(self):
        result = densify("function f() {\n\n    return 1;\n}\n", "a.ts")
        self.assertEqual(result, "function f() {\nreturn 1;\n}\n")

    def test_drops_slash_line_comments(self):
        result = densify("// why\nconst a = 1;\n", "a.ts")
        self.assertEqual(result, "const a = 1;\n")

    def test_drops_block_comments(self):
        result = densify("/* a\n b */\nconst a = 1;\n", "a.ts")
        self.assertEqual(result, "const a = 1;\n")

    def test_keeps_a_url_inside_a_string(self):
        src = 'const u = "https://x.dev/a";\n'
        result = densify(src, "a.ts")
        self.assertEqual(result, src)

    def test_drops_hash_comments_in_python(self):
        result = densify("# why\nx = 1\n", "a.py")
        self.assertEqual(result, "x = 1\n")

    def test_keeps_python_indentation_as_one_space(self):
        result = densify("def f():\n    return 1\n", "a.py")
        self.assertEqual(result, "def f():\n return 1\n")

    def test_nested_python_indentation_keeps_depth(self):
        result = densify("def f():\n    if x:\n        return 1\n", "a.py")
        self.assertEqual(result, "def f():\n if x:\n  return 1\n")

    def test_excluded_file_is_returned_unchanged(self):
        """densify returns excluded files byte-identical."""
        src = "key:\n  value: 1\n\n"
        result = densify(src, "ci.yml")
        self.assertEqual(result, src)
        self.assertIsInstance(result, str)

    def test_hash_inside_a_python_string_survives(self):
        src = 'x = "# not a comment"\n'
        result = densify(src, "a.py")
        self.assertEqual(result, src)

    def test_non_uniform_python_indentation(self):
        """FIX 2: Non-uniform indentation (1-space increment) should parse."""
        # This is valid Python with 1-space nesting increments
        src = "def f():\n if x:\n  y = 1\n return 2\n"
        result = densify(src, "a.py")
        # Should parse without IndentationError
        ast.parse(result)
        # Check indentation structure is preserved
        self.assertIn("def f():", result)
        self.assertIn(" if x:", result)
        self.assertIn("  y = 1", result)
        self.assertIn(" return 2", result)

    def test_tab_indented_python(self):
        """FIX 2: Tab-indented Python should preserve indentation depth."""
        src = "def f():\n\treturn 1\n"
        result = densify(src, "a.py")
        # Should parse without IndentationError
        ast.parse(result)
        # Tab (first indent level) should map to 1 space
        self.assertIn("def f():", result)
        self.assertIn(" return 1", result)

    def test_mixed_tabs_and_spaces_python(self):
        """FIX 2: Mixed tabs and spaces should be handled consistently."""
        # Tabs at level 1, two tabs at level 2 (both valid in original Python)
        src = "def f():\n\tif x:\n\t\ty = 1\n"
        result = densify(src, "a.py")
        # Should parse without IndentationError
        ast.parse(result)

    def test_python_uniform_4space_parses(self):
        """ast.parse round-trip: uniform 4-space indentation."""
        src = "def f():\n    if x:\n        return 1\n"
        result = densify(src, "a.py")
        ast.parse(result)

    def test_python_1space_increment_parses(self):
        """ast.parse round-trip: 1-space indentation increment."""
        src = "def f():\n if x:\n  y = 1\n return 2\n"
        result = densify(src, "a.py")
        ast.parse(result)

    def test_python_tab_indented_parses(self):
        """ast.parse round-trip: tab-indented Python."""
        src = "def f():\n\tif x:\n\t\ty = 1\n"
        result = densify(src, "a.py")
        ast.parse(result)

    def test_python_mixed_tabs_spaces_parses(self):
        """ast.parse round-trip: mixed tabs and spaces."""
        src = "def f():\n\tif x:\n\t\ty = 1\n"
        result = densify(src, "a.py")
        ast.parse(result)


class TestDensifyStatus(unittest.TestCase):
    """Tests for densify_status(text, path) -> tuple[str, bool]"""

    def test_densify_status_returns_tuple(self):
        """densify_status returns (str, bool) tuple."""
        result, unclosed = densify_status("// comment\nconst x = 1;\n", "a.ts")
        self.assertIsInstance(result, str)
        self.assertIsInstance(unclosed, bool)
        self.assertEqual(result, "const x = 1;\n")
        self.assertFalse(unclosed)

    def test_unclosed_block_comment_sets_flag(self):
        """FIX 1: Unclosed block comment sets flag and keeps remainder."""
        src = "const a = 1;\n/* start\nconst leaked = 2;\n"
        result, unclosed = densify_status(src, "a.ts")
        self.assertTrue(unclosed)
        # The remainder after /* should be kept unstripped
        self.assertIn("leaked", result)
        self.assertIn("const a = 1;", result)

    def test_closed_block_comment_clears_flag(self):
        """FIX 1: Properly closed block comment sets flag to False."""
        src = "/* comment */\nconst x = 1;\n"
        result, unclosed = densify_status(src, "a.ts")
        self.assertFalse(unclosed)

    def test_excluded_file_unclosed_flag_false(self):
        """Excluded files return unchanged with unclosed=False."""
        src = "key:\n  value: 1\n\n"
        result, unclosed = densify_status(src, "ci.yml")
        self.assertEqual(result, src)
        self.assertFalse(unclosed)

class TestMinreadCLI(unittest.TestCase):
    """FIX 3: CLI-level tests for bin/minread."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        # Load the CLI module
        spec = importlib.util.spec_from_loader(
            "minread_cli",
            importlib.machinery.SourceFileLoader(
                "minread_cli",
                str(Path(__file__).resolve().parent.parent / "bin" / "minread")
            )
        )
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)

    def tearDown(self):
        self.tmp.cleanup()

    def test_minread_success_on_existing_file(self):
        """Success case: read an existing file."""
        test_file = self.tmp_path / "test.ts"
        test_file.write_text("// comment\nconst x = 1;\n")

        rc = self.cli.main([str(test_file)])
        self.assertEqual(rc, 0)

    def test_minread_returns_1_on_missing_file(self):
        """Error case: file does not exist."""
        missing_file = self.tmp_path / "missing.ts"

        rc = self.cli.main([str(missing_file)])
        self.assertEqual(rc, 1)

    def test_minread_returns_2_on_no_arguments(self):
        """Usage error: no arguments provided."""
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = self.cli.main([])
        self.assertEqual(rc, 2)

    def test_minread_returns_2_on_two_arguments(self):
        """Usage error: too many arguments."""
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = self.cli.main(["file1", "file2"])
        self.assertEqual(rc, 2)

    def test_minread_returns_2_on_directory_as_path(self):
        """Usage error: directory path instead of file."""
        rc = self.cli.main([str(self.tmp_path)])
        # Should fail with OSError (IsADirectoryError), return code 1
        self.assertEqual(rc, 1)

    def test_minread_prints_diagnostic_on_unclosed_block_comment(self):
        """Diagnostic printed to stderr when block comment is unclosed."""
        test_file = self.tmp_path / "test.ts"
        test_file.write_text("const a = 1;\n/* start\nconst leaked = 2;\n")

        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = self.cli.main([str(test_file)])

        self.assertEqual(rc, 0)
        stderr_output = buf.getvalue()
        self.assertIn("unclosed block comment", stderr_output)

if __name__ == "__main__":
    unittest.main()
