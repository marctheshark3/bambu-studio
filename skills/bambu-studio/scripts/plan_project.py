#!/usr/bin/env python3
"""Plan one unsliced Bambu Studio project. Does not start a print.

Usage:
  plan_project.py plan --bed-x 256 --bed-y 256 --out DIR --part GROUP=model.stl
  plan_project.py argv --slicer bambu-studio --assemble DIR/assemble-list.json \
      --out-3mf DIR/project.3mf --outputdir DIR \
      --machine machine.json --process process.json --filament filament.json
  plan_project.py check-3mf project.3mf
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from itertools import permutations
from pathlib import Path

FORBIDDEN_EXPORT_FLAGS = (
    "--slice",
    "--orient",
    "--arrange",
    "--rotate",
    "--rotate-x",
    "--rotate-y",
    "--scale",
    "--assemble",
)
MAX_GROUP = 6


class PlanError(ValueError):
    """The requested plates cannot be built without changing the part."""


def mesh_bounds(path: Path) -> tuple[list[float], list[float]]:
    data = path.read_bytes()
    if _binary_stl(data):
        points = _binary_points(data)
    elif data.lstrip().lower().startswith(b"solid") and b"vertex" in data.lower():
        points = _ascii_points(data)
    else:
        raise PlanError(f"unsupported mesh: {path}")
    if not points:
        raise PlanError(f"mesh has no vertices: {path}")
    low = [min(point[axis] for point in points) for axis in range(3)]
    high = [max(point[axis] for point in points) for axis in range(3)]
    return low, high


def _binary_stl(data: bytes) -> bool:
    if len(data) < 84:
        return False
    count = struct.unpack_from("<I", data, 80)[0]
    return len(data) == 84 + count * 50


def _binary_points(data: bytes) -> list[tuple[float, float, float]]:
    count = struct.unpack_from("<I", data, 80)[0]
    points = []
    offset = 84
    for _ in range(count):
        values = struct.unpack_from("<12fH", data, offset)
        points.extend(
            (
                (values[3], values[4], values[5]),
                (values[6], values[7], values[8]),
                (values[9], values[10], values[11]),
            )
        )
        offset += 50
    return points


def _ascii_points(data: bytes) -> list[tuple[float, float, float]]:
    points = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].lower() == "vertex":
            points.append((float(parts[1]), float(parts[2]), float(parts[3])))
    return points


def write_rotated_stl(source: Path, dest: Path) -> None:
    """Rotate 90 degrees about Z and put the minimum XY corner at the origin."""
    triangles = [_turn_triangle(verts) for verts in _triangles(source)]
    xs = [vert[0] for verts in triangles for vert in verts]
    ys = [vert[1] for verts in triangles for vert in verts]
    zs = [vert[2] for verts in triangles for vert in verts]
    if not triangles:
        raise PlanError(f"mesh has no triangles: {source}")
    shift = (min(xs), min(ys), min(zs) if min(zs) < 0 else 0.0)
    out = bytearray(b"bambu-studio z90".ljust(80, b" "))
    out += struct.pack("<I", len(triangles))
    for verts in triangles:
        shifted = tuple((v[0] - shift[0], v[1] - shift[1], v[2] - shift[2]) for v in verts)
        normal = _normal(shifted)
        flat = [coord for vert in (normal, *shifted) for coord in vert]
        out += struct.pack("<12fH", *flat, 0)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(out)


def _triangles(path: Path) -> list[tuple[tuple[float, float, float], ...]]:
    data = path.read_bytes()
    if _binary_stl(data):
        count = struct.unpack_from("<I", data, 80)[0]
        triangles = []
        offset = 84
        for _ in range(count):
            values = struct.unpack_from("<12fH", data, offset)
            triangles.append(tuple((values[3 + i * 3], values[4 + i * 3], values[5 + i * 3]) for i in range(3)))
            offset += 50
        return triangles
    if data.lstrip().lower().startswith(b"solid") and b"vertex" in data.lower():
        collected, current = [], []
        for line in data.decode("utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0].lower() == "vertex":
                current.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif parts and parts[0].lower() == "endfacet" and len(current) >= 3:
                collected.append(tuple(current[:3]))
                current = []
        return collected
    raise PlanError(f"unsupported mesh: {path}")


def _turn_triangle(verts):
    return tuple(_turn(vert) for vert in verts)


def _turn(vert: tuple[float, float, float]) -> tuple[float, float, float]:
    return (vert[1], -vert[0], vert[2])


def _normal(verts: tuple[tuple[float, float, float], ...]) -> tuple[float, float, float]:
    ax, ay, az = (verts[1][i] - verts[0][i] for i in range(3))
    bx, by, bz = (verts[2][i] - verts[0][i] for i in range(3))
    return (ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx)


def pack_rectangles(sizes: list[tuple[float, float]], bed_x: float, bed_y: float, gap: float):
    """Return placements or None. sizes are (width, height) after a chosen rotation."""
    if len(sizes) > MAX_GROUP:
        raise PlanError(f"exhaustive packing stops at {MAX_GROUP} parts in one group")
    order = list(range(len(sizes)))
    for perm in permutations(order):
        placed = _place(list(perm), sizes, [], bed_x, bed_y, gap)
        if placed is not None:
            by_index = {item["index"]: item for item in placed}
            return [by_index[i] for i in order]
    return None


def _place(pending, sizes, placed, bed_x, bed_y, gap):
    if not pending:
        return placed
    index = pending[0]
    width, height = sizes[index]
    if width > bed_x or height > bed_y:
        return None
    candidates_x = {0.0} | {item["x"] + item["w"] + gap for item in placed}
    candidates_y = {0.0} | {item["y"] + item["h"] + gap for item in placed}
    for x in sorted(candidates_x):
        for y in sorted(candidates_y):
            trial = {"index": index, "x": x, "y": y, "w": width, "h": height}
            if x + width > bed_x + 1e-6 or y + height > bed_y + 1e-6:
                continue
            if any(not _separated(trial, item, gap) for item in placed):
                continue
            found = _place(pending[1:], sizes, placed + [trial], bed_x, bed_y, gap)
            if found is not None:
                return found
    return None


def _separated(a, b, gap) -> bool:
    return (
        a["x"] + a["w"] + gap <= b["x"] + 1e-6
        or b["x"] + b["w"] + gap <= a["x"] + 1e-6
        or a["y"] + a["h"] + gap <= b["y"] + 1e-6
        or b["y"] + b["h"] + gap <= a["y"] + 1e-6
    )


def plan_parts(parts: list[dict], bed_x: float, bed_y: float, gap: float, allow_split: bool) -> dict:
    plates = []
    splits = []
    grouped: dict[str, list[dict]] = {}
    for part in parts:
        grouped.setdefault(part["group"], []).append(part)
    for name, group in grouped.items():
        packed = _pack_group(group, bed_x, bed_y, gap)
        if packed is None:
            if len(group) == 1 or not allow_split:
                span = _group_span(group)
                raise PlanError(
                    f"{name} does not fit on {bed_x:g} x {bed_y:g} mm "
                    f"with {gap:g} mm gaps; measured {span}. Do not scale or flip the bed face."
                )
            splits.append(
                {
                    "group": name,
                    "reason": (
                        f"{name} does not share one plate on {bed_x:g} x {bed_y:g} mm; "
                        f"measured {_group_span(group)}"
                    ),
                }
            )
            for index, part in enumerate(group, start=1):
                alone = _pack_group([part], bed_x, bed_y, gap)
                if alone is None:
                    raise PlanError(
                        f"{part['name']} does not fit on {bed_x:g} x {bed_y:g} mm. Do not scale."
                    )
                plates.append(_plate(f"{name}-{index}", alone))
            continue
        plates.append(_plate(name, packed))
    return {"bed_mm": [bed_x, bed_y], "gap_mm": gap, "plates": plates, "splits": splits}


def _group_span(group: list[dict]) -> str:
    bits = []
    for part in group:
        span = part["span"]
        bits.append(f"{part['name']} {span[0]:.1f}x{span[1]:.1f}x{span[2]:.1f}")
    return ", ".join(bits)


def _pack_group(group, bed_x, bed_y, gap):
    choices = []
    for part in group:
        span = part["span"]
        options = [(span[0], span[1], 0)]
        if part["allow_z_rotation"] and abs(span[0] - span[1]) > 1e-6:
            options.append((span[1], span[0], 90))
        choices.append(options)
    return _search_orientations(group, choices, [], bed_x, bed_y, gap)


def _search_orientations(group, choices, chosen, bed_x, bed_y, gap):
    if len(chosen) == len(group):
        sizes = [(item[0], item[1]) for item in chosen]
        placed = pack_rectangles(sizes, bed_x, bed_y, gap)
        if placed is None:
            return None
        objects = []
        for part, orient, spot in zip(group, chosen, placed):
            objects.append({**part, "rotation_z_deg": orient[2], "placed_mm": [spot["x"], spot["y"]], "size_mm": [spot["w"], spot["h"]]})
        return objects
    index = len(chosen)
    for option in choices[index]:
        found = _search_orientations(group, choices, chosen + [option], bed_x, bed_y, gap)
        if found is not None:
            return found
    return None


def _plate(name: str, objects: list[dict]) -> dict:
    return {
        "name": name,
        "need_arrange": False,
        "objects": [
            {
                "name": item["name"],
                "source": item["source"],
                "rotation_z_deg": item["rotation_z_deg"],
                "span_mm": [round(v, 4) for v in item["span"]],
                "placed_mm": [round(v, 4) for v in item["placed_mm"]],
                "size_mm": [round(v, 4) for v in item["size_mm"]],
                "minimum_mm": [round(v, 4) for v in item["minimum"]],
            }
            for item in objects
        ],
    }


def assemble_list(plan: dict, out_dir: Path) -> dict:
    plates = []
    for plate in plan["plates"]:
        objects = []
        for item in plate["objects"]:
            source = Path(item["source"])
            mesh = source
            minimum = item["minimum_mm"]
            if item["rotation_z_deg"]:
                mesh = out_dir / "rotated" / f"{_safe(item['name'])}-z90.stl"
                write_rotated_stl(source, mesh)
                minimum, _high = mesh_bounds(mesh)
            objects.append(
                {
                    "path": str(mesh.resolve()),
                    "count": 1,
                    "filaments": [1],
                    "pos_x": [round(item["placed_mm"][0] - minimum[0], 4)],
                    "pos_y": [round(item["placed_mm"][1] - minimum[1], 4)],
                    "pos_z": [round(-minimum[2] if minimum[2] < 0 else 0.0, 4)],
                }
            )
        plates.append({"plate_name": plate["name"], "need_arrange": False, "objects": objects})
    return {"plates": plates}


def export_argv(slicer: str, assemble: Path, out_3mf: Path, output_dir: Path, machine: Path, process: Path, filament: Path) -> list[str]:
    argv = [
        slicer,
        "--load-settings",
        f"{machine};{process}",
        "--load-filaments",
        str(filament),
        "--load-assemble-list",
        str(assemble),
        "--export-3mf",
        str(out_3mf),
        "--outputdir",
        str(output_dir),
    ]
    guard_argv(argv)
    return argv


def open_argv(slicer: str, project: Path) -> list[str]:
    argv = [slicer, str(project)]
    guard_argv(argv)
    return argv


def proof_argv(slicer: str, project: Path, output_dir: Path) -> list[str]:
    argv = [slicer, "--export-png", "0", "--outputdir", str(output_dir), str(project)]
    guard_argv(argv)
    return argv


VALUE_FLAGS = {
    "--load-settings",
    "--load-filaments",
    "--load-assemble-list",
    "--export-3mf",
    "--outputdir",
    "--export-png",
}


def guard_argv(argv: list[str]) -> None:
    flags = {arg.split("=", 1)[0] for arg in argv[1:]}
    found = sorted(flags & set(FORBIDDEN_EXPORT_FLAGS))
    if found:
        raise PlanError("refusing slicer flags that slice, transform, or merge: " + " ".join(found))
    positionals = []
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg in VALUE_FLAGS:
            index += 2
            continue
        if arg.startswith("--"):
            index += 1
            continue
        positionals.append(arg)
        index += 1
    if "--load-assemble-list" in flags and any(
        item.lower().endswith((".stl", ".obj", ".3mf")) for item in positionals
    ):
        raise PlanError("an assemble list must not be combined with model arguments")


def check_3mf(path: Path) -> dict:
    import zipfile

    if not zipfile.is_zipfile(path):
        raise PlanError(f"not a 3MF zip: {path}")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        gcode = [name for name in names if name.lower().endswith(".gcode")]
        if gcode:
            raise PlanError("sliced gcode found; this skill only opens unsliced projects: " + ", ".join(gcode))
        if "3D/3dmodel.model" not in names:
            raise PlanError("3MF is missing 3D/3dmodel.model")
        plates = 0
        if "Metadata/model_settings.config" in names:
            text = archive.read("Metadata/model_settings.config").decode("utf-8", errors="replace")
            plates = text.count("<plate>")
    return {"path": str(path), "unsliced": True, "plates": plates}


def _safe(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name)
    return cleaned or "part"


def _part_from_arg(value: str, allow_z_rotation: bool) -> dict:
    if "=" in value:
        group, raw = value.split("=", 1)
    else:
        group, raw = "parts", value
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise PlanError(f"missing mesh: {path}")
    low, high = mesh_bounds(path)
    span = [high[i] - low[i] for i in range(3)]
    return {
        "group": _safe(group),
        "name": path.stem,
        "source": str(path),
        "span": span,
        "minimum": low,
        "allow_z_rotation": allow_z_rotation,
    }


def _write_plan(args) -> int:
    parts = [_part_from_arg(value, not args.no_z_rotation) for value in args.part]
    if not parts:
        raise PlanError("pass at least one --part")
    plan = plan_parts(parts, args.bed_x, args.bed_y, args.gap_mm, args.allow_split)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    listing = assemble_list(plan, out)
    (out / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    (out / "assemble-list.json").write_text(json.dumps(listing, indent=2) + "\n")
    print(json.dumps({"plates": len(plan["plates"]), "splits": plan["splits"]}, indent=2))
    return 0


def _write_argv(args) -> int:
    argv = {
        "export": export_argv(
            args.slicer,
            Path(args.assemble),
            Path(args.out_3mf),
            Path(args.outputdir),
            Path(args.machine),
            Path(args.process),
            Path(args.filament),
        ),
        "open": open_argv(args.slicer, Path(args.out_3mf)),
        "proof": proof_argv(args.slicer, Path(args.out_3mf), Path(args.outputdir) / "proof"),
    }
    print(json.dumps(argv, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan one unsliced Bambu Studio project")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--bed-x", type=float, required=True)
    plan.add_argument("--bed-y", type=float, required=True)
    plan.add_argument("--gap-mm", type=float, default=5.0)
    plan.add_argument("--part", action="append", default=[])
    plan.add_argument("--allow-split", action="store_true")
    plan.add_argument("--no-z-rotation", action="store_true")
    plan.add_argument("--out", required=True)
    plan.set_defaults(func=_write_plan)

    build = sub.add_parser("argv")
    build.add_argument("--slicer", required=True)
    build.add_argument("--assemble", required=True)
    build.add_argument("--out-3mf", required=True)
    build.add_argument("--outputdir", required=True)
    build.add_argument("--machine", required=True)
    build.add_argument("--process", required=True)
    build.add_argument("--filament", required=True)
    build.set_defaults(func=_write_argv)

    check = sub.add_parser("check-3mf")
    check.add_argument("path")
    check.set_defaults(func=lambda args: print(json.dumps(check_3mf(Path(args.path)), indent=2)) or 0)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PlanError as exc:
        print(f"PLAN: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
