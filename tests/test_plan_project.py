#!/usr/bin/env python3
"""Behavior checks for unsliced Studio project planning."""
from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "bambu-studio" / "scripts"))

import plan_project  # noqa: E402
import studio_windows  # noqa: E402


def write_box(path: Path, size, origin=(0.0, 0.0, 0.0)) -> None:
    sx, sy, sz = size
    ox, oy, oz = origin
    corners = []
    for z in (oz, oz + sz):
        for y in (oy, oy + sy):
            for x in (ox, ox + sx):
                corners.append((x, y, z))
    faces = (
        (0, 1, 3, 2),
        (4, 6, 7, 5),
        (0, 4, 5, 1),
        (2, 3, 7, 6),
        (0, 2, 6, 4),
        (1, 5, 7, 3),
    )
    triangles = []
    for a, b, c, d in faces:
        triangles.append((corners[a], corners[b], corners[c]))
        triangles.append((corners[a], corners[c], corners[d]))
    out = bytearray(b"test-box".ljust(80, b" "))
    out += struct.pack("<I", len(triangles))
    for verts in triangles:
        flat = [0.0, 0.0, 0.0]
        for vert in verts:
            flat.extend(vert)
        out += struct.pack("<12fH", *flat, 0)
    path.write_bytes(out)


