"""Independent dimensional controls transcribed from the 36 active project briefs.

These are global column-grid spans, highest specified steel datum, and horizontal
roof areas. The latter catches a solid rectangle substituted for an irregular plan.
Numbers are metres and square metres. A range records unspecified layout dimensions.
"""

HR = {
    1:(30,75,11.5,2250), 2:(96,108,15.4,10368), 3:(24,60,11.2,1440), 4:(30,90,12,2700),
    5:(30,75,11.5,2250), 6:(18,32,9,576), 7:(21,72,12.55,1512), 8:(24,36,9.2,864),
    9:(36,60,11,1800), 10:(90,60,10,5400),
    11:{"Office":(30,22.5,15,675), "Workshop":(30,15,10.8,450)},
    12:{"Classroom":(25.5,17,10.8,433.5), "Link":(17,17,7.2,289), "Gym":(17,17,8,289)},
    13:(30,24,18,720), 14:(37.5,30,28.8,1125), 15:(63,45,32.1,2106), 16:(30,30,31.5,900),
    17:(51,34,36.9,1734), 18:(36,27,39.6,972),
    19:{"Flange":(51,17,39.4,867), "Stem":(17,17,39.4,289)},
    20:(27,18,59.8,486), 21:(18,36,8.75,648)
}
CFS = {
    1:(48,18,(6.01,10),864), 2:(76,21,9,1596), 3:(24,30,8.4,720),
    4:(30,36,(7.3,10),1008), 5:(49,31,(8.7,12),700), 6:(37,21,(12.9,15),777),
    7:(12,8,12,96), 8:(43,40,(11.86,17),966), 9:(52,20,(11.91,17),(790,1039.5)),
    10:(24,12,15,288), 11:(55,46,(14.61,20),1558), 12:(36,12,18.3,432), 13:(74,36,17.8,1656),
    14:(64,40,23,(900,2560)), 15:(46,46,23.3,1332)
}


def run(family, number, measurements):
    requirements = (HR if family=="hr" else CFS)[number]
    expected = requirements if isinstance(requirements,dict) else {"Main":requirements}
    records = []
    def check(unit, label, observed, wanted, tolerance=.002):
        bounds = wanted if isinstance(wanted,tuple) else (wanted,wanted)
        ok = observed is not None and bounds[0]-tolerance <= observed <= bounds[1]+tolerance
        records.append({"unit":unit, "control":label, "required":wanted, "measured":observed, "pass":ok})
    check("project","independent unit count",len(measurements),len(expected),0)
    for unit,(width,length,top,area) in expected.items():
        model = measurements.get(unit,{})
        spans = model.get("column_spans_mm",[])
        for axis,name,target in [(0,"column span X (m)",width),(1,"column span Y (m)",length)]:
            check(unit,name,spans[axis]/1000 if spans else None,target)
        maximum = model.get("maximum_steel_workline_z_mm")
        check(unit,"upper steel datum (m)",maximum/1000 if maximum is not None else None,top)
        check(unit,"union of roof projections (m²)",model.get("roof_plan_union_m2"),area,.1)
        if (family=="hr" and number in (1,2,3,4,5,7,8,9,10,21)) or (family=="cfs" and number in (1,2,3,8,9,11)):
            check(unit,"pitched roof faces",model.get("pitched_roof_panels"),(1,10**6),0)
        if family=="cfs" and number==6:
            check(unit,"south walkout diaphragm at +3.0 m (m²)",model.get("floor_net_plan_m2_by_elevation_mm",{}).get("3000"),388.5,.1)
        if family=="cfs" and number==14:
            floors=model.get("floor_net_plan_m2_by_elevation_mm",{})
            check(unit,"full podium floor at +4.0 m (m²)",floors.get("4000"),2560,.1)
            upper=floors.get("11000")
            check(unit,"upper U floor and north courtyard at +11.0 m (m²)",upper,(900,2500),.1)
    return {"status":"pass" if all(r["pass"] for r in records) else "fail","controls":records}
