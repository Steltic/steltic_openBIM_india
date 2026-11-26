"use strict";
const byId = id => document.getElementById(id);
const tab = location.pathname.endsWith("/ifc-import") ? "import" : location.pathname.endsWith("/ifc-export") ? "export" : "design";
const project = new URLSearchParams(location.search).get("project") || "Project";
const api = "./api/projects/" + encodeURIComponent(project);
const link = (key, file) => api + "/" + key + "/files/" + file;
const addOption = (select, text, value) => select.add(new Option(text, value));
const clear = element => element.replaceChildren();
let viewer;
let requestData;

async function request(url, init) {
  const res = await fetch(url, init);
  const data = await res.json();
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed");
  return data;
}
function message(text, error = false) {
  byId("status").textContent = text;
  byId("status").classList.toggle("error", error);
}
function submit(id, work, progress) {
  const form = byId(id);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    message(progress);
    try { await work(form); await refresh(); message("Revision saved."); }
    catch (error) { message(error.message, true); }
    finally { button.disabled = false; }
  });
}
function downloadLinks(row, node) {
  for (const file of row.files) {
    const anchor = document.createElement("a");
    anchor.href = link(row.id, file);
    anchor.textContent = file;
    node.append(anchor);
  }
}
function record(row) {
  const node = document.createElement("article"), title = document.createElement("h3"), detail = document.createElement("p");
  node.className = "record";
  title.textContent = row.label;
  const fields = [row.kind, new Date(row.created).toLocaleString()];
  if (row.artifact_check) fields.push("Artifact check " + row.artifact_check, "Design " + row.engineering);
  detail.textContent = fields.join(" · ");
  node.append(title, detail);
  downloadLinks(row, node);
  return node;
}
async function showImport() {
  const key = byId("model").value;
  if (!key) return;
  const data = await request(link(key, "inspection.json"));
  const select = byId("storeys"), selected = select.value;
  clear(select); addOption(select, "All storeys", "all"); addOption(select, "Unassigned", "unassigned");
  for (const storey of data.storeys) addOption(select, storey.name, storey.id);
  if (Array.from(select.options).some(o => o.value === selected)) select.value = selected;
  byId("summary").textContent = [data.schema, data.units.name, data.counts.products + " products",
    data.storeys.length + " storeys", ...data.findings.map(f => f.title + " (" + f.count + ")")].join(" · ");
}
async function refresh() {
  const rows = await request(api);
  const history = byId("history");
  const filtered = rows.filter(r => tab === "export" || (tab === "design" ? r.kind === "design" : r.kind !== "design"));
  history.replaceChildren(...filtered.map(record));
  if (tab === "design") {
    const revisions = rows.filter(r => r.kind === "design" && r.files.includes("requests.json"));
    const select = byId("query-revision");
    clear(select);
    for (const row of revisions) addOption(select, row.label + " · " + row.id.slice(0, 8), row.id);
    byId("drawing-queries").hidden = !revisions.length;
    if (revisions.length && byId("drawing-queries").open) await showQueries();
  }
  if (tab !== "import") return;
  const imports = rows.filter(r => r.kind === "import"), select = byId("model"), selected = select.value;
  clear(select);
  for (const row of imports) addOption(select, row.label + " · " + row.id.slice(0, 8), row.id);
  if (imports.some(row => row.id === selected)) select.value = selected;
  byId("review-options").hidden = !imports.length;
  if (imports.length) await showImport();
}
async function showQueries() {
  const revision = byId("query-revision").value;
  if (!revision) return;
  const data = await request(link(revision, "requests.json"));
  if (revision !== byId("query-revision").value) return;
  requestData = data;
  const ids = byId("query-id"), form = byId("answer-form"), hosts = form.elements.panel;
  clear(ids); clear(hosts);
  for (const row of data.requests) addOption(ids, row.id + " · " + row.status, row.id);
  for (const row of data.answers.filter(r => r.request_id.startsWith("opening/"))) addOption(ids, row.request_id, row.request_id);
  for (const panel of data.panels) addOption(hosts, panel, panel);
  if (data.panels.length) addOption(ids, "Additional architectural opening", "new-opening");
  form.hidden = !ids.options.length;
  showResponse();
}
function showResponse() {
  const form = byId("answer-form"), selected = byId("query-id").value;
  const opening = selected === "new-opening" || selected.startsWith("opening/");
  const saved = requestData?.answers.find(r => r.request_id === selected);
  byId("query-description").textContent = requestData?.requests.find(r => r.id === selected)?.description || "";
  byId("saved-response").textContent = saved ? [saved.reviewer, saved.action, saved.note].join(" · ") : "";
  byId("opening-host").hidden = !opening;
  form.elements.mark.value = selected.startsWith("opening/") ? selected.slice(8) : "";
  form.elements.mark.required = opening;
  form.elements.mark.readOnly = !!saved;
  if (saved?.panel) form.elements.panel.value = saved.panel;
  form.elements.panel.disabled = !opening || !!saved;
  form.elements.action.options[1].disabled = !opening;
  form.elements.action.options[2].disabled = !saved;
  form.elements.action.value = opening ? "confirm opening" : "information";
  form.elements.points.value = saved?.outline?.map(p => p.join(", ")).join("\n") || "";
  form.elements.note.value = "";
  showPoints();
}
function showPoints() {
  const form = byId("answer-form"), confirm = form.elements.action.value === "confirm opening";
  byId("opening-points").hidden = !confirm;
  form.elements.points.required = confirm;
}
function post(url, data) {
  return request(url, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(data) });
}
function reviewOptions() {
  const result = Object.fromEntries(new FormData(byId("review-form")));
  result.group = result.group ? Number(result.group) : "all";
  return result;
}
async function start() {
  byId(tab).hidden = false;
  byId("project").value = project;
  for (const anchor of document.querySelectorAll("[data-tab]")) {
    const url = new URL(anchor.href); url.searchParams.set("project", project); anchor.href = url;
    if (anchor.dataset.tab === tab) anchor.setAttribute("aria-current", "page");
  }
  byId("project-form").onsubmit = event => {
    event.preventDefault(); const url = new URL(location.href); url.searchParams.set("project", byId("project").value); location.assign(url);
  };
  for (const kind of ["design","import"]) {
    submit(kind + "-form", async form => {
      const row = await request(api + "/" + kind, {method: "POST", body: new FormData(form)});
      if (kind === "import") { await refresh(); byId("model").value = row.id; viewer?.dispose(); clear(byId("viewer")); }
      form.reset();
    }, kind === "design" ? "Generating and checking the delivery…" : "Inspecting IFC…");
  }
  submit("job-form", () => request(api + "/sources/" + byId("source-jobs").value, {method:"POST"}), "Importing design job…");
  const jobs = tab === "design" ? await request("./api/sources") : [];
  byId("job-form").hidden = !jobs.length;
  for (const item of jobs) addOption(byId("source-jobs"), item.module + " / " + item.job, item.module + "/" + encodeURIComponent(item.job));
  byId("drawing-queries").ontoggle = () => { if (byId("drawing-queries").open) showQueries().catch(e => message(e.message, true)); };
  byId("query-revision").onchange = () => showQueries().catch(e => message(e.message, true));
  byId("query-id").onchange = showResponse;
  byId("answer-form").elements.action.onchange = showPoints;
  submit("answer-form", async form => {
    const fields = form.elements, selected = byId("query-id").value;
    const opening = selected === "new-opening" || selected.startsWith("opening/");
    const body = {request_id: selected === "new-opening" ? "opening/" + fields.mark.value.trim() : selected,
      reviewer: fields.reviewer.value, note: fields.note.value, action: fields.action.value};
    if (opening) body.panel = fields.panel.value;
    if (body.action === "confirm opening") {
      body.outline = fields.points.value.trim().split(/\n+/).map(line => line.trim().split(/\s*,\s*|\s+/).map(Number));
      if (body.outline.some(p => p.length !== 3 || !p.every(Number.isFinite))) throw new Error("Enter three finite coordinates per line.");
    }
    await post(api + "/" + byId("query-revision").value + "/answers", body);
  }, "Saving the response and checking the revised drawings…");
  byId("model").onchange = () => { viewer?.dispose(); clear(byId("viewer")); showImport().catch(e => message(e.message, true)); };
  submit("review-form", async () => {
    const row = await post(api + "/" + byId("model").value + "/review", reviewOptions());
    const model = await request(link(row.id,"review.json"));
    viewer?.dispose(); clear(byId("viewer")); viewer = window.StelticIFCViewer(byId("viewer"), model);
  }, "Building geometry review…");
  submit("brief-form", async form => {
    await post(api + "/" + byId("model").value + "/brief", {...Object.fromEntries(new FormData(form)), options:reviewOptions()});
  }, "Preparing design brief…");
  await refresh();
}
start().catch(error => message(error.message, true));
