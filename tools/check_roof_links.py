"""Verify the native pitched-roof analysis couplings in saved modal and static jobs."""

import argparse
import ast
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import openseespy.opensees as ops


COMMAND = re.compile(r"^ops\.(node|fix|uniaxialMaterial|element)\((.*)\)$")
PROJECTED_RESTRAINT = (0, 0, 1, 1, 1, 0)
FINITE_ORIENTATION = ["-orient", 0, 0, 1, 0, 1, 0, "-shearDist", 1., 1.]


def replay(path):
    nodes, restraints, materials, links = {}, {}, {}, {}
    with path.open(encoding="utf-8") as source:
        for line in source:
            match = COMMAND.fullmatch(line.strip())
            if not match:
                continue
            command, raw = match.groups()
            if command in {"element", "uniaxialMaterial"}:
                kind = raw.split(",", 1)[0].strip("'\" ")
                if kind not in {"zeroLength", "twoNodeLink", "Elastic"}:
                    continue
            args = ast.literal_eval("(" + raw + ",)")
            if command == "node":
                nodes[args[0]] = args[1:4]
            elif command == "fix":
                restraints[args[0]] = args[1:]
            elif command == "uniaxialMaterial":
                materials[args[1]] = args[2]
            else:
                kind, tag, projected, physical, *options = args
                if not 7000000 <= tag < 7100000:
                    continue
                first, second = nodes[projected], nodes[physical]
                height = second[2] - first[2]
                if max(abs(first[k] - second[k]) for k in (0, 1)) > .001 or height < -.001:
                    raise ValueError(f"{path} {tag}: diaphragm nodes are not vertically aligned")
                if tuple(restraints.get(projected, ())) != PROJECTED_RESTRAINT:
                    raise ValueError(f"{path} {tag}: unexpected projected-node restraint")
                if options[:1] != ["-mat"] or options[2:3] != ["-dir"]:
                    raise ValueError(f"{path} {tag}: unsupported diaphragm spring")
                direction = options[3]
                if kind == "twoNodeLink":
                    if options[4:] != FINITE_ORIENTATION or direction not in (2, 3):
                        raise ValueError(f"{path} {tag}: unexpected finite-link axes")
                    direction = 1 if direction == 3 else 2
                elif options[4:] or direction not in (1, 2):
                    raise ValueError(f"{path} {tag}: unexpected zero-length link axes")
                links[tag] = (kind, round(height, 6), direction, materials[options[1]])
    return links


def tangent(height, direction, stiffness, kind):
    """Return the compiled element tangent on three projected and six physical DOFs."""
    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 6)
    for node, elevation in ((1, 0), (2, height), (3, 0), (4, height)):
        ops.node(node, 0, 0, elevation)
    ops.fix(1, *PROJECTED_RESTRAINT)
    for ground in (3, 4):
        ops.fix(ground, 1, 1, 1, 1, 1, 1)
    ops.uniaxialMaterial("Elastic", 1, stiffness)
    ops.uniaxialMaterial("Elastic", 2, 1.)
    if kind == "zeroLength":
        ops.element("zeroLength", 10, 1, 2, "-mat", 1, "-dir", direction)
    else:
        local_direction = 3 if direction == 1 else 2
        ops.element("twoNodeLink", 10, 1, 2, "-mat", 1, "-dir", local_direction, *FINITE_ORIENTATION)

    # Unit springs stabilize uncoupled DOFs. Subtract their diagonal below.
    for tag, node, ground in ((11, 1, 3), (12, 2, 4)):
        ops.element("zeroLength", tag, node, ground, "-mat", *([2] * 6), "-dir", 1, 2, 3, 4, 5, 6)
    ops.constraints("Plain")
    ops.numberer("Plain")
    ops.system("FullGeneral")
    ops.algorithm("Linear")
    ops.integrator("GimmeMCK", 0., 0., 1., 0.)
    ops.analysis("Transient")
    if ops.analyze(1, 0.) != 0:
        raise ValueError("Could not assemble the diaphragm tangent")
    dofs = [ops.nodeDOFs(1)[i] for i in (0, 1, 5)] + list(ops.nodeDOFs(2))
    assembled = np.array(ops.printA("-ret")).reshape(9, 9)
    return assembled[np.ix_(dofs, dofs)] - np.eye(9)


def verify(hr, cfs):
    jobs, conditions = [], set()
    for family, root in (("HR", hr), ("CFS", cfs)):
        for modal in sorted(root.rglob("model_opensees.py")):
            static = modal.with_name("model_static.py")
            links = replay(modal)
            if not links:
                continue
            if replay(static) != links:
                raise ValueError(f"{modal}: modal and static diaphragm inputs differ")
            groups = []
            for (kind, height, direction, stiffness), count in sorted(Counter(links.values()).items()):
                groups.append(dict(formulation=kind, offset_mm=height, global_dof=direction,
                                   stiffness_N_mm=stiffness, count=count))
                if height > .001:
                    conditions.add((height, direction, stiffness))
            jobs.append(dict(module=family, job=modal.parent.relative_to(root).as_posix(), groups=groups,
                             modal_sha256=hashlib.sha256(modal.read_bytes()).hexdigest(),
                             static_sha256=hashlib.sha256(static.read_bytes()).hexdigest()))

    results = []
    for height, direction, stiffness in sorted(conditions):
        difference = np.zeros(9)
        difference[direction - 1] = 1
        difference[3 + direction - 1] = -1
        expected = stiffness * np.outer(difference, difference)
        error = max(float(np.abs(tangent(height, direction, stiffness, kind) - expected).max())
                    for kind in ("zeroLength", "twoNodeLink"))
        if not math.isfinite(error) or error > 1e-4:
            raise ValueError(f"{height} mm, global DOF {direction}: unexpected tangent error {error}")
        results.append(dict(offset_mm=height, global_dof=direction, stiffness_N_mm=stiffness,
                            maximum_matrix_entry_error=error))
    if not jobs or not results:
        raise ValueError("No pitched-roof diaphragm cases were measured")
    return dict(status="pass", jobs=jobs, compiled_tangents=results, scope=(
        "Both link formulations were checked against the expected 9-by-9 tangent for an isolated "
        "translational spring with the native projected-node Z, RX and RY restraints. Input hashes "
        "identify the modal and static building replays. Physical member and bearing geometry is "
        "assessed in each building's IFC acceptance record."
    ))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("hr", "cfs", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.hr, args.cfs)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{len(result['jobs'])} pitched-roof native jobs, {len(result['compiled_tangents'])} compiled tangent comparisons")