class PlanTests(unittest.TestCase):
    def test_front_frames_do_not_share_a_256_plate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left_frame.stl"
            right = root / "right_frame.stl"
            write_box(left, (140.7, 162.6, 20.6))
            write_box(right, (130.7, 162.6, 20.6))
            code = plan_project.main(
                [
                    "plan",
                    "--bed-x",
                    "256",
                    "--bed-y",
                    "256",
                    "--allow-split",
                    "--out",
                    str(root / "out"),
                    "--part",
                    f"fronts={left}",
                    "--part",
                    f"fronts={right}",
                ]
            )
            self.assertEqual(code, 0)
            plan = json.loads((root / "out" / "plan.json").read_text())
            self.assertEqual(len(plan["plates"]), 2)
            self.assertEqual(len(plan["splits"]), 1)
            self.assertIn("does not share one plate", plan["splits"][0]["reason"])
            listing = json.loads((root / "out" / "assemble-list.json").read_text())
            self.assertTrue(all(plate["need_arrange"] is False for plate in listing["plates"]))
            self.assertEqual(len(listing["plates"][0]["objects"]), 1)

    def test_required_group_fails_closed_without_scaling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.stl"
            right = root / "right.stl"
            write_box(left, (140.7, 162.6, 10))
            write_box(right, (130.7, 162.6, 10))
            code = plan_project.main(
                ["plan", "--bed-x", "256", "--bed-y", "256", "--out", str(root / "out"), "--part", f"fronts={left}", "--part", f"fronts={right}"]
            )
            self.assertEqual(code, 2)

    def test_small_parts_share_a_plate_without_overlap(self):
        parts = [
            {"group": "small", "name": "a", "source": "a.stl", "span": [40, 20, 5], "minimum": [0, 0, 0], "allow_z_rotation": True},
            {"group": "small", "name": "b", "source": "b.stl", "span": [30, 20, 5], "minimum": [0, 0, 0], "allow_z_rotation": True},
        ]
        plan = plan_project.plan_parts(parts, 256, 256, 5, False)
        self.assertEqual(len(plan["plates"]), 1)
        placed = plan["plates"][0]["objects"]
        self.assertEqual(len(placed), 2)
        a, b = placed
        separated = (
            a["placed_mm"][0] + a["size_mm"][0] + 5 <= b["placed_mm"][0]
            or b["placed_mm"][0] + b["size_mm"][0] + 5 <= a["placed_mm"][0]
            or a["placed_mm"][1] + a["size_mm"][1] + 5 <= b["placed_mm"][1]
            or b["placed_mm"][1] + b["size_mm"][1] + 5 <= a["placed_mm"][1]
        )
        self.assertTrue(separated)

    def test_oversized_part_is_not_scaled(self):
        part = {"group": "big", "name": "bar", "source": "bar.stl", "span": [300, 10, 10], "minimum": [0, 0, 0], "allow_z_rotation": True}
        with self.assertRaises(plan_project.PlanError) as caught:
            plan_project.plan_parts([part], 256, 256, 5, True)
        self.assertIn("Do not scale", str(caught.exception))

    def test_z_rotation_is_used_only_when_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "long.stl"
            write_box(path, (200, 20, 4), origin=(3, 4, 1))
            code = plan_project.main(
                ["plan", "--bed-x", "100", "--bed-y", "250", "--out", str(root / "out"), "--part", f"one={path}"]
            )
            self.assertEqual(code, 0)
            plan = json.loads((root / "out" / "plan.json").read_text())
            obj = plan["plates"][0]["objects"][0]
            self.assertEqual(obj["rotation_z_deg"], 90)
            listing = json.loads((root / "out" / "assemble-list.json").read_text())
            mesh = Path(listing["plates"][0]["objects"][0]["path"])
            low, high = plan_project.mesh_bounds(mesh)
            self.assertLess(high[0] - low[0], 21)
            self.assertGreater(high[1] - low[1], 199)

    def test_ascii_stl_can_rotate_onto_the_bed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "ascii.stl"
            path.write_text(
                "solid a\n"
                "  facet normal 0 0 0\n"
                "    outer loop\n"
                "      vertex 0 0 0\n"
                "      vertex 180 0 0\n"
                "      vertex 0 10 0\n"
                "    endloop\n"
                "  endfacet\n"
                "endsolid a\n"
            )
            code = plan_project.main(
                ["plan", "--bed-x", "40", "--bed-y", "200", "--out", str(root / "out"), "--part", f"one={path}"]
            )
            self.assertEqual(code, 0)
            plan = json.loads((root / "out" / "plan.json").read_text())
            self.assertEqual(plan["plates"][0]["objects"][0]["rotation_z_deg"], 90)

    def test_argv_refuses_slice_and_transforms(self):
        argv = plan_project.export_argv(
            "bambu-studio",
            Path("assemble-list.json"),
            Path("project.3mf"),
            Path("out"),
            Path("machine.json"),
            Path("process.json"),
            Path("filament.json"),
        )
        self.assertIn("--load-assemble-list", argv)
        self.assertIn("--export-3mf", argv)
        self.assertNotIn("--slice", argv)
        self.assertNotIn("--orient", argv)
        self.assertNotIn("--arrange", argv)
        self.assertFalse(any(arg.endswith(".stl") for arg in argv))
        with self.assertRaises(plan_project.PlanError):
            plan_project.guard_argv(["bambu-studio", "--slice", "0", "project.3mf"])
        with self.assertRaises(plan_project.PlanError):
            plan_project.guard_argv(["bambu-studio", "--load-assemble-list", "list.json", "part.stl"])

    def test_check_3mf_rejects_gcode(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw.3mf"
            sliced = Path(tmp) / "sliced.3mf"
            with zipfile.ZipFile(raw, "w") as archive:
                archive.writestr("3D/3dmodel.model", "<model/>")
            with zipfile.ZipFile(sliced, "w") as archive:
                archive.writestr("3D/3dmodel.model", "<model/>")
                archive.writestr("Metadata/plate_1.gcode", "G1")
            self.assertTrue(plan_project.check_3mf(raw)["unsliced"])
            with self.assertRaises(plan_project.PlanError):
                plan_project.check_3mf(sliced)


class WindowTests(unittest.TestCase):
    def test_send_dialog_is_protected_and_never_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "windows.tsv"
            path.write_text("11\tSend print job\n22\tleft frame — reprint\n")
            code = studio_windows.main(["inventory", "--text", str(path)])
            self.assertEqual(code, 0)
        result = studio_windows.classify(
            [{"id": "11", "title": "Send print job"}, {"id": "22", "title": "left frame"}]
        )
        self.assertEqual(result["protected"][0]["id"], "11")
        self.assertEqual(result["close"], [])
        self.assertEqual(result["click"], [])
        self.assertEqual(result["other"][0]["id"], "22")


class PackageTests(unittest.TestCase):
    def test_package_has_no_printer_secrets_or_host_paths(self):
        root = ROOT / "skills" / "bambu-studio"
        text = "\n".join(
            path.read_text()
            for path in root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        )
        for needle in ("BAMBU_ACCESS_CODE", "192.168.", "/home/", "access_code", "serial"):
            self.assertNotIn(needle, text.lower() if needle.islower() else text)


if __name__ == "__main__":
    unittest.main()
