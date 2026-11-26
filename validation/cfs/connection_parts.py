"""Metric physical joint layouts selected for the benchmark design inputs."""
import math


def circ(u,v,r,place,n=16):
    return [place(u+r*math.cos(2*math.pi*i/n),v+r*math.sin(2*math.pi*i/n)) for i in range(n)]


def plate(points,t,holes=()):
    out=dict(kind="plate",material="Plate",outline=points,thickness_mm=t)
    if holes: out["openings"]=list(holes)
    return out


def bolt(a,b,d):
    return dict(kind="bolt",material="Bolt",start=a,end=b,diameter_mm=d)


def weld(a,b,leg):
    return dict(kind="weld",material="Weld",start=a,end=b,leg_mm=leg)


def base_parts(at,spec,section_mm,axis):
    x,y,z=at; B,L,T=(spec[k] for k in ("B_mm","L_mm","t_plate_mm"))
    an=spec["anchors"]; d=an["d_mm"]; embed=an["embedment"]["L_mm"]
    # For the portal minor coordinate is across the pair (Y). Major bending
    # separates groups along X at +/-f. For the HR two-axis base use four
    # symmetric groups with 6 anchors/group, centroids at (+/-f, +/-f_y).
    f=an["f_mm"]
    if an["n_total"]==8:
        xy=[(s*f,t) for s in (-1,1) for t in (-225,-75,75,225)]
    else:
        xy=[(sx*f+i,sy*an["f_y_mm"]+j) for sx in (-1,1) for sy in (-1,1)
            for i in (-90,0,90) for j in (-55,55)]
    plane=lambda u,v:[round(x+u,5),round(y+v,5),z-T]
    parts=[plate([plane(-B/2,-L/2),plane(B/2,-L/2),plane(B/2,L/2),plane(-B/2,L/2)],T,
                 [circ(u,v,(d+4)/2,plane) for u,v in xy])]
    parts.extend(bolt([x+u,y+v,z-T-embed],[x+u,y+v,z+d],d) for u,v in xy)
    if "stiffeners" in spec:
        stiff=spec["stiffeners"]; t=stiff["t_mm"]; h=stiff["h_mm"]
        breadth,depth=section_mm
        # Column strong-axis orientation comes from the native viewer.
        X,Y=(depth,breadth) if axis=="X" else (breadth,depth)
        for dim,face,width,edge in ((0,X/2,Y,B/2),(1,Y/2,X,L/2)):
            for sign in (-1,1):
                for off in (-(width-t)/2,0,(width-t)/2):
                    def vert(dv,dz):
                        return [x+sign*dv,y+off-t/2,z+dz] if dim==0 else [x+off-t/2,y+sign*dv,z+dz]
                    points=[vert(face,0),vert(edge,0),vert(face,h)]
                    # Consistent positive transverse plate extrusion.
                    if (dim==0 and sign==1) or (dim==1 and sign==-1): points.reverse()
                    parts.append(plate(points,t))
        # Shear lugs are two orthogonal balanced plates. Split the intersecting
        # leg at the crossing to avoid two overlapping fabricated solids.
        for lo,hi in ((-450,-80),(80,450)):
            parts.append(plate([[x+lo,y-80,z-T],[x+hi,y-80,z-T],[x+hi,y-80,z-T-350],[x+lo,y-80,z-T-350]],160))
        parts.append(plate([[x-80,y-450,z-T],[x-80,y-450,z-T-350],[x-80,y+450,z-T-350],[x-80,y+450,z-T]],160))
    return parts


def portal_gusset(at,axes,spec):
    """Two external gussets, bearing on both channel webs, one group per end."""
    from shapely.geometry import MultiPoint
    x,y,z=at; er=spec["edge_mm"]; d=spec["d_mm"]
    n,m=spec["cols"],spec["rows"]; sx,sz=spec["gauge_mm"],spec["pitch_mm"]
    reach=(n-1)*sx/2; height=(m-1)*sz/2
    extents=[]; centers=[]
    for dx,dz in axes:
        def point(u,v): return (round(dx*u-dz*v,5),round(dz*u+dx*v,5))
        for u in (45,45+2*(reach+er)):
            for v in (-height-er,height+er): extents.append(point(u,v))
        for i in range(n):
            for j in range(m): centers.append(point(45+er+i*sx,(j-(m-1)/2)*sz))
    hull=list(MultiPoint(extents).convex_hull.exterior.coords)[:-1]
    if sum(u*v2-u2*v for (u,v),(u2,v2) in zip(hull,hull[1:]+hull[:1]))<0: hull.reverse()
    t=12; web_pair_half=5
    parts=[]
    # A positive x-z winding has an outward normal of -Y.
    for face in (-web_pair_half,web_pair_half+t):
        local=lambda u,v:[round(x+u,5),y+face,round(z+v,5)]
        parts.append(plate([local(u,v) for u,v in hull],t,[circ(u,v,(d+2)/2,local) for u,v in centers]))
    for u,v in centers: parts.append(bolt([x+u,y-web_pair_half-t-6,z+v],[x+u,y+web_pair_half+t+6,z+v],d))
    return parts


