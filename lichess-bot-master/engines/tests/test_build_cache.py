"""Cache correctness checks; fixtures are data, never native executables."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Kernels"))
import build_cache as cache


class BuildCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mrbits-cache-")
        self.root = Path(self.temporary.name) / "engines"
        self.root.mkdir()
        self.source = self.root / "Kernel.cpp"
        self.source.write_text('#include "shared.hpp"\nint main(){}\n')
        (self.root / "shared.hpp").write_text("// fixture\n")
        self.executable = self.root / "Kernel.exe"
        self.executable.write_bytes(b"old executable data fixture, not executable code")
        self.compiler = self.root.parent / "fake compiler"
        self.compiler.write_bytes(b"compiler identity fixture")
        self.inputs = cache.dependency_inputs(self.source, self.root)
        self.recipe = cache.recipe(self.source, self.root, compiler=str(self.compiler))
        self.old = {
            "schema": "mrbits.local-build.v1", "label": "original",
            "stamp": "original-fixture-20261104T000000Z", "inputs": dict(self.inputs),
            "builder_sha256": "historical helper hash", "origin": "local_compilation",
            "executable_sha256": hashlib.sha256(self.executable.read_bytes()).hexdigest(),
            "command": [str(self.compiler), "-std=c++17", "-O2",
                        '-DMRBITS_BUILD_STAMP="original-fixture-20261104T000000Z"',
                        "-I", str(self.root), str(self.source), "-o",
                        str(self.executable.with_name("Kernel.building.exe"))],
        }

    def tearDown(self):
        self.temporary.cleanup()

    def valid(self, previous, *, inputs=None, recipe=None):
        return cache.validate_receipt(previous, inputs or self.inputs, recipe or self.recipe,
                                      self.executable, source=self.source, engines=self.root)

    def test_transitive_all_branch_and_cycle_dependencies(self):
        (self.root / "shared.hpp").write_text('#if 0\n#include "nested.hpp"\n#endif\n')
        (self.root / "nested.hpp").write_text('#include "shared.hpp"\n')
        self.assertEqual(set(cache.dependency_inputs(self.source, self.root)),
                         {"Kernel.cpp", "shared.hpp", "nested.hpp"})

    def test_unrelated_headers_do_not_change_inputs(self):
        (self.root / "unrelated.hpp").write_text("not included")
        self.assertEqual(cache.dependency_inputs(self.source, self.root), self.inputs)

    def test_transitive_edit_invalidates_existing_receipt(self):
        value = cache.upgraded_receipt(self.old, self.inputs, self.recipe)
        (self.root / "shared.hpp").write_text("// changed real dependency")
        new_inputs = cache.dependency_inputs(self.source, self.root)
        self.assertFalse(self.valid(value, inputs=new_inputs))

    def test_relative_include_precedes_root_include(self):
        folder = self.root / "sub"; folder.mkdir()
        (folder / "one.hpp").write_text('#include "same.hpp"\n')
        (folder / "same.hpp").write_text("// correct local dependency")
        (self.root / "same.hpp").write_text("// shadowed root dependency")
        self.source.write_text('#include "sub/one.hpp"\n')
        found = cache.dependency_inputs(self.source, self.root)
        self.assertIn("sub/same.hpp", found)
        self.assertNotIn("same.hpp", found)

    def test_comments_and_raw_literals_are_not_dependencies(self):
        self.source.write_text('/*\n#include "missing.hpp"\n*/\n'
                               'const char* x = R"tag(\n#include "also_missing.hpp"\n)tag";\n'
                               '#include /* why */ "shared.hpp" // okay\n')
        self.assertEqual(set(cache.dependency_inputs(self.source, self.root)), {"Kernel.cpp", "shared.hpp"})

    def test_dynamic_and_missing_includes_fail_conservatively(self):
        for text, error in [('#include HEADER\n', ValueError),
                            ('#include_next "shared.hpp"\n', ValueError),
                            ('#if 0\n#include "missing.hpp"\n#endif\n', FileNotFoundError)]:
            with self.subTest(text=text):
                self.source.write_text(text)
                with self.assertRaises(error): cache.dependency_inputs(self.source, self.root)

    def test_escape_rejected(self):
        (self.root.parent / "outside.hpp").write_text("// outside")
        self.source.write_text('#include "../outside.hpp"\n')
        with self.assertRaises(ValueError): cache.dependency_inputs(self.source, self.root)

    def test_source_escape_rejected(self):
        outside = self.root.parent / "outside.cpp"; outside.write_text("int main(){}")
        with self.assertRaises(ValueError): cache.dependency_inputs(outside, self.root)

    def test_existing_binary_and_complete_legacy_command_can_migrate(self):
        self.old["inputs"]["unrelated.hpp"] = "historical irrelevant header"
        self.assertTrue(self.valid(self.old))
        migrated = cache.upgraded_receipt(self.old, self.inputs, self.recipe)
        self.assertEqual(migrated["inputs"], self.old["inputs"])
        self.assertEqual(migrated["command"], self.old["command"])
        self.assertEqual(migrated["builder_sha256"], "historical helper hash")
        self.assertTrue(self.valid(migrated))

    def test_legacy_changed_or_missing_dependency_cannot_migrate(self):
        for changed in ("changed", None):
            value = deepcopy(self.old)
            if changed is None: value["inputs"].pop("shared.hpp")
            else: value["inputs"]["shared.hpp"] = changed
            self.assertFalse(self.valid(value))

    def test_binary_tampering_cannot_migrate_or_hit_v2(self):
        value = cache.upgraded_receipt(self.old, self.inputs, self.recipe)
        self.executable.write_bytes(b"different installed binary")
        self.assertFalse(self.valid(self.old)); self.assertFalse(self.valid(value))

    def test_legacy_command_changes_rejected(self):
        for index, replacement in [(0, "unknown compiler"), (1, "-std=c++20"),
                                   (2, "-O0"), (3, '-DMRBITS_BUILD_STAMP="wrong"'),
                                   (4, "-isystem"), (5, str(self.root.parent)),
                                   (6, str(self.root / "other.cpp")),
                                   (7, "--output"), (8, str(self.executable))]:
            with self.subTest(index=index):
                value = deepcopy(self.old); value["command"][index] = replacement
                self.assertFalse(self.valid(value))
        value = deepcopy(self.old); value["command"].append("-DUNTRACKED=1")
        self.assertFalse(self.valid(value))

    def test_recipe_change_invalidates_v2_but_helper_audit_hash_does_not(self):
        value = cache.upgraded_receipt(self.old, self.inputs, self.recipe)
        value["builder_sha256"] = "new helper unrelated to compilation"
        self.assertTrue(self.valid(value))
        changed = deepcopy(self.recipe); changed["cpp_flags"] = ["-std=c++17", "-O3"]
        self.assertFalse(self.valid(value, recipe=changed))

    def test_toolchain_identity_change_invalidates_v2(self):
        value = cache.upgraded_receipt(self.old, self.inputs, self.recipe)
        self.compiler.write_bytes(b"updated compiler fixture")
        changed = cache.recipe(self.source, self.root, compiler=str(self.compiler))
        self.assertFalse(self.valid(value, recipe=changed))

    def test_recovery_provenance_is_preserved(self):
        value = deepcopy(self.old)
        value["origin"] = "verified_git_artifact_recovery"
        command = value.pop("command")
        command[3] = f'-DMRBITS_BUILD_STAMP="original-{self.inputs["Kernel.cpp"][:12]}-20261104T000000Z"'
        value["recovery"] = {"comparison_command": command, "git_blob": "git-id",
                             "comparison_executable_sha256": "comparison-sha",
                             "equivalence_proof": "proof.json", "inputs_validation": "validated"}
        self.assertTrue(self.valid(value))
        migrated = cache.upgraded_receipt(value, self.inputs, self.recipe)
        self.assertEqual(migrated["origin"], value["origin"])
        self.assertEqual(migrated["recovery"], value["recovery"])
        self.assertNotIn("command", migrated)
        self.assertEqual(migrated["stamp"], value["stamp"])

    def test_malformed_metadata_is_a_cache_miss(self):
        self.assertFalse(self.valid([]))
        for recovery in (None, [], "not a provenance object"):
            value = deepcopy(self.old)
            value["origin"] = "verified_git_artifact_recovery"
            value["recovery"] = recovery
            self.assertFalse(self.valid(value))
        for validation in (None, [], "not validation"):
            value = cache.upgraded_receipt(self.old, self.inputs, self.recipe)
            value["cache_validation"] = validation
            self.assertFalse(self.valid(value))

    def test_sqlite_amalgamation_is_explicit_opaque_input(self):
        folder = self.root / "sqlite"; folder.mkdir()
        (folder / "sqlite3.c").write_text('#if 0\n#include CUSTOM_INCLUDE\n#endif\n')
        (folder / "sqlite3.h").write_text("// API fixture")
        found = cache.dependency_inputs(self.source, self.root, controller=True)
        self.assertIn("sqlite/sqlite3.c", found); self.assertIn("sqlite/sqlite3.h", found)
        value = cache.recipe(self.source, self.root, controller=True,
                             compiler=str(self.compiler), c_compiler=str(self.compiler))
        self.assertEqual(value["sqlite"]["flags"], cache.SQLITE_FLAGS)


if __name__ == "__main__":
    unittest.main()
