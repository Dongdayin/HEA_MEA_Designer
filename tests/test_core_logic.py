import tempfile
import sys
import unittest
from pathlib import Path

import hea_mea_designer as app


def make_structure() -> app.LammpsStructure:
    box = app.BoxBounds(0.0, 10.0, 0.0, 10.0, 0.0, 10.0)
    atoms = [
        app.AtomRecord(atom_id=1, atom_type=1, x=0.1, y=1.0, z=1.0),
        app.AtomRecord(atom_id=2, atom_type=1, x=9.8, y=1.0, z=1.0),
        app.AtomRecord(atom_id=3, atom_type=2, x=5.0, y=5.0, z=9.2),
    ]
    return app.LammpsStructure(
        path=Path("input.lmp"),
        header_lines=[
            "LAMMPS data",
            "",
            "3 atoms",
            "2 atom types",
            "",
            "0.0 10.0 xlo xhi",
            "0.0 10.0 ylo yhi",
            "0.0 10.0 zlo zhi",
            "",
        ],
        mass_lines=[
            "Masses",
            "",
            "1 58.6934 # Ni",
            "2 51.9961 # Cr",
            "",
        ],
        atom_lines=[],
        tail_lines=[],
        atoms=atoms,
        box=box,
        atom_count=3,
        atom_types=2,
    )