def cleat_parts(a,b,spec,section,orientation,plies,seat_t):
    """One cleat and its two shop fillets, at the incoming end of one span."""
    x,y,z=a; length=math.dist(a,b); axis=[(v-u)/length for u,v in zip(a,b)]
    ux,uy,uz=axis; nx,ny,nz=orientation
    # The section depth direction is normal to the roof, in the web plane.
    vx=uy*nz-uz*ny; vy=uz*nx-ux*nz; vz=ux*ny-uy*nx
    if vz<0: vx,vy,vz=-vx,-vy,-vz
    norm=math.sqrt(vx*vx+vy*vy+vz*vz); vx,vy,vz=vx/norm,vy/norm,vz/norm
    dims=spec["cleat"]; bo=spec["bolts"]; t=dims["t_mm"]; w=dims["width_mm"]
    e=bo["edge_mm"]; p=bo["pitch_mm"]; d=bo["d_mm"]; bh=dims["bolt_height_mm"]
    # Seat datum is the lower edge of the purlin web. Cleat grips the web
    # face. Heights and local width are measured on the actual roof slope.
    h=bh+e; bot=-section["h"]/2; face=-section["b"]/2 if plies==1 else -section["t"]
    def pt(u,v,dist):
        return [round(i,5) for i in (x+u*ux+(v+bot)*vx+dist*nx,y+u*uy+(v+bot)*vy+dist*ny,z+u*uz+(v+bot)*vz+dist*nz)]
    centers=[((w-(bo["n"]-1)*p)/2+i*p,bh) for i in range(bo["n"])]
    loc=lambda u,v:pt(u,v,face)
    points=[loc(0,0),loc(w,0),loc(w,h),loc(0,h)]
    # Pick plate extrusion toward the cleat side of the purlin web.
    ncalc=[uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx]
    if sum(v*n for v,n in zip(ncalc,orientation))>0: points.reverse()
    parts=[plate(points,t,[circ(u,v,(d+2)/2,loc) for u,v in centers])]
    parts.extend(bolt(pt(u,v,face-t-3),pt(u,v,face+plies*section["t"]+4),d) for u,v in centers)
    parts.extend(weld(pt(0,0,j),pt(w,0,j),dims["weld_mm"]) for j in (face,face-t))
    transverse=[face-80,face+80]
    seat=[pt(0,-seat_t,transverse[0]),pt(w,-seat_t,transverse[0]),pt(w,-seat_t,transverse[1]),pt(0,-seat_t,transverse[1])]
    if (ux*ny-uy*nx)*vz+(uy*nz-uz*ny)*vx+(uz*nx-ux*nz)*vy<0:seat.reverse()
    parts.append(plate(seat,seat_t))
    # Two transverse fillets across the inner footprint of the supporting
    # rafter flange. The seat itself carries the part beyond that footprint.
    for u in (8,58): parts.append(weld(pt(u,-seat_t,transverse[0]),pt(u,-seat_t,transverse[1]),8))
    return parts


