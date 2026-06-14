import tempfile
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

    def test_largest_remainder_counts_preserves_total(self) -> None:
        counts = app.largest_remainder_counts([1.0, 1.0, 1.0], 10)

        self.assertEqual(sum(counts), 10)
        self.assertEqual(counts, [4, 3, 3])

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


if __name__ == "__main__":
    unittest.main()
