"""Fit the secondary framing and deck to the primary steel's actual upper face."""
from collections import defaultdict
import math

from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree
from steltic_openbim_india.geometry import dot, frame, plane, sub
from steltic_openbim_india.profiles import section_polygons


def shift(point, dz):
    return [point[0],point[1],round(point[2]+dz,4)]


def move_joint(joint,dz):
    joint["at"]=shift(joint["at"],dz)
    for part in joint.get("parts",[]):
        for key in ("start","end"):
            if key in part:part[key]=shift(part[key],dz)
        if "outline" in part:part["outline"]=[shift(p,dz) for p in part["outline"]]
        if "openings" in part:part["openings"]=[[shift(p,dz) for p in ring] for ring in part["openings"]]


class Sections:
    def __init__(self,layout,pkg):
        from openbim_handoff import _catalog, _rolled_sections
        self.records=_catalog(pkg)[0]
        self.rolled=_rolled_sections()
        self.profiles=layout["profiles"].copy()
        self.shapes={}

    def profile(self,m):
        from openbim_handoff import _profile
        if m.get("native_ref"):
            record=self.records[m["native_ref"]]
            sec=record["section"]; count=int(record.get("n_ply") or 1)
            label=(f"{count}x" if count>1 else "")+sec
            if label not in self.profiles:self.profiles[label]=_profile(sec,count,self.rolled,section_polygons)
        else:label=m["profile"]
        if label not in self.shapes:self.shapes[label]=section_polygons(self.profiles[label])
        return label,self.shapes[label]

    def limits(self,m,normal):
        name,shapes=self.profile(m)
        w,d,_=frame(m["start"],m["end"],m.get("ref_direction"))
        wx,wy=dot(w,normal),dot(d,normal)
        vals=[x*wx+y*wy for p in shapes for x,y in p.exterior.coords]
        return min(vals),max(vals)


ROOF={"Roof","Amenity deck"}
FLOOR={"Floor","Exterior walkway","Mezzanine floor"}
PODIUM={"Podium floor"}


