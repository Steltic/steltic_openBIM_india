import json
from pathlib import Path

import ifcopenshell

from steltic_openbim_india.ifc import write_ifc


def test_measure_installed_contact_in_reopened_solids(tmp_path, monkeypatch):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/"tools"))
    from bearing_controls import measure

    data=json.loads((root/"tests/fixtures/metric_frame.json").read_bytes())
    # Column 2 ends at 3800 mm. The panel bottom is on its top end, over one flange.
    def plate(height):
        return [[5900,-180,height],[6100,-180,height],[6100,180,height],[5900,180,height]]
    data["panels"].append(dict(id="CAP",role="roof",material="Sheet",thickness_mm=6,outline=plate(3800)))
    source=data["project"]["id"]
    path=tmp_path/"contact.ifc"
    write_ifc(data,"1"*64,path)
    sample={"id":"column cap","chain":["COL-2","CAP"],"normal":[0,0,1],"stations_mm":[[6000,0,3800]],
            "expected_gaps_mm":[0],"tolerance_mm":.1}
    result=measure(ifcopenshell.open(str(path)),source,[sample])
    assert result["status"]=="pass" and result["samples"][0]["stations"][0]["measured_gaps_mm"]==[0.]
    data["panels"][-1]["outline"]=plate(3804)
    write_ifc(data,"2"*64,path)
    model=ifcopenshell.open(str(path))
    result=measure(model,source,[sample])
    assert result["status"]=="fail" and result["samples"][0]["stations"][0]["measured_gaps_mm"]==[4.]
    sample["stations_mm"]=[[6500,0,3800]]
    assert measure(model,source,[sample])["samples"][0]["stations"][0]["missing_material"]==["COL-2","CAP"]
