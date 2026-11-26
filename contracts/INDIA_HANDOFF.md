# Indian steel design handoff

The exchange consumes an occurrence model and design records issued by an India producer. The consumer preserves the producer’s loads, design decisions and calculation findings. Each delivered PDF and IFC carries the SHA-256 of the exact input file. The contract is versioned independently of the source engines.

[Machine-readable schema](../src/steltic_openbim_india/handoff.schema.json) · [Small runnable example](../tests/fixtures/metric_frame.json)

## Physical geometry

Use millimetres for all coordinates and section dimensions. Global Z is up. A level has a unique ID and elevation. Grid X designates lines of constant X, grid Y lines of constant Y. Use a distinct occurrence ID for every physical member, panel, joint or connection part. The runtime validates finite numbers, reference integrity, positive dimensions, section topology and planar polygon validity.

Each member has a start and end in global coordinates, a role, a section ID and a material ID. Its local Z follows the axis to the end. Its local X follows the optional section-width direction projected perpendicular to that axis. Local Y follows Z × X. For a nonvertical member the default X is horizontal and the local depth points up; a vertical member defaults to global X as its section-width direction. The producer supplies the roll for members with a particular installed orientation.

| Profile family | Dimensions in mm |
| --- | --- |
| I | Overall depth `d`, flange width `b`, web `tw`, flange `tf`. Optional root radius `r` or `r1`, toe radius `r2` and inner flange face `slope_deg` in degrees. |
| C, Z | Depth `d`, flange width `b`, uniform `t` or `tw` and `tf`. A return lip uses `lip`. Folded sections accept an inner bend radius `r`. For Z, `b` is the width of one flange including the web. |
| L | Depth `d`, width `b`, thickness `t` or `tw` and `tf`. Optional root and toe radii. |
| RHS | Outside `d`, `b`, wall `t` or separate `tw` and `tf`. Optional inner corner `r`. |
| CHS, ROD | Outside `diameter` (or `d`), plus wall `t` for CHS. |
| PLATE | Section width `b` and depth `d` (or `t`). |
| POLYGON | `contours_mm` gives the outer ring of each disjoint component. Optional `holes_mm` has one list of inner rings per outer contour. Every point is a local X, Y pair. |

An explicit contour overrides a parametric section. Parametric origins lie at the centre of the outside bounding rectangle. Explicit contours retain their authored origin. For a tapered member, `end_profile` defines the end shape. Component count, hole count and vertex correspondence must agree. Parameterized I/round tapers use native IFC4 swept solids. Other tapered contours use a closed polygonal loft. Curved edges of explicit polygons and formed sections are represented at the input or tessellation resolution.

A panel uses an ordered coplanar global outline and a positive thickness. Extrusion follows the right-hand normal of the outer ring. Each opening is a coplanar ring inside that host. Openings cut the body and have explicit IFC void relationships.

Use optional `end_cutbacks_mm` for the distances from each analysis endpoint to the physical steel end plane. The IFC Axis retains the original workline. Section profiles describe the physical start and end faces of the remaining steel. Supply drilled holes or slots in `member_voids` with an occurrence ID and, when available, the owning connection ID. A `bore` gives the global tool-axis `start`, `end` and `diameter_mm`. A `slot` uses an ordered global `outline` and `thickness_mm` in its right-hand normal direction. These operations cut the receiving IFC product. The PDF schedules their positions in the member's local axes from the original workline start. The independent audit compares actual material through each tool path before and after cutting.

## Connections and calculations

A connection binds a positioned joint to its actual receiving members. The producer may include a description, selected parameter dictionary, check IDs and a list of physical parts. Plates use the panel geometry contract. A bolt supplies its actual shaft endpoints and nominal diameter. A fillet weld uses endpoint positions and an equal leg length. The triangular section occupies local coordinates (0, 0), (leg, 0), (0, leg). Use `ref_direction` to orient it. A bolt shaft does not imply a head, nut, drilled hole or embedment. Include each designed hole in its host.

A connection without parts is delivered as a located specification. Its drawing projects the participating member worklines, and the IFC records the relationships. Its physical detailing remains open. The program does not synthesize fasteners, plate boundaries or member end cutbacks.

Each check records its ID, description, source status, optional utilization and standard/clause or calculation reference. Modules can retain additional source data, load evidence and calculation pointers alongside the exchange fields. Explicit failed or pending checks appear on the drawings. All sheets show the overall design status for the handoff. The detached output certificate reports transfer fidelity and the state of the supplied checks separately.

## Independent structures

List separate buildings under `units`, with an ID, label, global `origin_mm` and preferably explicit level IDs. Each physical object declares its unit. All incoming points remain global; exported storey/product placements use the unit’s local frame. A joint may never attach members in separate units.

For a separation joint give its ordered unit pair, comparison axis and direction, reference, and the required clear gap when known. The nominal `declared_gap_mm` can carry `declared_basis` of `workline` or `clear`. Optional `stations_mm` and `elevation_range_mm` limit the comparison to part of the interface. The measured value is the signed distance between outermost material planes. A negative value is a conservative envelope finding. A separate test calculates the common volume of parallel finite plates across units, including their holes. A confirmed overlap greater than 1 mm³ fails the design coordination gate.

## Design handoff and output files

```shell
steltic-openbim-india validate handoff.json
steltic-openbim-india deliver handoff.json --output delivery
```

Delivery writes `drawings.pdf`, `model.ifc`, `drawing_register.json` and `certificate.json` to a new or empty directory. A register indexes sheet kinds, projections, dimension witnesses, occurrence marks, assemblies and separate structures. Each IFC product keeps its source ID, check links and selected material. Project properties carry the complete reported checks and assumptions. A candidate-only render omits the detached audit and its certificate.

The optional `--source-root JOB` on either command verifies every relative path and SHA-256 declared under `source_evidence.files` against the actual native job directory. A verified delivery checks the native bytes again immediately before publishing its output directory.

The same commands accept the frozen `handoff.json.gz` examples directly. Their source fingerprint describes the underlying JSON bytes and is identical to the fingerprint from the unpacked handoff.
