"""Locate restraint points on the actual frame and declare the corresponding buckling lengths."""
from itertools import combinations
import math

import engine3d as E
import openseespy.opensees as ops


def cross_points(rows):
    """Find both diagonals of the same wall bay and their true intersection on sloping roofs."""
    groups={}
    for tag,kind,sec,a,b in rows:
        if kind!='brace':continue
        p=list(ops.nodeCoord(a));q=list(ops.nodeCoord(b))
        if abs(p[2]-q[2])<1:continue
        if p[2]>q[2]:p,q=q,p
        direction=0 if abs(p[1]-q[1])<1 else 1 if abs(p[0]-q[0])<1 else None
        if direction is None:continue
        axis=direction;low,high=sorted((p[axis],q[axis]))
        groups.setdefault((axis,round(p[1-axis],2),round(low,2),round(high,2),round(p[2],2)),[]).append((tag,p,q))
    for key,pairs in groups.items():
        if len(pairs)!=2:continue
        (t,a,b),(u,c,d)=pairs;axis=key[0]
        if (b[axis]-a[axis])*(d[axis]-c[axis])>=0:continue
        h1=b[2]-a[2];h2=d[2]-c[2]
        fraction=(c[axis]-a[axis]) / ((b[axis]-a[axis])-(d[axis]-c[axis])*h1/h2)
        station=[a[i]+(b[i]-a[i])*fraction for i in range(3)]
        lengths=[max(fraction,1-fraction),max(fraction*h1/h2,1-fraction*h1/h2)]
        if all(.45<=v<=.60 for v in lengths):
            yield axis,station,(t,u),max(lengths)


def declare(case,u,cfg):
    n=case.number
    if n not in (7,8,9,10,11,21):return
    overrides=cfg.setdefault('member_overrides',{})
    data=E.build(cfg,'Linear')
    if n in (7,9,10,11):
        cfg['connected_crossings']=[]
        for axis,pt,tags,part in cross_points(data['ele']):
            record={'axis':axis,'at':pt,'tags':tags}
            cfg['connected_crossings'].append(record)
            factor=math.ceil((part+.01)*100)/100
            for tag in tags:
                overrides['e'+str(tag)]={'Ky':factor,'Kz':factor}
    for tag,kind,sec,ni,nj in data['ele']:
        a,b=ops.nodeCoord(ni),ops.nodeCoord(nj)
        if n==10 and kind=='beam' and abs(a[1]-b[1])>1000 and abs(a[2]-b[2])>1:
            # Perpendicular roof joists intersect every 2500 mm and the following
            # physical bridging braces the girder compression flange under reversal.
            L=math.dist(a,b)
            overrides['e'+str(tag)]={'Ly_mm':2501,'Ky':2501/L,'LLT_hog_mm':2501,'LLT_sag_mm':2501}
        if n==10 and kind=='col':
            # The pinned side-wall girts are located on every perimeter face.
            w=u.nx*u.sx*1000;length=u.ny*u.sy*1000
            if min(abs(a[0]),abs(a[0]-w),abs(a[1]),abs(a[1]-length))<.1:
                L=math.dist(a,b)
                overrides['e'+str(tag)]={'Ly_mm':2375,'Ky':2375/L}
        if n in (8,9) and kind=='beam' and abs(a[0]-b[0])>100 and abs(a[2]-b[2])>1:
            L=math.dist(a,b)
            half_span=u.nx*u.sx/2
            stations=math.ceil(half_span/case.purlin_spacing)
            upper=math.ceil(1000*math.hypot(half_span,case.rise)/stations)
            lower=2*upper
            overrides['e'+str(tag)]={'Ly_mm':lower,'Ky':min(1,lower/L),'LLT_sag_mm':upper,'LLT_hog_mm':lower}
        if n in (7,8,9,21) and kind=='beam' and abs(a[1]-b[1])>100 and abs(a[0]-b[0])<1:
            # Eave struts and ridge beams bear at consecutive frame lines.
            # The transverse building width is not their unsupported length.
            span=math.ceil(math.dist(a,b))
            overrides['e'+str(tag)]={'LLT_sag_mm':span,'LLT_hog_mm':span}
        if n==9 and data.get('physical_roles',{}).get(tag)=='lean-to purlin':
            overrides['e'+str(tag)]={'Ky':1/3,'Ly_mm':2500,'LLT_sag_mm':2500,'LLT_hog_mm':2500}
        if n==9 and data.get('physical_roles',{}).get(tag)=='lean-to roof beam':
            overrides['e'+str(tag)]={'Ky':1,'Ly_mm':3000,'LLT_sag_mm':3000,'LLT_hog_mm':3000}
        if n==21 and data.get('physical_roles',{}).get(tag)=='gable post':
            L=math.dist(a,b)
            # The new tie at mid-height connects to the sidewall girt lines.
            overrides['e'+str(tag)]={'Ly_mm':L/2,'Ky':.50}


def draw(model):
    n=model.case.number
    for ix,row in enumerate(model.cfg.get('connected_crossings',[]),1):
        ids=[model.pre+'E'+str(t) for t in row['tags']]
        if not set(ids)<=model.roles.keys():continue
        model.data['connections'].append({'id':model.pre+f'XC-{ix}','type':'connected X-brace crossing',
              'at':model.xyz(row['at']),'unit':model.u.name,'level':model.level(row['at'][2]),'members':ids,
              'description':'Connected crossing required for the declared compression length. Detail the continuous brace, interrupted brace and transverse restraint for both load reversals.'})
    if n==9:
        import sections as S
        depth=S.props(model.cfg['lean_beam'])['d']
        for j in range(5):
            y=j*model.u.sy*1000
            for i in range(1,5):
                x=-3000*i
                model.member('lean-to girder flange brace','ISA75X75X6',(x,y,5000-depth/2),(x,y+(600 if j<4 else -600),5000),
                             mid=f'LOW-FLY-{j}-{i}',bind=False)
        for j in range(4):
            for station in (1/3,2/3):
                y=(j+station)*model.u.sy*1000
                for i in range(4):
                    model.member('lower roof bridging','ISA75X75X6',(-3000*i,y,5000),(-3000*(i+1),y,5000),
                                 mid=f'LOW-BRIDGE-{j}-{round(station*3)}-{i}',bind=False)
            if j in (0,3):
                model.member('lower roof plan brace','ISA90X90X8',(0,j*model.u.sy*1000,5000),(-12000,(j+1)*model.u.sy*1000,5000),
                             mid=f'LOW-DIAG-{j}',bind=False)
    if n==10:
        import sections as S
        depth=S.props(model.cfg['gold']['roof_planes'][0]['rafter_sec'])['d']
        for i in range(model.u.nx+1):
            x=i*model.u.sx*1000
            side=-1 if i==model.u.nx else 1
            for j in range(1,round(model.u.ny*model.u.sy/2.5)):
                y=j*2500;z=model.roof_y(y)
                model.member('girder flange brace','ISA75X75X6',(x,y,z-depth/2),(x+750*side,y,z),
                             mid=f'GIRDER-FLY-{i}-{j}',bind=False)
    if n==21:
        w=model.u.nx*model.u.sx*1000;h=model.datums[-1];rise=model.case.rise*1000
        z=(h+rise*2/3)/2
        for j in (0,model.u.ny):
            for k in range(3):
                model.member('gable post restraint','MC250',(k*w/3,j*model.u.sy*1000,z),((k+1)*w/3,j*model.u.sy*1000,z),mid=f'GAB-REST-{j}-{k}',bind=False)
