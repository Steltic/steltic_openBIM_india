# Publish the India design examples

Each existing website entry has a native calculation report, a physical model and an analytical view. The physical model contains the steel members and panels from the issued IFC4. Select a member to read its section, material, workline length, IFC GlobalId and linked source checks. The complete building download contains the connection hardware and drawings. Composite HR buildings have a physical scene for each independently calculated unit.

The acceptance manifest identifies the issued handoff, IFC and delivery archive by SHA-256. The scene exporter reopens that IFC, triangulates its solid representations with their actual cuts, and preserves each occurrence placement. Repeated geometry shares a glTF mesh. The standalone reader checks the exported accessors, material and profile identities, cutback extents and panel coordinates against the handoff.

```sh
python tools/website/scene.py --validation validation --out stage/solutions_india/openbim
python tools/website/verify_scenes.py --validation validation --scenes stage/solutions_india/openbim
```

Prepare the calculation reports from verified native jobs in a separate publication directory. The India Hub's `design-indexes` command supplies the fresh HR and CFS catalogs and route map. Rebuild the analytical pages with the India HR and CFS viewer exporters. Save each HR page under `hr-views/<case>/<unit>.html` and each CFS viewer tree under `cfs-views/<case>/`. The `mathjax-3.2.2.tgz` argument is the original npm release archive. The staging tool verifies it and includes its SVG equation renderer and license.

```sh
python tools/website/stage_pages.py --validation validation --routes catalogs/path-map.json --catalogs catalogs --hr-jobs hr-jobs --cfs-jobs cfs-jobs --hr-views hr-views --cfs-views cfs-views --stage stage --mathjax mathjax-3.2.2.tgz --revision 'India openBIM design examples'
```

The physical model remains at `viewer_3d.html`. `analysis.html` presents the native force and design results. Each `report.html` gives the scope of the native checks and the whole-building coordination decision. The 14 hybrid CFS buildings retain their lateral-frame companion routes. The Bengaluru PV report includes the failed local purlin assessment and the installer’s note.

Use `site/build_site.py capture-design-baseline` and `publish-designs` in the India Hub to produce the upload and rollback ZIPs from `stage/publication.json`. To test the extracted site, run the optional browser check with Playwright, Pillow and a local Chromium-family browser. It checks all current report/viewer pairs and the historical CFS companion routes with external requests blocked.

```sh
python tools/website/browser_check.py --browser /path/to/chromium --root release/public_html --routes catalogs/path-map.json --out browser-results.json
```
