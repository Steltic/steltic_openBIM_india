"""Locate the PEB envelope from supporting steel faces and the fixed structural worklines."""
import math
from collections import defaultdict

from shapely.geometry import LineString
from steltic_openbim_india.geometry import cross,dot,frame,sub,unit
from steltic_openbim_india.profiles import section_polygons


def plus(at,direction,distance):
    return [round(v+d*distance,4) for v,d in zip(at,direction)]


def flange(profile,positive):
    """Midpoint of material in the requested Z flange, clear of toe and bend."""
    poly=section_polygons(profile)[0];xmin,ymin,xmax,ymax=poly.bounds
    t=profile['dimensions_mm']['tw'];yf=ymax-t/2 if positive else ymin+t/2
    cuts=poly.intersection(LineString([(xmin-1,yf),(xmax+1,yf)]))
    if cuts.geom_type=='MultiLineString':cuts=max(cuts.geoms,key=lambda g:g.length)
    return tuple(cuts.interpolate(.5,normalized=True).coords[0])


def depth(m,profiles,fraction):
    a=profiles[m['profile']]['dimensions_mm']['d'];b=profiles[m.get('end_profile',m['profile'])]['dimensions_mm']['d']
    return a+(b-a)*fraction


def contact(m,profiles,at,n):
    """Intersect an outward normal ray with the upper/outer primary flange surface.

    A linear-depth I has a planar outside face between its actual swept end profiles.
    Its taper changes the face normal as well as its end elevations.
    """
    a,b=m['start'],m['end'];w,deep,axis=frame(a,b,m.get('ref_direction'));p=profiles[m['profile']]['dimensions_mm'];
    if abs(dot(n,deep))<.7:raise ValueError(f"{m['id']}: requested support is away from its flange face")
    outward=deep if dot(n,deep)>0 else [-x for x in deep]
    p0=plus(a,outward,depth(m,profiles,0)/2);p1=plus(b,outward,depth(m,profiles,1)/2)
    norm=unit(cross(w,sub(p1,p0)));den=dot(norm,n)
    return plus(at,n,dot(norm,sub(p0,at))/den)


def rooflights(model,roof_offset):
    n=model.case.number
    if n not in (1,2,4,5):return
    u=model.u;w=u.nx*u.sx*1000;bay=u.sy*1000;panels=model.data['panels']
    roofs=sorted((p for p in panels if p['role']=='roof sheeting' and p['unit']==u.name),key=lambda p:min(v[0] for v in p['outline']))
    model.materials['DAYLIGHT']=dict(grade='Translucent profiled polycarbonate, 1.5 mm trial',standard='Envelope supplier selection')
    bands=math.ceil(.04*w/1200);strip=.04*w/bands
    centers=[.445*w] if n in (1,5) else [(i+1)*w/(2*(bands+1)) for i in range(bands)]
    for side,roof in enumerate(roofs):
        for band,center in enumerate(centers,1):
            x=w-center if side else center
            for j in range(u.ny):
                yc=(j+.5)*bay;half=.1875*bay
                ring=[[cx,cy,model.roof_z(cx)+roof_offset] for cx,cy in ((x-strip/2,yc-half),
                    (x+strip/2,yc-half),(x+strip/2,yc+half),(x-strip/2,yc+half))]
                roof.setdefault('openings',[]).append([list(p) for p in reversed(ring)])
                model.panel('rooflight',ring,1.5,'DAYLIGHT',f'ROOFLIGHT-{side+1}-{band}-{j+1}')
    model.data['assumptions'].append('Rooflight openings and separate translucent sheets occupy 3% of the gross main roof in plan and on the slope. Producer design uses a 1.5 mm polycarbonate envelope allowance; the supplier confirms sheet grade, curb and trimmer details, fall protection, overlaps, fasteners and watertight seals.')


