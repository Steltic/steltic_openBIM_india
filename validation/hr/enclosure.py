"""Shed cladding, clear door openings and physical restraints in the brief's site grid."""
import math


def intervals(length,number,width,height):
    if not number:return []
    spacing=length/number
    return [(spacing*(i+.5)-width/2,spacing*(i+.5)+width/2,height) for i in range(number)]


def doors(case,u,axis,side):
    n=case.number; span=(u.ny*u.sy if axis=='Y' else u.nx*u.sx)*1000
    if n==10:
        # External door sizes are coordination assumptions inside each wall's 5% opening limit.
        return intervals(span,1,4000,4000) if axis=='Y' else [(24000,27000,4000),(69000,72000,4000)]
    if n==6:return intervals(span,2 if axis=='Y' else 1,4000,4500)
    if n in (7,8):return intervals(span,2 if axis=='Y' else 1,5500,5000)
    if axis=='Y':
        if n in (1,5):return intervals(span,2,5000,5000)
        if n==2 and side==1:return intervals(span,20,3000,3500)
        if n==4 and side==0:return intervals(span,10,3000,3500)
    else:
        if n==2:return intervals(span,2,6000,6000)
        if n==3:return intervals(span,1,6000,6000)
        if n==21:return intervals(span,1,4000,4500)
    return []


def allowed_segments(a,b,z,holes):
    segments=[(a,b)]
    for lo,hi,h in holes:
        if z>=h-.001:continue
        result=[]
        for x,y in segments:
            if x<lo and min(y,lo)>x:result.append((x,min(y,lo)))
            if y>hi and y>max(x,hi):result.append((max(x,hi),y))
        segments=result
    return segments


def envelope(model):
    case,u=model.case,model.u;n=case.number;h=model.datums[-1]
    width=u.sx*u.nx*1000;length=u.sy*u.ny*1000
    if not case.rise and n not in (6,10):return
    data=model.data
    data['materials']['BRICK']={'grade':'Fired clay masonry','standard':'230 mm nominal brick dado per HR test brief'}
    for ax,across,along in [('Y',width,length),('X',length,width)]:
        for side in (0,1):
            def point(a,z):
                return (side*across,a,z) if ax=='Y' else (a,side*across,z)
            openings=doors(case,u,ax,side)
            split_ridge=ax==('Y' if n==10 else 'X')
            ends=sorted({0.,along}|({along/2} if split_ridge else set())|{q for lo,hi,z in openings for q in (lo,hi)})
            for i,(x,y) in enumerate(zip(ends,ends[1:]),1):
                low=max((z for lo,hi,z in openings if lo<(x+y)/2<hi),default=0.)
                dado=3000. if n in (1,2,4,5,21) else 0.
                topa=model.roof_y(x) if n==10 and ax=='Y' else model.roof_z(x) if ax=='X' else h
                topb=model.roof_y(y) if n==10 and ax=='Y' else model.roof_z(y) if ax=='X' else h
                if dado>low:
                    model.panel('masonry dado',[point(x,low),point(y,low),point(y,dado),point(x,dado)],230,'BRICK',
                                f'DADO-{ax}{side}-{i}')
                z=max(dado,low)
                model.panel('wall cladding',[point(x,z),point(y,z),point(y,topb),point(x,topa)],.5,'SHEET',
                            f'WALL-{ax}{side}-{i}')
            for k,(a,b,z) in enumerate(openings,1):
                for j,q in enumerate((a,b),1):
                    model.member('door jamb','MC250',point(q,0),point(q,z),mid=f'JAMB-{ax}{side}-{k}-{j}',bind=False)
                model.member('door lintel','MC300',point(a,z),point(b,z),mid=f'LINT-{ax}{side}-{k}',bind=False)
            if n in (6,10) or n in (7,8,9) and ax=='X':
                step=(u.sy if ax=='Y' else u.sx)*1000; bays=u.ny if ax=='Y' else u.nx
                service='side girt' if ax=='Y' else 'end girt'
                section=model.cfg['physical_secondaries'][service]
                if ax=='X' and n in (7,8,9):
                    step/=3;bays*=3
                    for m in range(1,bays):
                        coord=m*step
                        if any(a<coord<b for a,b,z in openings):continue
                        model.member('end wall wind post','WPB250X250X73.15',point(coord,0),point(coord,model.roof_z(coord)),mid=f'END-POST-{side}-{m}',bind=False)
                for k in range(1,math.ceil(h/(case.girt_spacing*1000))):
                    zz=k*case.girt_spacing*1000
                    for bay in range(bays):
                        for m,(lo,hi) in enumerate(allowed_segments(bay*step,(bay+1)*step,zz,openings)):
                            model.member('girt',section,point(lo,zz),point(hi,zz),ref=[0,0,1],
                                         checks=[model.secondary_checks.get(service)],mid=f'GIRT-{ax}{side}-{k}-{bay}-{m}',bind=False)
    if n in (6,7,8,10):
        data['assumptions'].append('Door dimensions and positions are design assumptions for the stated permeability. Coordinate with the architectural door and escape schedule.')
    if n in (7,8,9):
        bays=2*math.ceil(width/(2*case.purlin_spacing*1000))
        for j in range(u.ny):
            for third in (1,2):
                y=(j+third/3)*u.sy*1000
                for b in range(bays):
                    a=width*b/bays; end=width*(b+1)/bays
                    model.member('purlin bridging','ISA50X50X6',(a,y,model.roof_z(a)),(end,y,model.roof_z(end)),
                                 mid=f'PURLIN-BRIDGE-{j}-{third}-{b}',bind=False)
    # Connection end positions and fixing choice are detailed later. Model the
    # plan and wall lines specified by the brief, including local knee restraint.
    if n in (1,2,3,4,5):
        from peb_details import restraints
        restraints(model)
    if n in (8,9):
        import sections as S
        depth=S.props(model.cfg['gold']['roof_planes'][0]['rafter_sec'])['d']
        for j in range(u.ny+1):
            for sgn,face in ((1,0.),(-1,width)):
                nps=math.ceil(width/2/(case.purlin_spacing*1000))
                for p in range(1,nps):
                    dist=width*p/(2*nps)
                    if dist>6000 and p%2:continue
                    x=face+sgn*dist;z=model.roof_z(x);y=j*u.sy*1000
                    # On alternate sides so that a fly brace occupies a single bay.
                    row=model.member('rafter flange brace','ISA65X65X6',(x,y,z-depth/2),(x,y+(600 if j<u.ny else -600),z),
                                     mid=f'FLY-{j}-{p}-{sgn}',bind=False)
                    row['basis']='Rafter lower flange to purlin seat. Consecutive bottom-flange braces are at most two purlin intervals apart.'
