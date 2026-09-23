import unittest
from harness.minify.lib.dense import densify

class TestDensify(unittest.TestCase):
    def test_drops_blank_lines_and_indentation(self):
        self.assertEqual(densify("function f() {\n\n    return 1;\n}\n", "a.ts"),
                         "function f() {\nreturn 1;\n}\n")

    def test_drops_slash_line_comments(self):
        self.assertEqual(densify("// why\nconst a = 1;\n", "a.ts"), "const a = 1;\n")

    def test_drops_block_comments(self):
        self.assertEqual(densify("/* a\n b */\nconst a = 1;\n", "a.ts"), "const a = 1;\n")

    def test_keeps_a_url_inside_a_string(self):
        src = 'const u = "https://x.dev/a";\n'
        self.assertEqual(densify(src, "a.ts"), src)

    def test_drops_hash_comments_in_python(self):
        self.assertEqual(densify("# why\nx = 1\n", "a.py"), "x = 1\n")

    def test_keeps_python_indentation_as_one_space(self):
        self.assertEqual(densify("def f():\n    return 1\n", "a.py"), "def f():\n return 1\n")

    def test_nested_python_indentation_keeps_depth(self):
        got = densify("def f():\n    if x:\n        return 1\n", "a.py")
        self.assertEqual(got, "def f():\n if x:\n  return 1\n")

    def test_excluded_file_is_returned_unchanged(self):
        src = "key:\n  value: 1\n\n"
        self.assertEqual(densify(src, "ci.yml"), src)

    def test_hash_inside_a_python_string_survives(self):
        src = 'x = "# not a comment"\n'
        self.assertEqual(densify(src, "a.py"), src)

if __name__ == "__main__":
    unittest.main()
