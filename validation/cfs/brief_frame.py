"""Project-declared topology beyond the stock JSON bay builder.

The engineering engine owns model formation, member checks and demand recovery.
Only the roof members and the double-height return braces are specified here.
"""
def attach(cfg,spec):
    import frame_build
    frame_build.attach(cfg,spec)
    cfg["custom_build"]=build
    cfg["benchmark_geometry"]=spec["gold"]["benchmark_geometry"]
    if cfg["benchmark_geometry"]=="west_truss":
        original=cfg["_gold"]["beam_sec"]
        def choose(i,j,k,d):
            if k==4 and d=="Y" and i in cfg["roof_planes"][0]["lines"] and 1<=j<=4:
                return "NPB240X120X34.32"
            return original(i,j,k,d)
        cfg["_gold"]["beam_sec"]=choose


def build(cfg,transf="PDelta"):
    import engine3d as E
    import frame_build as FB
    import openseespy.opensees as ops
    import roof_geometry as roof
    import sections
    # The native static replay matches the ordered structural element list
    # to construction calls. Roof diaphragms create auxiliary spring elements
    # outside that list. Emit those constraints after ALL structural members,
    # in the same order as the stock builder's own frame. Each CFS lateral
    # job has a dedicated analysis subprocess.
    which=cfg["benchmark_geometry"]
    ties=[]; tie=roof.tie_diaphragm; original_rafters=roof.add_plane_members
    try:
        roof.tie_diaphragm=lambda *args:ties.append(args)
        if which=="cold_shed": roof.add_plane_members=cold_shed_rafters
        # Occupied multi-storey buildings have a physical horizontal ceiling
        # diaphragm with a trussed roof above. All floor-level grid nodes
        # belong to that plane in BOTH the rigid and flexible models. The
        # stock eave-spread portal detail is reserved for the open sheds.
        source=cfg if which in ("shed","cold_shed") else dict(cfg,roof_planes=[])
        info=FB.frame_build(source,transf)
    finally:
        roof.tie_diaphragm=tie
        roof.add_plane_members=original_rafters
    members=info["ele"]
    tag=1+max(m[0] for m in members)
    if which in ("west_truss","high_bay","wing_truss"):
        tag=add_roof(cfg,info,tag)
    if which in ("shed","high_bay"):
        section=cfg["brace"]; area=sections.props(section)["A"]
        ends=[]
        if which=="shed":
            for i in (0,2,cfg["NX"]-3,cfg["NX"]-1):
                for j in (0,1):
                    ends.append((E.ntag(i,j,1),roof.apex_tag(1,0,i+1)))
                    ends.append((E.ntag(i+1,j,1),roof.apex_tag(1,0,i)))
        else:
            # South is a moment-framed open face. Brace its returns and two
            # internal transverse lines from foundation to full eave height.
            for i in (0,5):
                for j in (0,3):
                    ends.extend([(E.ntag(i,j,0),E.ntag(i,j+1,2)),(E.ntag(i,j+1,0),E.ntag(i,j,2))])
            for j in (1,3):
                for i in (0,4):
                    ends.extend([(E.ntag(i,j,0),E.ntag(i+1,j,2)),(E.ntag(i+1,j,0),E.ntag(i,j,2))])
        for a,b in ends:
            ops.element("Truss",tag,a,b,area,1)
            members.append((tag,"brace",section,a,b))
            tag+=1
    for args in ties: tie(*args)
    return info