def place(model):
    data=model.data;u=model.u;profiles=data['profiles'];length=u.ny*u.sy*1000;width=u.nx*u.sx*1000
    rise=2*model.case.rise*1000/width;factor=math.hypot(1,rise);h=model.datums[-1]
    ms=[m for m in data['members'] if m['unit']==u.name];roofs=defaultdict(list);walls=defaultdict(list);canopies=defaultdict(list)
    secondaries=[m for m in ms if m['role'] in ('purlin','girt','canopy purlin')]
    for m in ms:
        a,b=m['start'],m['end'];j=round((a[1]-model.offset[1])/(u.sy*1000))
        if m['role'] in ('gable rafter','rafter'):roofs[j].append(m)
        if m['role']=='canopy':canopies[j].append(m)
        if m['role']=='column' and (abs(a[0])<.1 or abs(a[0]-width)<.1):walls[j,abs(a[0])>.1].append(m)
    if not roofs or not walls:raise ValueError('PEB envelope requires actual rafters and both exterior portal columns')
    roof_depth=max(depth(m,profiles,i) for rows in roofs.values() for m in rows for i in (0,1));
    col_depth=max(depth(m,profiles,i) for rows in walls.values() for m in rows for i in (0,1))
    zdepth={role:max(profiles[m['profile']]['dimensions_mm']['d'] for m in secondaries if m['role']==role) for role in {r['role'] for r in secondaries}}
    # Cold-formed open Z sections are located by their measured extremal faces. A
    # 16 mm minimum thickness leaves steel at the thinnest end of a tapered block.
    roof_offset=(roof_depth/2+16+zdepth['purlin'])*factor
    wall_offset=col_depth/2+16+zdepth['girt']
    model.peb_roof_steel_offset_mm=roof_offset
    stations={};seats={};flange_points={};gaps=[]
    def target(rows,cap,normal):
        matches=[]
        for m in rows:
            p=contact(m,profiles,cap,normal);axis=frame(m['start'],m['end'],m.get('ref_direction'))[2]
            station=dot(sub(p,m['start']),axis);length=math.dist(m['start'],m['end'])
            matches.append((min(station,length-station),m['id'],m))
        return max(matches)[2] if matches else None
    for m in secondaries:
        role=m['role'];a=m['start'][:];b=m['end'][:];wall=role=='girt';can=role=='canopy purlin'
        right=a[0]>width/2;wall_sign=1 if right else -1;slope=rise*(-1 if right else 1)
        if can:slope=-1/30
        tangent=unit((1,0,slope));n=(wall_sign,0,0) if wall else unit((-slope,0,1))
        if not wall:m['ref_direction']=[-q for q in tangent]
        if can and '-CAN-PU-8-' in m['id']:
            # The lower Z outstand points towards the free edge. Bring this last
            # line 80 mm back along the roof so its full block bears on the actual
            # 6 m cantilever. This shortens the final tributary interval.
            a=plus(a,tangent,-80);b=plus(b,tangent,-80)
        dim=profiles[m['profile']]['dimensions_mm'];t=dim['tw'];pdepth=dim['d']
        delta=(col_depth/2+16+pdepth/2) if wall else ((16+pdepth/2) if can else roof_depth/2+16+pdepth/2)
        # The old canopy purlin datum follows the top of its tapered beam already.
        # The supplied piece's two endpoints are at the same station on a longitudinal run.
        for field,p in [('start',a),('end',b)]:m[field]=plus(p,n,delta)
        m['basis']='Physical secondary position on the inside Z flange and its measured packing block. Native portal worklines retained.'
        stations[m['id']]=(a[0],a[2]);x,y,_=frame(m['start'],m['end'],m.get('ref_direction'))
        positive=wall and not right;fk=(m['profile'],positive)
        if fk not in flange_points:flange_points[fk]=flange(profiles[m['profile']],positive)
        fx,fy=flange_points[fk]
        bearing_offset=tuple(fx*xx+fy*yy-t/2*nn for xx,yy,nn in zip(x,y,n))
        for field,p in [('start',a),('end',b)]:
            j=round(p[1]/(u.sy*1000));at=m[field]
            if abs(p[1]-j*u.sy*1000)>.1:continue  # A cut wall girt at a door jamb has its own receiver.
            cap=[v+o for v,o in zip(at,bearing_offset)]
            host=target(walls[j,right] if wall else (canopies if can else roofs)[j],cap,n)
            if host is None:raise ValueError(f"{m['id']}: no primary receiver at {p}")
            # A 40 mm width sits inside the actual Z outstand. Both longitudinal
            # pieces at a frame share one continuous 140 mm bearing length.
            across=(0,0,1) if wall else tangent
            if dot(cross(across,n),(0,1,0))<0:across=tuple(-v for v in across)
            root=tuple(round(v,2) for v in cap)
            if root in seats:
                if m['id'] not in seats[root]['members']:seats[root]['members'].append(m['id'])
                continue
            lead=0 if j==0 else -140 if j==u.ny else -70
            pt=plus(cap,(0,1,0),lead);p0=plus(pt,across,-20);p1=plus(pt,across,20)
            h0,h1=(contact(host,profiles,t_,n) for t_ in (p0,p1))
            distances=[dot(sub(top,bottom),n) for bottom,top in ((h0,p0),(h1,p1))]
            if min(distances)<1:raise ValueError(f"{m['id']}: primary flange interferes with the secondary bearing face, {distances}")
            gaps.extend(distances);key=f'{model.pre}SEAT-{len(seats)+1}'
            part=dict(id=key+'-BL',kind='plate',material='E250B0',outline=[h0,h1,p1,p0],thickness_mm=140)
            row=dict(id=key,unit=u.name,level=m['level'],type=role+' bearing',at=[round(v,4) for v in cap],
                     members=[host['id'],m['id']],parts=[part],parameters={'bearing_length_mm':140,'bearing_width_mm':40,
                     'minimum_packing_mm':round(min(distances),2),'maximum_packing_mm':round(max(distances),2)},
                     description='Tapered E250 B0 steel bearing between the actual frame flange and the inside face of the cold-formed Z flange. Verify block welding and the supplier cleat, fasteners, uplift and local web crippling before installation.')
            seats[root]=row;data['connections'].append(row)
    model.peb_secondary_stations=stations
    for panel in data['panels']:
        if panel['unit']!=u.name:continue
        role=panel['role'];x0=panel['outline'][0][0]
        if role in ('roof sheeting','dock canopy'):
            dz=roof_offset if role=='roof sheeting' else (16+zdepth['canopy purlin'])*math.hypot(1,1/30)
            for ring in [panel['outline'],*panel.get('openings',[])]:
                for p in ring:p[2]=round(p[2]+dz,4)
        elif role in ('masonry dado','wall cladding'):
            sidewall=all(abs(p[0]-x0)<.01 for p in panel['outline']);sgn=-1 if x0<width/2 else 1
            if sidewall:
                # Wall outline defines the inner face; material extrudes outward.
                if dot(cross(sub(panel['outline'][1],panel['outline'][0]),sub(panel['outline'][2],panel['outline'][0])),(sgn,0,0))<0:
                    panel['outline'].reverse()
                for p in panel['outline']:
                    p[0]=round(p[0]+sgn*(wall_offset-(panel['thickness_mm'] if role=='masonry dado' else 0)),4)
                    if role=='wall cladding' and abs(p[2]-h)<.01:p[2]=round(h+roof_offset-rise*wall_offset,4)
            else:
                # Gable support design remains separate. Extend the actual gable sheet to its roof.
                if role=='wall cladding':
                    for p in panel['outline']:
                        if abs(p[2]-model.roof_z(p[0]))<.01:p[2]=round(p[2]+roof_offset,4)
    # Sidewall sheeting sits outside the structural grid. Eave flashings close
    # that physical distance and remain separate from the specified grid roof area.
    for right in (False,True):
        x=width if right else 0.;outer=x+(wall_offset if right else -wall_offset)
        z=h+roof_offset;oz=z-rise*wall_offset
        points=[(x,0,z),(outer,0,oz),(outer,length,oz),(x,length,z)]
        if not right:points.reverse()
        model.panel('eave flashing',points,.5,'SHEET',f'EAVE-CLOSURE-{int(right)}')
    for m in ms:
        if m['role'] not in ('door jamb','door lintel') or '-Y' not in m['id']:continue
        right=m['start'][0]>width/2;outward=(1 if right else -1,0,0)
        x,y,_=frame(m['start'],m['end'],m.get('ref_direction'))
        face=max(dot(x,outward)*u+dot(y,outward)*v for polygon in section_polygons(profiles[m['profile']]) for u,v in polygon.exterior.coords)
        for field in ('start','end'):m[field]=plus(m[field],outward,wall_offset-face)
    rooflights(model,roof_offset)
    from peb_gables import install
    install(model,roof_offset,wall_offset)
    n=model.case.number
    if n in (1,2,5):data['assumptions'].append('Continuous ridge ventilation is a specialist envelope package. Opening width, curb, flashing, local trimming and rain exclusion require the ventilator supplier specification.')
    if n in (2,4):data['assumptions'].append('The 50 mm roof insulation is included in roof dead load. The envelope supplier coordinates the thermal blanket, standing seam or profiled liner, spacers and sealed rooflight transitions.')
    if n==2:data['assumptions'].append('Twenty 3.0 x 3.5 m east dock openings and four 6 x 6 m gable openings are set out between columns. Dock-leveller pits, equipment, edge beams, anchors and manufacturer reactions belong to equipment and foundation coordination.')
    if n in (1,2,4,5):data['assumptions'].append('The 230 mm masonry dado bears on its own plinth. Its out-of-plane ties, foundation and movement joints require local masonry and foundation detailing.')
    data['assumptions'].append(f'Portal eave and ridge values are fixed structural workline elevations. Across the main roof the inner skin is {roof_offset:.1f} mm vertically above that datum. The long façade is {wall_offset:.1f} mm outside the column grid. Roof and long-wall packing varies from {min(gaps):.1f} to {max(gaps):.1f} mm. The gable and door jamb attachments, outer cladding fixings, water seals and thermal movement require envelope-supplier details.')


