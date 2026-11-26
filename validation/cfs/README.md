# Fresh India cold-formed steel designs

Each `IN_CFS_Ex*/result.json` identifies the active building brief, its hash, the design basis, gravity build-up, site inputs, governing native checks, dimensional controls and proposal assumptions. `handoff.json.gz` decompresses to the exact `design/openbim_handoff.json` emitted by the cold-formed steel customer exporter. The SHA-256 in the result identifies those uncompressed bytes. Compare the worked example only after fixing this hash.

The engineering reconciliation compares all 15 published reports and both committed reference fixtures with the local designs. It records the corrected storage, wind, corridor and podium inputs alongside the original freeze hashes. [Engineering review](engineering-review.md)

## Reproduce one design

Use the active `test_buildings/IN_CFS_Ex*.txt` briefs from `Steltic/steltic_CFS_india`. The baseline structural engine commit is `6e43e5839a84358a6a23356b2de4d59ab914a38b`. Use a checkout containing the optional `steel_engine/openbim_handoff.py` producer and install the India BIM package into its Python environment. The native 3D runs also require the CFS repository's OpenSeesPy, NumPy and reporting dependencies. `--jobs` names local scratch. The licensed source corpus and retrieval excerpts stay there.

```console
python validation/cfs/run_native.py 9 --engine ../steltic_CFS_india --corpus /path/to/corpus_fixed --jobs /path/to/private/jobs
python validation/cfs/export_case.py 9 --engine ../steltic_CFS_india --jobs /path/to/private/jobs --target /path/to/replay
python validation/cfs/verify_replay.py 9 --jobs /path/to/private/jobs --replay /path/to/replay
```

The first command reconstructs the job from the brief and local specification corpus, calls `india_cfs_pipeline.design_and_report`, and writes the native HTML report, viewer, status and calculation package. The second binds physical occurrences to the actual native group checks and writes the customer job sidecar and portable evidence. The third rehashes every bound native source and compares the issued and recalculated quantities, checks, geometry and bearing probes. Local report paths and timestamps can change the byte hash between independent runs. Within a run the portable handoff must match the native job sidecar byte for byte. Open the job in the India BIM Hub or use the BIM publishing command in the project README.

## Cases

| Brief | Location | Physical and analytical features |
| --- | --- | --- |
| 1 | Chennai | 48 × 18 m moment portals, SCBF sidewalls, two roof slopes, compression-capable plan braces and flange stays |
| 2 | Srinagar | 76 × 21 m cold store, transverse SMRF, sidewall EBF links, distinct roof-plane trusses, vestibule, rooftop condenser and unbalanced snow |
| 3 | Hyderabad | Seven two-span all-CFS portals, elastic R = 1, separate 12 × 8 m storage mezzanine, sidewall X-braces and four roof slopes |
| 4 | Nagpur | 30 × 24 m high bay, offset 24 × 12 m two-level office, open storefront with full-height braced returns, gabled high bay |
| 5 | Visakhapatnam | Three-level L-plan motel, exterior galleries within the floor outline, through-breezeway and cyclone exposure |
| 6 | Coimbatore | South-half walkout diaphragm and uphill grade supports at +3 m, four level datums, local imaging-suite load enveloped |
| 7 | Delhi | Four-storey 12 × 8 m SCBF building, independently balanced X and Y brace lines and 4 m joists |
| 8 | Ahmedabad | Four-storey T-plan, two gabled zones meeting at a valley, braced head/stem and re-entrant diaphragm |
| 9 | Lucknow | Four-storey western truss roof, three-storey eastern roof step, 8 × 4 m entry recess and framed window openings |
| 10 | Mumbai | Five-storey 24 × 12 m corridor building, two 5 m wings and 2 m corridor |
| 11 | Pune | Five-storey L-plan, north gable, flat accessible amenity roof and re-entrant transfer line |
| 12 | Bengaluru | Six-storey student housing with two 5 m wings, 2 m corridor and braced corridor/end lines |
| 13 | Surat | Six-storey offset 46 × 18 m wings, 18 × 8 m corridor, coastal wind checks and roof mechanical allowance |
| 14 | Noida | Two 64 × 40 m composite podium levels, five U-shaped residential levels, open court and continuous bracing |
| 15 | Kolkata | Eight-storey cruciform, four re-entrant corners and three primary-column tiers |

`brief_frame.py` supplies project geometry through the native engine’s public custom-builder interface. The occupied pitched buildings have an actual ceiling diaphragm with a roof truss above. The open portal roofs use the eave-spread model. Angle webs, primary chords and the double-height return braces participate in the same analysis as the columns. Noida has a separate concrete-topped diaphragm stiffness at the podium. `grounding.py` records the supplied corpus locators and digests. Noida’s Delhi wind proxy and Srinagar’s ground snow-zone assumption require site confirmation.

## Interpreting the evidence

Each case includes `bearing-samples.json`. Its ordered occurrence IDs run from the receiving steel to the carried member or panel. For each global station, an independent IFC reader can intersect the solids along the stated unit normal, measure adjacent material limits, and compare with the expected signed gap in millimetres. Across the 15 cases, 53 distinct sample chains cover 133 interfaces. The samples identify representative occurrences and section combinations. The generated support locations, physical surface offsets and native analysis workpoints are also recorded in the handoff and result.

Floor boards bear on installed joist upper flanges. Flat roofs bear on purlins seated above the primary steel. Pitched roofs retain their plan ridge, valley and eave positions, with a separate recessed purlin on each side of a fold. The four horizontal ceiling diaphragms have dedicated suspended joists beneath the primary ties. The Srinagar cold-store model includes insulated panels, thermal isolation strips, the airlock load path and a level condenser platform with open steel grating. See the fitted setout and remaining supplier requirements in the engineering review. [Engineering review](engineering-review.md)

The native gate status pertains to the stated design inputs. The BIM packages carry review items for material certificates, tested diaphragm behavior, anchor bond and breakout, weld preparations, fabrication and site setout. Connection plates, fasteners, bearing seats and selected fillet welds have physical bodies. Complete-joint-penetration welds carry type and effective-length callouts. The primary analytical levels and workpoints provide the design datums. Where present, `analysis_workpoints_mm` and `analysis_plane_mm` preserve the original datum alongside the installed coordinates used in the drawings and IFC.