def install_flat(model,pkg):
    """Standing joists bear on the beam flange. Roof purlins bear through their selected seat."""
    shapes=Sections(model,pkg); up=(0.,0.,1.)
    faces=[]; levels=defaultdict(list)
    for panel in model["panels"]:
        if panel["role"] not in ROOF|FLOOR|PODIUM:continue
        z=panel["outline"][0][2]
        if max(abs(p[2]-z) for p in panel["outline"])>.1:continue
        if plane(panel["outline"])[3][2]<0:panel["outline"].reverse()
        index=len(faces);faces.append(panel)
        levels[round(z,1)].append(index)
    footprints=[Polygon([(p[0],p[1]) for p in f["outline"]]) for f in faces]
    tree=STRtree(footprints)
    beams=defaultdict(list); cleats=defaultdict(list)
    for joint in model["connections"]:
        if joint["type"]=="Purlin cleat":cleats[joint["members"][0]].append(joint)
    for m in model["members"]:
        a,b=m["start"],m["end"]
        if m["role"] not in ("beam","mezzanine beam") or abs(a[2]-b[2])>.1:continue
        j=0 if abs(b[0]-a[0])>abs(b[1]-a[1]) else 1
        line=(round(a[2],1),j,round(a[1-j],1))
        beams[line].append((min(a[j],b[j]),max(a[j],b[j]),m))
    samples={}; stats=defaultdict(list)
    panel_heights=defaultdict(set)

    def sample(typ,chain,station,datum,offset):
        if typ in samples:return
        samples[typ]=dict(id=typ,chain=chain,normal=list(up),stations_mm=[station],
             expected_gaps_mm=[0.]*(len(chain)-1),tolerance_mm=1.,structural_datum_mm=datum,
             panel_underside_above_datum_mm=round(offset,3))
    def receiver(z,which,q):
        row=beams.get((round(z,1),which,round(q[1-which],1)),[])
        return [(lo,hi,m) for lo,hi,m in row if lo-.05<=q[which]<=hi+.05]
    def covers(q,z,roles):
        p=Point(q[:2]);return [int(i) for i in tree.query(p) if faces[int(i)]["role"] in roles
            and abs(faces[int(i)]["outline"][0][2]-z)<.1 and footprints[int(i)].covers(p)]

    for m in model["members"]:
        role=m["role"]
        if role not in ("joist","purlin"):continue
        a,b=m["start"],m["end"]
        if abs(a[2]-b[2])>.1:continue
        z=a[2]; delta=sub(b,a);along=0 if abs(delta[0])>abs(delta[1]) else 1
        plane_roles=ROOF if role=="purlin" else FLOOR
        midpoint=[(x+y)/2 for x,y in zip(a,b)]
        panel_ids=covers(midpoint,z,plane_roles)
        if role=="joist" and any(f["role"]=="Exterior walkway" for f in faces):
            run=LineString([a[:2],b[:2]])
            panel_ids=[int(i) for i in tree.query(run) if faces[int(i)]["role"] in plane_roles
                       and abs(faces[int(i)]["outline"][0][2]-z)<.1 and
                       footprints[int(i)].intersection(run).length>.1]
        if not panel_ids:continue
        supports=[]
        for end,other in ((a,b),(b,a)):
            peers=receiver(z,1-along,end)
            if not peers:raise ValueError(f'{m["id"]} has no steel bearing at {end}')
            supports.append((end,other,peers))
        lowers,upper=shapes.limits(m,up)
        top=max(shapes.limits(r,up)[1] for _,_,ps in supports for _,_,r in ps)
        joints=cleats[m["id"]] if role=="purlin" else []
        seat=next((p["thickness_mm"] for p in reversed(joints[0]["parts"]) if p["kind"]=="plate"),0) if joints else 0
        lift=top+seat-lowers
        panel_raise=lift+upper
        for i in panel_ids:panel_heights[i].add(round(panel_raise,4))
        for end,other,peers in supports:
            for lo,hi,host in peers:
                host_height=shapes.limits(host,up)[1]
                if abs(host_height-top)>.1:raise ValueError(f'{m["id"]} needs packing for unequal receiver heights')
            # Select an interior flange point, on the supported side of the span
            # end and the adjacent side of the receiver at the boundary grid.
            lo,hi,host=max(peers,key=lambda item:item[1]-item[0])
            station=list(end)
            station[along]+=40*(1 if other[along]>end[along] else -1)
            lateral=1-along
            station[lateral]+=12*(1 if hi-end[lateral]>=lo*-1+end[lateral] else -1)
            station[2]=z+top
            idx=covers(station,z,plane_roles)
            if not idx:continue
            panel=faces[idx[0]]
            chain=[host["id"]]
            if joints:
                j=min(joints,key=lambda item:math.dist(item["at"],end))
                sp=next(p for p in reversed(j["parts"]) if p["kind"]=="plate")
                chain.append(sp["id"])
                if host["id"] not in j["members"]:j["members"].append(host["id"])
            chain+=[m["id"],panel["id"]]
            typ=panel["role"]+" / "+shapes.profile(host)[0]+" / "+shapes.profile(m)[0]
            sample(typ,chain,station,z,panel_raise)
            stats[typ].append(panel_raise)
        for joint in joints:move_joint(joint,lift)
        m["start"],m["end"]=shift(a,lift),shift(b,lift)
        m["analysis_workpoints_mm"]=[a,b]

    for i,panel in enumerate(faces):
        z=panel["outline"][0][2]
        if panel["role"] in PODIUM:
            p=panel["outline"]
            centre=[(p[0][0]+p[2][0])/2,(p[0][1]+p[2][1])/2,z]
            bottom_line=[centre[0],p[0][1],z]
            matches=receiver(z,0,bottom_line)
            if not matches:raise ValueError(f'{panel["id"]} has no podium girder')
            host=matches[0][2]
            dz=shapes.limits(host,up)[1]
            station=[bottom_line[0],bottom_line[1]+(10 if centre[1]>bottom_line[1] else -10),z+dz]
            typ=panel["role"]+" / "+shapes.profile(host)[0]
            sample(typ,[host["id"],panel["id"]],station,z,dz)
            stats[typ].append(dz)
        else:
            offsets=panel_heights[i]
            if len(offsets)!=1:raise ValueError(f'{panel["id"]} has {len(offsets)} incompatible support planes')
            dz=next(iter(offsets))
        panel["analysis_plane_mm"]=[p[:] for p in panel["outline"]]
        panel["outline"]=[shift(p,dz) for p in panel["outline"]]
    if samples:
        model["assumptions"].append("Native levels are analytic structural worklines. Floor joists bear on girder flanges; "
            "roof purlins bear through their detailed seats. The issued board or roof skin starts on the upper flange. "
            "Supplier floor retention, deck fasteners and the podium deck/slab specification remain project inputs.")
    return list(samples.values()),{k:dict(samples=len(v),min_panel_underside_offset_mm=min(v),
                                             max_panel_underside_offset_mm=max(v)) for k,v in stats.items()}
