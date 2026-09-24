import unittest
from harness.minify.lib.classes import classify

class TestClassify(unittest.TestCase):
    def test_collapse_languages(self):
        for p in ["src/api.ts", "a/b.js", "x.mjs", "x.cjs", "s.css", "s.scss", "d.json", "i.svg"]:
            self.assertEqual(classify(p), "collapse", p)

    def test_dense_languages(self):
        for p in ["ui.tsx", "ui.jsx", "page.html", "sync.py", "run.sh", "run.bash", "q.sql"]:
            self.assertEqual(classify(p), "dense", p)

    def test_excluded_extensions(self):
        for p in ["README.md", "doc.mdx", "ci.yaml", "ci.yml", "pyproject.toml"]:
            self.assertEqual(classify(p), "exclude", p)

    def test_excluded_by_name(self):
        for p in ["Dockerfile", "a/Dockerfile", "package-lock.json", "uv.lock", "yarn.lock"]:
            self.assertEqual(classify(p), "exclude", p)

    def test_excluded_by_glob(self):
        for p in ["docker-compose.yml", "docker-compose.prod.yml", ".env", ".env.local",
                  "db/migrations/001_init.sql", "app/migrations/x.py"]:
            self.assertEqual(classify(p), "exclude", p)

    def test_unknown_extension_is_excluded(self):
        self.assertEqual(classify("image.png"), "exclude")
        self.assertEqual(classify("noext"), "exclude")

    def test_lockfile_beats_collapse_extension(self):
        # package-lock.json is .json, which is collapse-class; the name rule must win
        self.assertEqual(classify("package-lock.json"), "exclude")

    def test_migration_beats_dense_extension(self):
        self.assertEqual(classify("app/migrations/0002_add.py"), "exclude")

if __name__ == "__main__":
    unittest.main()
