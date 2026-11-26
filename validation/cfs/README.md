# Fresh India cold-formed steel designs

Each `IN_CFS_Ex*/result.json` identifies the active building brief, its hash, the design basis, gravity build-up, site inputs, governing native checks, dimensional controls and proposal assumptions. `handoff.json.gz` decompresses to the exact `design/openbim_handoff.json` emitted by the cold-formed steel customer exporter. The SHA-256 in the result identifies those uncompressed bytes. Compare the worked example only after fixing this hash.

The engineering reconciliation compares all 15 published reports and both committed reference fixtures with the local designs. It records the corrected storage, wind, corridor and podium inputs alongside the original freeze hashes. [Engineering review](engineering-review.md)

## Reproduce one design

Use the active `test_buildings/IN_CFS_Ex*.txt` briefs from `Steltic/steltic_CFS_india`. The baseline structural engine commit is `6e43e5839a84358a6a23356b2de4d59ab914a38b`. Use a checkout containing the optional `steel_engine/openbim_handoff.py` producer and install the India BIM package into its Python environment. The native 3D runs also require the CFS repository's OpenSeesPy, NumPy and reporting dependencies. `--jobs` names local scratch. The licensed source corpus and retrieval excerpts stay there.

```console
python validation/cfs/run_native.py 9 --engine ../steltic_CFS_india --corpus /path/to/corpus_fixed --jobs /path/to/private/jobs
python validation/cfs/export_case.py 9 --engine ../steltic_CFS_india --jobs /path/to/private/jobs --target /path/to/replay
```

The first command constructs a job from the brief and local specification corpus, calls `india_cfs_pipeline.design_and_report`, and writes the native HTML report, 3D viewer, status and calculation package. The second binds authored occurrences to the actual native member and connection groups, checks source identities, emits the job sidecar, and packages the portable evidence. Open the native job in the India BIM Hub or pass its sidecar to the BIM publishing command documented in the project README. Replayed native HTML and absolute-path metadata can change hashes between machines. Compare engineering values, configuration and geometry as well as the source hashes within each run.

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

The native gate status pertains to the design calculated using the listed inputs. The BIM packages also carry review items for product certificates, tested diaphragm behavior, anchor bond and breakout, weld preparations and fabrication workpoints. Plate holes, individual fasteners, selected support seats and fillet welds are explicit geometry. Complete-joint-penetration welds are called out by type and effective length. Nominal member axes, untrimmed steel ends and envelope control planes are explicit modelling assumptions. The construction engineer must resolve the items carried as `review` before fabrication.
