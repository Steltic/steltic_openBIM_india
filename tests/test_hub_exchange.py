from pathlib import Path
import hashlib
import json

from fastapi.testclient import TestClient

from steltic_openbim_india.webapp import app


def test_hub_delivery_ifc_return_and_architectural_review(tmp_path, monkeypatch):
    src=Path(__file__).resolve().parents[1]/"src"
    monkeypatch.setenv("PYTHONPATH", str(src))
    monkeypatch.setenv("OPENBIM_JOBS", str(tmp_path/"openbim"))
    api=TestClient(app)
    assert api.get("/healthz").json()=={"ok":True}
    home=api.get("/ifc-import")
    assert home.status_code==200 and "Steltic openBIM India" in home.text
    assert api.get("/static/ifc_viewer.js").status_code==200
    project="/api/projects/Hub-test"
    fixture=Path(__file__).parent/"fixtures/metric_frame.json"
    issued=api.post(project+"/design",files={"file":("handoff.json",fixture.read_bytes(),"application/json")})
    assert issued.status_code==200,issued.text
    key=issued.json()["id"]
    assert issued.json()["artifact_check"]=="pass"
    data=api.get(f"{project}/{key}/files/model.ifc").content
    response=api.post(project+"/import",files={"file":("back.ifc", data, "application/octet-stream")})
    assert response.status_code==200,response.text
    imported=response.json()["id"]
    assert api.get(f"{project}/{imported}/files/original.ifc").content==data
    info=api.get(f"{project}/{imported}/files/inspection.json").json()
    assert info["schema"]=="IFC4" and info["units"]["scale_to_m"]==.001 and info["counts"]["products"]>0
    review=api.post(f"{project}/{imported}/review",json={"scope":"structural"})
    assert review.status_code==200,review.text
    model=api.get(f"{project}/{review.json()['id']}/files/review.json").json()
    assert model["counts"]["displayed"]>0 and model["counts"]["triangles"]>0
    result=api.post(f"{project}/{imported}/brief",json={"options":{"scope":"all"},"module":"HR","brief":"Test warehouse in Bengaluru."})
    assert result.status_code==200,result.text
    brief=api.get(f"{project}/{result.json()['id']}/files/architectural_geometry.json").json()
    assert brief["target_module"]=="HR" and brief["source_sha256"]==response.json()["source_sha256"]
    assert len(api.get(project).json())==4


def test_import_native_job_rejects_stale_calculation(tmp_path,monkeypatch):
    monkeypatch.setenv("PYTHONPATH",str(Path(__file__).resolve().parents[1]/"src"))
    root = tmp_path/"hr"
    snapshot = root/"Metric"/"design"
    snapshot.mkdir(parents=True)
    calc = snapshot/"calc_package.json"
    calc.write_bytes(b'{"units":{"length":"mm"}}')
    data=json.loads((Path(__file__).parent/"fixtures/metric_frame.json").read_bytes())
    data["source_evidence"] = {"files":{"design/calc_package.json":hashlib.sha256(calc.read_bytes()).hexdigest()}}
    (snapshot/"openbim_handoff.json").write_text(json.dumps(data),encoding="utf-8")
    monkeypatch.setenv("HR_JOBS",str(root))
    monkeypatch.setenv("OPENBIM_JOBS",str(tmp_path/"deliveries"))
    api=TestClient(app)
    assert {"module":"HR","job":"Metric"} in api.get("/api/sources").json()
    endpoint="/api/projects/Metric/sources/HR/Metric"
    issued=api.post(endpoint)
    assert issued.status_code==200,issued.text
    assert issued.json()["artifact_check"]=="pass"
    calc.write_bytes(b'{"changed":true}')
    assert api.post(endpoint).status_code==409
    assert len(api.get("/api/projects/Metric").json())==1


def test_drawing_answer_reissues_measured_opening_and_reopens_original(tmp_path, monkeypatch):
    import ifcopenshell

    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]/"src"))
    monkeypatch.setenv("OPENBIM_JOBS", str(tmp_path/"revisions"))
    client = TestClient(app)
    project = "/api/projects/Opening-review"
    fixture = Path(__file__).parent/"fixtures/metric_frame.json"
    original = client.post(project+"/design", files={"file": ("frame.json", fixture.read_bytes())}).json()

    def contents(key, file):
        return client.get(f"{project}/{key}/files/{file}").content

    def holes(key):
        model = ifcopenshell.file.from_string(contents(key, "model.ifc").decode())
        return len(model.by_type("IfcOpeningElement"))

    key = original["id"]
    register = json.loads(contents(key, "requests.json"))
    assert register["requests"][0]["id"] == "connection/K2" and register["panels"] == ["W1"]
    data = {"request_id":"opening/L1", "reviewer":"Architect", "panel":"W1", "action":"confirm opening",
            "note":"Louvre set-out from the south grid.", "outline":[[400,0,900],[950,0,900],[950,0,1400],[400,0,1400]]}
    defective = {**data, "outline":[[0,100,0],[450,110,0],[0,110,900]]}
    assert client.post(f"{project}/{key}/answers",json=defective).status_code == 422
    issued = client.post(f"{project}/{key}/answers", json=data)
    assert issued.status_code == 200, issued.text
    revised = issued.json()
    assert revised["artifact_check"] == "pass" and revised["parent_revision"] == key
    assert holes(revised["id"]) == holes(key) + 1
    actual = json.loads(contents(revised["id"], "handoff.json"))
    assert actual["drawing_revision"]["native_handoff_sha256"] == original["source_sha256"]
    assert actual["checks"][-1]["status"] == "review" and actual["panels"][0]["openings"][-1] == data["outline"]
    note = {**data, "outline":None, "action":"information", "note":"Supplier confirms the louvre model."}
    annotated = client.post(f"{project}/{revised['id']}/answers", json=note).json()
    assert holes(annotated["id"]) == holes(revised["id"])
    reopened = client.post(f"{project}/{annotated['id']}/answers", json={**note, "action":"reopen"}).json()
    assert holes(reopened["id"]) == holes(key) and reopened["base_revision"] == key
    assert contents(key,"handoff.json") == fixture.read_bytes()
    assert len(client.get(project).json()) == 4