def beam_end_parts(a,b,fin,sec,support,cover=None):
    """Twin fin plates drilled for double shear, plus moment cover plates."""
    from steltic_openbim_india.geometry import frame
    side,up,axis=frame(a,b)
    def pt(u,v,w):
        return [round(o+i*(u+support)+j*v+k*w,5) for o,i,j,k in zip(a,axis,side,up)]
    bp=fin["bolts"]; d=bp["d_mm"]; n=bp["n_bolts"]; t=fin["t_plate_mm"]
    e=bp["e_mm"]; pitch=bp["p_mm"]; H=fin["h_plate_mm"]
    cols=max(2,math.ceil(n/(math.floor((H-2*e)/pitch)+1))); rows=math.ceil(n/cols);length=2*e+(cols-1)*pitch
    center=[(e+(k%cols)*pitch,(k//cols-(rows-1)/2)*pitch) for k in range(n)]
    parts=[]; half=float(sec["tw_mm"])/2
    for face in (half,-half-t):
        loc=lambda u,w:pt(u,face,w)
        parts.append(plate([loc(0,-H/2),loc(0,H/2),loc(length,H/2),loc(length,-H/2)],t,
                           [circ(u,w,bp["d0_mm"]/2,loc) for u,w in center]))
    for u,w in center: parts.append(bolt(pt(u,-half-t-5,w),pt(u,half+t+5,w),d))
    if cover:
        t=cover["plate_t_mm"]; width=cover["plate_b_mm"]; length=cover["weld"]["length_mm"]/2
        for z in (-float(sec["D_mm"])/2-t,float(sec["D_mm"])/2):
            parts.append(plate([pt(0,-width/2,z),pt(length,-width/2,z),pt(length,width/2,z),pt(0,width/2,z)],t))
            interface=z+t if z<0 else z
            for s in (-1,1): parts.append(weld(pt(0,s*width/2,interface),pt(length,s*width/2,interface),cover["weld"]["size_mm"]))
    return parts


def brace_end_parts(a,b,spec):
    """Gusset welded to the frame, twin brace cheeks, a single double-shear interface."""
    from steltic_openbim_india.geometry import frame
    side,depth,axis=frame(a,b)
    # For a wall brace the chosen width is within the vertical frame plane.
    # For roof-plane members take horizontal transverse direction instead.
    if abs(axis[2])<.25: width,normal=side,depth
    else: width,normal=depth,side
    def pt(u,v,n): return [round(o+ui*u+vi*v+ni*n,5) for o,ui,vi,ni in zip(a,axis,width,normal)]
    gus=spec["gusset"]; bolts=spec["bolts"]; d=bolts["d_mm"]; dia=bolts["d0_mm"]; pitch=bolts["p_mm"]
    t=gus["t_mm"]; cheek_t=max(16,math.ceil(t/2)); L=gus["L_conn_mm"]; W=gus["w_start_mm"]
    n=bolts["n_bolts"]; nx=spec.get("detailing",{}).get("nlong",min(10,math.ceil(math.sqrt(n*1.4)))); ny=math.ceil(n/nx)
    start=220; lo=start+(L-(nx-1)*pitch)/2; coords=[]
    for i in range(nx):
        count=n//nx+(i<n%nx)
        for j in range(count): coords.append((lo+i*pitch,(j-(count-1)/2)*pitch))
    parts=[]
    for offset,th,umin,umax in ((-t/2,t,0,start+L),(-t/2-cheek_t,cheek_t,start,start+L+150),(t/2,cheek_t,start,start+L+150)):
        loc=lambda u,v:pt(u,v,offset)
        outline=[loc(umin,-W/2),loc(umax,-W/2),loc(umax,W/2),loc(umin,W/2)]
        from steltic_openbim_india.geometry import cross,dot
        if dot(cross(axis,width),normal)<0: outline.reverse()
        parts.append(plate(outline,th,[circ(u,v,dia/2,loc) for u,v in coords]))
    parts.extend(bolt(pt(u,v,-t/2-cheek_t-5),pt(u,v,t/2+cheek_t+5),d) for u,v in coords)
    return parts


def truss_end_parts(a,b,spec,sec):
    """A single angle leg bolted to its node gusset at the design gauge."""
    from steltic_openbim_india.geometry import frame,cross,dot
    width,depth,axis=frame(a,b)
    def pt(dist,v,n):return [round(k+dist*u+v*w+n*f,5) for k,u,w,f in zip(a,axis,width,depth)]
    bolts=spec["n_bolts"]; pitch=spec["pitch_mm"]; e=spec["end_mm"]; g=spec["gauge_mm"]
    t=spec["gusset_t_mm"]; edge=spec["gusset_edge_mm"]; length=(bolts-1)*pitch+2*e
    center=-float(sec["B_mm"])/2+g; face=-float(sec["D_mm"])/2
    loc=lambda u,v:pt(u,v,face)
    outline=[loc(0,center-edge),loc(length,center-edge),loc(length,center+edge),loc(0,center+edge)]
    if dot(cross(axis,width),depth)>0: outline.reverse()
    parts=[plate(outline,t,[circ(e+i*pitch,center,spec["d0_mm"]/2,loc) for i in range(bolts)])]
    parts.extend(bolt(pt(e+i*pitch,center,face-t-4),pt(e+i*pitch,center,face+float(sec["tf_mm"])+4),spec["d_mm"]) for i in range(bolts))
    return parts