def samples(data):
    """Global test rays through finite Z flanges, packs and the weather skin."""
    from shapely.geometry import Point,Polygon
    ms={m['id']:m for m in data['members']};out=[];families=set()
    for j in data['connections']:
        if j['type'] not in ('purlin bearing','canopy purlin bearing','girt bearing'):continue
        receiver,carried=ms[j['members'][0]],ms[j['members'][1]]
        a,b=carried['start'],carried['end'];p=data['profiles'][carried['profile']]
        wall=carried['role']=='girt';side='west' if a[0]<0 else 'east'
        x,y,axis=frame(a,b,carried.get('ref_direction'));n=y
        if wall:
            n=(-1,0,0) if side=='west' else (1,0,0)
            if a[2]<4500:continue
        elif n[2]<0:n=tuple(-v for v in n)
        key=(j['type'],side if wall else n[0]>0)
        if key in families or not min(a[1],b[1])+.1<j['at'][1]<max(a[1],b[1])+.1:continue
        block=j['parts'][0]
        # Stay inside the incoming member at an interior support and inside its pack.
        at=plus(j['at'],(0,1,0),-35)
        if not min(a[1],b[1])<at[1]<max(a[1],b[1]):continue
        prefix=carried['id']
        uplift=dot(y,n)>0;upper=flange(p,uplift);outward=plus(plus(a,x,upper[0]),y,upper[1])
        mid=plus(outward,axis,math.dist(a,b)*.15)
        role='wall cladding' if wall else 'dock canopy' if carried['role']=='canopy purlin' else 'roof sheeting'
        dims=(1,2) if wall else (0,1)
        def project(r):return [(pt[dims[0]],pt[dims[1]]) for pt in r]
        panel=None
        for skin in data['panels']:
            if skin['role']!=role:continue
            if wall and abs(skin['outline'][0][0]-mid[0])>12:continue
            shape=Polygon(project(skin['outline']),[project(h) for h in skin.get('openings',[])])
            if shape.is_valid and shape.contains(Point(*project([mid])[0])):
                panel=skin;break
        if not panel:continue
        families.add(key)
        out.extend([dict(id=prefix+'-PACK-CONTACT',chain=[receiver['id'],block['id'],carried['id']],
                         normal=list(n),stations_mm=[at],expected_gaps_mm=[0,0],tolerance_mm=1),
                    dict(id=prefix+'-SKIN-CONTACT',chain=[carried['id'],panel['id']],
                         normal=list(n),stations_mm=[mid],expected_gaps_mm=[0],tolerance_mm=1)])
    for j in data['connections']:
        if j['type']!='gable girt bearing':continue
        post,rail=ms[j['members'][0]],ms[j['members'][1]];a,b=rail['start'],rail['end']
        if post['role']!='gable post' or a[2]<5000:continue
        end=0 if a[1]<0 else 1;group=('gable girt',end)
        if group in families:continue
        normal=(0,-1 if end==0 else 1,0);px,py,axis=frame(a,b,rail['ref_direction'])
        fx,fy=flange(data['profiles'][rail['profile']],dot(py,normal)>0)
        q=plus(plus(plus(a,px,fx),py,fy),axis,.45*math.dist(a,b))
        panel=next((p for p in data['panels'] if p['role']=='wall cladding' and f'-X{end}-' in p['id']
                    and Polygon([(v[0],v[2]) for v in p['outline']]).contains(Point(q[0],q[2]))),None)
        if not panel:continue
        families.add(group)
        out.extend([dict(id=rail['id']+'-PACK-CONTACT',chain=[post['id'],j['parts'][0]['id'],rail['id']],
                         normal=list(normal),stations_mm=[j['at']],expected_gaps_mm=[0,0],tolerance_mm=1),
                    dict(id=rail['id']+'-SKIN-CONTACT',chain=[rail['id'],panel['id']],
                         normal=list(normal),stations_mm=[q],expected_gaps_mm=[0],tolerance_mm=1)])
    return out
