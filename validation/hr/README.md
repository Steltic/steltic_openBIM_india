# Hot-rolled India examples

The 21 numbered inputs are independently developed designs for the active India HR building briefs. Each case folder contains a physical `handoff.json` and a portable `evidence.json`. The latter binds the brief and local native job files by SHA-256, records the adopted wind, gravity and seismic inputs, and reports native checks and unresolved engineering findings. The signed engineering decision remains the responsibility of the project engineer.

| Examples | Briefs |
| --- | --- |
| 1–5 | Bengaluru PEB, Bhiwandi logistics warehouse, Nagpur crane building, Farrukhnagar fulfilment warehouse, and the Bengaluru frozen-frame solar retrofit |
| 6–10 | Hyderabad storage mezzanine, Visakhapatnam crane hall, Chennai industrial portal, Shimla snow-loaded hall with attached lean-to, and Indore retail hall |
| 11–15 | Jaipur separate office and workshop, Chandigarh three-wing school, Delhi five-storey SCBF, Kolkata hospital, and Pune stepped EBF |
| 16–21 | Mumbai office moment frame, Ahmedabad laboratory SCBF, Kochi podium, Guwahati two-unit residential building, Noida office tower, and Hosur angle-truss shed |

## Reproduce a handoff

Install the India HR solver and its supported OpenSees Python runtime. Install this repository into that environment, with its drawing and IFC dependencies. Keep the India CFS clone available for the native IS 801 secondary-member checks. The `--jobs` directory stores the local producer reports and intermediate evidence. Use a location outside a public checkout because the native HR evidence contains private source retrievals.

```powershell
python validation/hr/run_case.py 6 7 8 --phase all --hr ../hr --cfs ../cfs --corpus C:/licensed/corpus_fixed --specs C:/licensed/specs/INDIA_STEEL/pdfs --jobs ../hr-jobs --output ../case-handoffs
python -m steltic_openbim_india deliver-job ../hr-jobs/IN_Ex7 --output ../published-sets/IN_Ex7
```

Pass any subset of the integers 1 through 21. `--phase preflight` runs the producer input checks. `--phase native` regenerates the local job with `pipeline.design_and_report` or `pipeline.design_units`. `--phase audit` rebuilds the physical declaration, binds the element geometry and material to the saved native model, and writes the portable files. The normal producer output is `design/openbim_handoff.json`. The composite cases retain each unit and its independent report and displacements under the parent job.

The audit requires a completed native calculation package, HTML report and final status for each independent unit. The versioned section selections, connection actions and supplementary dead-load schedules are inputs to this command. It also regenerates Pune’s companion with the full imposed floor loads. Each case includes global-coordinate contact samples that the acceptance runner checks against independently reopened IFC solids.

Examples 1–5 include an IFC survey of every purlin and girt bearing block and each required vehicle opening. Examples 6–10 and 21 include a survey of every fascia weld face and the strip of roof sheet beyond each rail. To repeat either survey on a generated model, run the matching command in the drawing environment.

```powershell
python validation/hr/verify_peb_bearings.py validation/hr/IN_Ex2/handoff.json ../published-sets/IN_Ex2/model.ifc --output ../published-sets/IN_Ex2/bearing-proof.json
python validation/hr/verify_eave_edges.py validation/hr/IN_Ex7/handoff.json ../published-sets/IN_Ex7/model.ifc --output ../published-sets/IN_Ex7/edge-verification.json
```

## Evidence and assumptions

The local design starts from the project geometry, occupancy and site in the active brief. Tributary screening selects initial sections. Steltic's `frame_build.attach_gold` function receives those bays, section groups and end releases as the native frame input. The native combination-level member forces, serviceability results, seismic detailing requirements and connection actions drive later trials. The section decision files preserve the prior numerical choices and calculations used to select the published trial. The solar retrofit holds the independently selected original shed fixed and separately checks full panel loading over the array.

In the moment-frame buildings, transverse restraints connect actual parallel framing lines at both flange levels. The native load model includes their steel weight at the supporting nodes. Each local check sizes the hot-finished tube for axial force and checks the available complete-penetration weld. The engineering record identifies the remaining end-shoe, diaphragm and receiving-web coordination. Chandigarh, Mumbai and Kochi carry the same restraint layout through their native analysis, drawing set and IFC.

Coordinates and physical section dimensions are in millimetres. Area loads are in kN/m², force records use N and moments use N·mm unless the field name gives a different unit. A composite joint uses the minimum clear distance between the outer steel surfaces and connection parts. The native displacement requirement is recorded separately from the grid-centre distance.

The one-way floor models declare the secondary beam direction and spacing used by the India engine. The sheets span across those beams. Installed deck soffits, clear column penetrations, cladding, bearing shoes and edge supports are located from actual section faces. The analytical grid and storey worklines remain available for setting out. `evidence.json` gives the installed elevations and measured volume-based steel weights. Each suspended level carries a separate supplementary dead load in the native gravity and seismic analysis. Explicit runway loads or cross-frame nodal loads can add conservatism where they cover some of the same steel.

Chandigarh’s link wing, Mumbai and Kochi use conditional fabricated bases. The exchange contains individual machined strips, full-depth effective fusion zones, triangular gussets and drilled perimeter anchor holes. Each involved foundation carries its own hardware dead weight directly. The numerical checks use the native concurrent axial forces, biaxial moments and capacity-design shear. They include elastic seam bending and shear at the shaft footprint. Mill material certificates, through-thickness toughness, the qualified shop welding procedure, ultrasonic examination, concrete group breakout, grout and pedestal reinforcement require project-specific approval. The check register identifies these items against the affected base occurrences.

The public grounding records contain document editions, relative locators, selected design quantities, and digests. Local licensed PDFs and raw corpus extracts remain in the owner's workspace. The source filename for IS 875 Part 4 contains `1987`; the supplied document is the 2021 third revision. Each case records proxy towns or figure interpretations where applicable. Supplier details, anchor development, foundation capacity, and local detailing assumptions retain their engineering review status in the model.