class CoreLogicTests(unittest.TestCase):
    def test_recipe_parsing_merges_symbols_and_normalizes_formula(self) -> None:
        entries = app.parse_recipe_text("Ni50 Cr25 Ni25")

        self.assertEqual([entry.symbol for entry in entries], ["Ni", "Cr"])
        self.assertEqual([entry.weight for entry in entries], [75.0, 25.0])
        self.assertEqual(app.format_formula(entries, percent_digits=1), "Ni75.0Cr25.0")

    def test_recipe_parsing_rejects_invalid_scientific_inputs(self) -> None:
        with self.assertRaises(ValueError):
            app.parse_recipe_text("Ni50 Xx50")
        with self.assertRaises(ValueError):
            app.parse_recipe_text("Ni50 Cr-1")

    def test_largest_remainder_counts_preserves_total(self) -> None:
        counts = app.largest_remainder_counts([1.0, 1.0, 1.0], 10)

        self.assertEqual(sum(counts), 10)
        self.assertEqual(counts, [4, 3, 3])

    def test_largest_remainder_counts_rejects_negative_or_nonfinite_weights(self) -> None:
        with self.assertRaises(ValueError):
            app.largest_remainder_counts([1.0, -0.1, 1.0], 10)
        with self.assertRaises(ValueError):
            app.largest_remainder_counts([1.0, float("nan")], 10)

    def test_strict_numeric_parsers_reject_silent_truncation_and_nonfinite_values(self) -> None:
        self.assertEqual(app.parse_positive_int("2000", "步数"), 2000)
        self.assertEqual(app.parse_positive_int("", "弛豫步数", default=2000), 2000)
        self.assertAlmostEqual(app.parse_positive_float("0.001", "步长"), 0.001)
        self.assertIsNone(app.parse_optional_float_value("", "压力"))
        self.assertEqual(app.parse_optional_float_value("-1.5", "压力"), -1.5)

        with self.assertRaises(ValueError):
            app.parse_positive_int("1.5", "步数")
        with self.assertRaises(ValueError):
            app.parse_positive_int("0", "步数")
        with self.assertRaises(ValueError):
            app.parse_positive_float("nan", "温度")
        with self.assertRaises(ValueError):
            app.parse_positive_float("0", "步长")

    def test_region_selection_uses_box_geometry(self) -> None:
        structure = make_structure()

        top_indices = app.select_doping_region_indices(structure.atoms, structure.box, "top_surface", 0.0)
        bottom_indices = app.select_doping_region_indices(structure.atoms, structure.box, "bottom_surface", 0.0)

        self.assertEqual(top_indices, [2])
        self.assertEqual(bottom_indices, [0, 1])

    def test_substitution_doping_updates_types_and_masses(self) -> None:
        structure = make_structure()
        entries = [
            app.DopingEntry(
                symbol="Co",
                operation="substitution",
                region="top_surface",
                amount=1.0,
                amount_mode="count",
                control=0.0,
            )
        ]

        atoms, type_assignments, mass_entries, box, summaries = app.apply_doping_entries(
            structure,
            structure.atoms,
            [atom.atom_type for atom in structure.atoms],
            [
                app.CompositionEntry("Ni", 0.5, app.element_mass("Ni")),
                app.CompositionEntry("Cr", 0.5, app.element_mass("Cr")),
            ],
            entries,
            enabled=True,
            seed=42,
        )

        self.assertEqual(len(atoms), 3)
        self.assertEqual(type_assignments, [1, 1, 3])
        self.assertEqual([entry.symbol for entry in mass_entries], ["Ni", "Cr", "Co"])
        self.assertEqual(box, structure.box)
        self.assertEqual(len(summaries), 1)

    def test_doping_target_selection_never_reuses_same_site(self) -> None:
        rng = app.random.Random(123)

        selected = app.choose_doping_indices([0, 1, 2], 10, rng)

        self.assertEqual(len(selected), 3)
        self.assertEqual(sorted(selected), [0, 1, 2])
        self.assertEqual(app.resolve_doping_target_count(10, "count", 3), 3)
        with self.assertRaises(ValueError):
            app.resolve_doping_target_count(101, "percent", 3)

    def test_prune_close_contact_uses_periodic_minimum_image(self) -> None:
        structure = make_structure()

        atoms, types, removed_count, minimum_distance = app.prune_close_contact_atoms(
            structure.atoms,
            structure.box,
            type_assignments=[atom.atom_type for atom in structure.atoms],
            threshold=0.5,
        )

        self.assertEqual(removed_count, 1)
        self.assertAlmostEqual(minimum_distance, 0.3, places=6)
        self.assertEqual([atom.atom_id for atom in atoms], [1, 2])
        self.assertEqual(types, [1, 2])

    def test_write_lammps_structure_round_trips_counts_and_sections(self) -> None:
        structure = make_structure()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.lmp"
            app.write_lammps_structure(
                output_path,
                structure,
                structure.atoms[:2],
                mass_entries=[app.CompositionEntry("Ni", 1.0, app.element_mass("Ni"))],
                atom_types_count=1,
                type_assignments=[1, 1],
            )

            written = output_path.read_text(encoding="utf-8")

        self.assertIn("2 atoms", written)
        self.assertIn("1 atom types", written)
        self.assertIn("Masses", written)
        self.assertIn("Atoms # atomic", written)
        self.assertIn("# Ni", written)

    def test_read_lammps_structure_accepts_comments_and_validates_counts(self) -> None:
        valid_text = "\n".join(
            [
                "LAMMPS data",
                "",
                "2 atoms # generated fixture",
                "1 atom types # generated fixture",
                "",
                "0.0 10.0 xlo xhi",
                "0.0 10.0 ylo yhi",
                "0.0 10.0 zlo zhi",
                "",
                "Masses",
                "",
                "1 58.6934 # Ni",
                "",
                "Atoms # atomic",
                "",
                "1 1 0.0 0.0 0.0 # origin",
                "2 1 1.0 1.0 1.0",
                "",
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "valid.lmp"
            path.write_text(valid_text, encoding="utf-8")
            structure = app.read_lammps_structure(path)
            bad_path = Path(tmpdir) / "bad.lmp"
            bad_path.write_text(valid_text.replace("2 atoms", "3 atoms", 1), encoding="utf-8")

            self.assertEqual(len(structure.atoms), 2)
            with self.assertRaises(ValueError):
                app.read_lammps_structure(bad_path)

    def test_parse_box_bounds_rejects_invalid_limits(self) -> None:
        with self.assertRaises(ValueError):
            app.parse_box_bounds(
                [
                    "10.0 0.0 xlo xhi",
                    "0.0 10.0 ylo yhi",
                    "0.0 10.0 zlo zhi",
                ]
            )

    def test_parse_atom_line_keeps_atomic_format_strict(self) -> None:
        atom = app.parse_atom_line("10 2 1.0 2.0 3.0 # atom comment", 1)

        self.assertEqual(atom, app.AtomRecord(atom_id=10, atom_type=2, x=1.0, y=2.0, z=3.0))
        self.assertIsNone(app.parse_atom_line("# comment", 2))
        with self.assertRaises(ValueError):
            app.parse_atom_line("1 1 0.0 0.0 0.0 99.0", 3)
        with self.assertRaises(ValueError):
            app.parse_atom_line("1 1 inf 0.0 0.0", 4)

    def test_write_lammps_structure_rejects_inconsistent_type_assignments(self) -> None:
        structure = make_structure()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.lmp"
            with self.assertRaises(ValueError):
                app.write_lammps_structure(
                    output_path,
                    structure,
                    structure.atoms,
                    atom_types_count=2,
                    type_assignments=[1, 1],
                )
            with self.assertRaises(ValueError):
                app.write_lammps_structure(
                    output_path,
                    structure,
                    structure.atoms,
                    atom_types_count=1,
                    type_assignments=[1, 1, 2],
                )

    def test_run_command_failure_includes_diagnostic_context(self) -> None:
        command = [
            sys.executable,
            "-c",
            "import sys; print('command stdout'); print('command stderr', file=sys.stderr); raise SystemExit(7)",
        ]

        with self.assertRaises(RuntimeError) as raised:
            app.run_command(command, cwd=Path.cwd())

        message = str(raised.exception)
        self.assertIn("退出码 7", message)
        self.assertIn("命令:", message)
        self.assertIn("工作目录:", message)
        self.assertIn("stdout:", message)
        self.assertIn("command stdout", message)
        self.assertIn("stderr:", message)
        self.assertIn("command stderr", message)

    def test_process_output_truncation_keeps_message_bounded(self) -> None:
        truncated = app._truncate_process_output("x" * 5000, limit=100)

        self.assertTrue(truncated.startswith("x" * 100))
        self.assertIn("truncated 4900 characters", truncated)


if __name__ == "__main__":
    unittest.main()