def cold_shed_rafters(cfg,k,XY,present_k,tag,members,**unused):
    """Six equal roof strips allow short, checked angle struts between rafters.

    The roof struts are outside the two vertical EBFs. Each small X terminates
    on a real rafter station. No lateral restraint is assumed at its crossing.
    """
    import openseespy.opensees as ops
    import engine3d as E
    import roof_geometry as R
    pl=R.planes_at(cfg,k)[0]; shafts=[]
    for i in pl["lines"]:
        line=[]; xx=pl["lcoord"][i]
        for h in range(7):
            yy=pl["lo"]+(pl["hi"]-pl["lo"])*h/6
            if h in (0,6): nn=E.ntag(i,0 if h==0 else 1,k)
            else:
                nn=R.apex_tag(k,0,i) if h==3 else k*100000+85000+i*10+h
                ops.node(nn,xx,yy,R.surface_z(pl,yy))
            line.append(nn)
        for a,b in zip(line,line[1:]):
            sec=pl["raw"]["rafter_sec"];E.add_beam(tag,a,b,sec);members.append((tag,"beam",sec,a,b));tag+=1
        shafts.append(line)
    for i,(first,last) in enumerate(zip(shafts,shafts[1:])):
        sec=pl["raw"]["ridge_sec"];E.add_beam(tag,first[3],last[3],sec,releases=("both","none"));members.append((tag,"beam",sec,first[3],last[3]));tag+=1
        if i not in (0,4,len(shafts)-6,len(shafts)-2): continue
        for h in range(6):
            for a,b in ((first[h],last[h+1]),(last[h],first[h+1])):
                sec="ISA200X200X20"
                E.add_truss(tag,a,b,sec,group="roof_plan",truss=f"roof-{i+1}")
                members.append((tag,"truss",sec,a,b));tag+=1
    return tag


def add_roof(cfg,info,tag):
    import engine3d as E
    import openseespy.opensees as ops
    import roof_geometry as R
    lvl=len(cfg["heights"]); members=info["ele"]
    for p in R.planes_at(cfg,lvl):
        grid=[(j,yy) for j,yy in enumerate(cfg["ycoords"]) if p["lo"]<=yy<=p["hi"]]
        ys=sorted({yy for _,yy in grid}|{p["ridge"]}); j_at={yy:j for j,yy in grid}
        prev={}
        for i in p["lines"]:
            bottom={yy:E.ntag(i,j,lvl) for j,yy in grid}; top={}
            if not all(n in ops.getNodeTags() for n in bottom.values()): continue
            tid=f"roof-{p['idx']+1}-{i+1}"; xx=p["lcoord"][i]
            for h,yy in enumerate(ys):
                if yy in (p["lo"],p["hi"]): top[yy]=bottom[yy];continue
                nn=lvl*100000+50000+p["idx"]*5000+i*100+h
                ops.node(nn,xx,yy,R.surface_z(p,yy));top[yy]=nn
            for ya,yb in zip(ys,ys[1:]):
                a,b=top[ya],top[yb];sec=p["raw"]["rafter_sec"]
                E.add_beam(tag,a,b,sec);members.append((tag,"beam",sec,a,b))
                tag+=1
            for yy,nn in top.items():
                if yy in (p["lo"],p["hi"]):continue
                # A web connects each top station to the ceiling chord.
                # Connect a non-grid ridge to the panel points on either side.
                adjacent=[yy] if yy in bottom else [max(v for v in bottom if v<yy),min(v for v in bottom if v>yy)]
                if yy in bottom and yy!=p["ridge"]:
                    inside=[v for v in bottom if yy<v<=p["ridge"]] if yy<p["ridge"] else [v for v in bottom if p["ridge"]<=v<yy]
                    if inside: adjacent.append(min(inside,key=lambda val:abs(val-yy)))
                for yy0 in adjacent:
                    grp="vertical" if yy==yy0 else "diagonal";sec="ISA200X200X20"
                    E.add_truss(tag,bottom[yy0],nn,sec,group=grp,truss=tid)
                    members.append((tag,"truss",sec,bottom[yy0],nn));tag+=1
                if yy in prev:
                    sec=p["raw"]["ridge_sec"];E.add_beam(tag,prev[yy],nn,sec,releases=("both","none"))
                    members.append((tag,"beam",sec,prev[yy],nn));tag+=1
            prev=top
    return tag
