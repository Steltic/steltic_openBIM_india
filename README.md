# Steltic openBIM India

Generate an A1 structural drawing set and an IFC4 coordination model from an Indian hot-rolled or cold-formed steel design. Each delivered revision includes a machine-readable drawing register and an independent readback certificate. The [building index](validation/README.md) contains the issued example files, design decisions, assumptions and outstanding checks.

## Run a building

Use Python 3.12 for the tested configuration. From a checkout of this repository:

```shell
python -m venv .venv
# Activate .venv in your shell
python -m pip install ".[hub]"
steltic-openbim-india deliver validation/cfs/IN_CFS_Ex3/handoff.json.gz --output hyderabad
```

Open `hyderabad/drawings.pdf` or `hyderabad/model.ifc`. The PDF title block gives the design decision and source fingerprint. The IFC uses millimetres, Z up, and preserves the same revision, material grades, section orientation, occurrence IDs and calculation links. `drawing_register.json` maps occurrences to drawings and detail sheets. `certificate.json` reports what the independent reader found in the two saved files.

## Use a native India job

1. Design the building in [Steltic India HR](https://github.com/Steltic/steltic_india) or [Steltic India CFS](https://github.com/Steltic/steltic_CFS_india). Record the building layout, datums, openings, connection locations and actual shop parts as the design proceeds. The [physical exchange guide](contracts/INDIA_HANDOFF.md) and [JSON schema](src/steltic_openbim_india/handoff.schema.json) describe the fields.
2. Export the finished native job. HR resolves a physical declaration against its analysis elements, section catalogue, selected material grades and job records. CFS resolves the layout against the final cold-formed selections, plies and vendored lateral-frame results. Both write `JOB/design/openbim_handoff.json`.
3. Generate the PDF and STEP model. The job command rechecks the native file fingerprints immediately before publishing the output directory.

```shell
# In the India HR environment and repository
python -m steel_engine.openbim_handoff JOB PHYSICAL_DECLARATION.json

# In the India openBIM environment
steltic-openbim-india deliver-job JOB --output delivery
python -m steltic_openbim_india.audit JOB/design/openbim_handoff.json delivery
```

For CFS, install this package in the design environment and use `cfg["openbim_layout"]` or call `openbim_handoff.write_handoff(job_directory, layout)` after sizing. Uploaded handoffs can also be delivered directly with `steltic-openbim-india deliver HANDOFF --output delivery`. Pass `--source-root JOB` when the native files are available. [CFS producer guide](https://github.com/Steltic/steltic_CFS_india/blob/main/docs/openbim.md)

## Local application

```shell
steltic-openbim-india serve --port 8090
```

Open [the local application](http://127.0.0.1:8090). **Steltic import** accepts a JSON handoff or a completed native job discovered under `HR_JOBS` or `CFS_JOBS`. **IFC import** inspects an IFC2x3, IFC4 or IFC4x3 source and displays selected storeys or structural products in 3D. Its architectural brief export retains geometry constraints and source identity for the chosen India module. **IFC export** provides both generated structural deliveries and the byte-identical original of an uploaded IFC. `OPENBIM_JOBS` sets the project history directory. The [Steltic Hub manifest](steltic_module.json) exposes the same workflow when installed as a module.

Under **Request register and drawing revisions**, choose a drawing set, name the reviewer and record an answer. Confirm an architectural opening by selecting its host panel and entering perimeter coordinates in mm. The revised PDF and IFC include the measured opening, the reviewer attribution and an open structural-coordination check. Reopening the item restores the source panel. Each answer creates a separate revision with links to its parent and original design. `requests.json` lists outstanding engineering checks, connection details and recorded responses.

## What the drawings and certificate cover

| Output | Contents |
| --- | --- |
| Plans and elevations | Level framing plans, elevations of each occupied frame line and orthogonal off-grid projections. Independent structures have separate placements, levels and joint schedules. |
| Schedules and details | Member marks, section shapes and orientation, workline and cut lengths, stock drilling and slot coordinates, panels and openings, selected grades, located connections, receiver IDs, three orthogonal detail views and part schedules for the supplied assemblies. The K-series prints the source calculation decisions and utilization. |
| IFC | Solid rolled and built-up sections, tapered members, sheets and slabs with openings, connection plates and fasteners. Fillet welds use a triangular section. Complete-joint-penetration welds use the specified effective throat and width. The drawing identifies each located connection awaiting fabrication geometry. |
| Readback | IfcOpenShell independently parses the STEP, validates the schema and tessellates distinct bodies. The checker measures placements, sizes, profile walls, hosted holes, fasteners, welds, unit clearances and horizontal plate overlaps. PyMuPDF rasterizes every sheet and checks printed schedules, dimensions and projected linework. |

`artifact_status` reports agreement between the saved delivery and the input handoff. `design_status` incorporates the supplied native and coordination checks, including open connection details and inter-unit clashes. The [validation index](validation/README.md) also gives the native engine decision and dimensional controls measured against each building brief. Use the applicable decisions together when issuing a model.

## Reproduce the acceptance runs

The website publication tools build a physical viewer from each issued IFC and pair it with the native report and analytical results at the existing example address. [Website publication guide](tools/website/README.md)

```shell
python -m pip install ".[test]"
python -m pytest -q
python tools/validate_examples.py --output building-deliveries --workers 2
python tools/validate_examples.py --case hr:11 --output building-deliveries
```

The runner rebuilds each PDF and IFC in a revision-specific directory. It checks the saved files against the native handoff, measures each building against its brief and probes installed steel at recorded bearing locations. `--require-design-pass` additionally requires every supplied engineering decision to pass. The Bengaluru fixed-frame solar assessment has a local purlin failure at the proposed array load. The [native reproduction instructions](validation/README.md#reproduce-the-native-designs) explain how to regenerate the source calculations with the local BIS corpus. The [revision checklist](validation/revision-checklist.md) compares the frozen independent designs with the published examples.

Pull requests and pushes to `main` rebuild all 36 deliveries on Linux and retain the certificates as workflow artifacts. To download the regenerated Linux PDFs and IFCs together, run **India drawing and IFC acceptance** from the Actions tab and select **Include the independently checked drawing and model files**. The [building index](validation/README.md) links the published drawing and model archives individually.

For a second rendering of the drawing samples, install Poppler with `pdftoppm` on your path. Run `python tools/review_drawings.py --build building-deliveries --output drawing-review` after a full rebuild. Open the PNGs to inspect one framing plan, frame elevation and connection detail per building. `visual-review.json` maps each sample to its PDF, page and sheet number. Image fingerprints identify the rendering produced by the installed Poppler version.

The behavioral reference was [Steltic openBIM 0.8.109](https://github.com/Steltic/steltic_openBIM/tree/c3796b8f3904b448655a05adf8ca72cc5b868b8a). Its architectural IFC inspection, viewer, local access guard and brief exchange are reused. Indian metric producers, profiles, drawings, numerical evidence and acceptance cases implement the India workflow. The fixed BIS corpus and licensed PDFs remain in the operator's local standards directory. The [source manifest](validation/corpus-verification.json) publishes their fingerprints, editions and verification results.
