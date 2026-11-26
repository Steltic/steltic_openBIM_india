"""Façade girt shoes, clear openings and the snow-loaded lower deck."""
import math
from collections import defaultdict

from steltic_openbim_india.geometry import cross,dot,frame,plane,sub,unit
from bearing import UP,bounds,centre,contains,endpoints,location,negative,point_on


def fit_lean_to(f):
    if f.model.case.number!=9:return
    deck=next(p for p in f.panels if p['role']=='lean-to structural deck')
    sheet=next(p for p in f.panels if p['role']=='lean-to roof')
    beams=[r for r in f.members if r['role'] in ('lean-to purlin','lean-to roof beam')]
    maximum=max(r['start'][2]+f.extremity(r,UP)[1] for r in beams)
    lift=maximum-deck['outline'][0][2]
    for panel in (deck,sheet):
        old=min(p[2] for p in panel['outline'])
        for p in panel['outline']:p[2]+=lift
        f.references.append(dict(panel=panel['id'],role=panel['role'],reference_elevation_mm=old,
                        installed_soffit_elevation_mm=old+lift,normal_offset_mm=lift))
    deck['bearing_members']=[]
    # Continuous, centred bearing rails close differing native purlin/beam top
    # levels without shifting those source-bound worklines.
    for r in beams:
        lo,hi=f.extremity(r,UP);z=r['start'][2]+hi
        run=unit(sub(r['end'],r['start']));across=unit(cross(UP,run))
        margin=70.
        if maximum-z>.5:
            key=r['id']+'-DECK-RISER'
            w=min(f.data['profiles'][r['profile']]['dimensions_mm']['b']*.75,125.)
            length=math.dist(*endpoints(r))-2*margin
            thick=max(8.,5*math.ceil((maximum-z)/40/5))
            # An inverted T rail seats the deck continuously. Web bears and is
            # shop welded along the supporting primary flange.
            bottom=location(r['start'],(UP,hi),(run,margin))
            cap_t=10.;height=maximum-z-cap_t
            parts=[]
            if height>.1:
                base=location(bottom,(across,thick/2))
                parts.append(f.record_plate(f.plate(key+'-WEB',base,run,UP,length,height,thick,'E250B0'),r['level'],length*height))
            cap=f.plate(key+'-CAP',location(bottom,(UP,max(0.,height)),(across,-w/2)),run,across,length,w,min(cap_t,maximum-z),'E250B0')
            parts.append(f.record_plate(cap,r['level'],length*w));deck['bearing_members'].append(cap['id'])
            f.data['connections'].append(dict(id=key,type='continuous deck bearing rail',unit=r['unit'],level=r['level'],
                at=location(centre(r),(UP,hi)),members=[r['id']],parts=parts,
                description='Centred welded tee between the lower native member top flange and the structural deck soffit.'))
            f.sample(f.model.pre+'lean-rail-'+r['role'],[r['id'],*[p['id'] for p in parts],deck['id']],UP,centre(r))
        else:
            deck['bearing_members'].append(r['id'])
            f.sample(f.model.pre+'lean-direct-'+r['role'],[r['id'],deck['id']],UP,centre(r))


def fit_walls(f):
    model=f.model
    wall=[p for p in f.panels if p['role'] in ('wall cladding','masonry dado')]
    if not wall:return
    origin=model.offset
    sizes=(model.u.nx*model.u.sx*1000,model.u.ny*model.u.sy*1000)
    contacts=defaultdict(list)
    roof=[p for p in f.panels if p['role'] in ('roof deck','roof sheeting')]
    def roof_z(point):
        return min((dot(n,p['outline'][0])-n[0]*point[0]-n[1]*point[1])/n[2]
                   for p in roof for n in [plane(p['outline'])[3]])
    def atwall(m,ix,d,tol=1.):
        return all(abs(p[ix]-d)<tol for p in endpoints(m))
    offsets={}
    original_bounds={p['id']:bounds(p) for p in wall}
    for ix in (0,1):
        tangent=1-ix
        for side in (0,1):
            sign=1 if side else -1;d=origin[ix]+side*sizes[ix]
            n=tuple(sign if k==ix else 0. for k in range(3))
            wallpan=[p for p in wall if all(abs(pt[ix]-d)<.2 for pt in p['outline'])]
            girts=[r for r in f.members if r['role']=='girt' and atwall(r,ix,d)]
            structure=[r for r in f.members if r['role'] in ('column','gable post','end wall wind post','lean-to column')
                       and atwall(r,ix,d) and max(r['start'][2],r['end'][2])-min(r['start'][2],r['end'][2])>100]
            if not wallpan:continue
            jambs=[r for r in f.members if r['role']=='door jamb' and atwall(r,ix,d)]
            lintels=[r for r in f.members if r['role']=='door lintel' and atwall(r,ix,d)]
            if model.case.number==21 and ix==1:
                from enclosure import allowed_segments,doors
                example=next(r for r in f.members if r['role']=='girt')
                hs=model.datums[-1];space=model.case.girt_spacing*1000;openings=doors(model.case,model.u,'X',side)
                xs=sorted({0.,sizes[tangent]}|{r['start'][tangent]-origin[tangent] for r in structure})
                top=hs-150.
                for z in [3000+i*(top-3000)/math.ceil((top-3000)/space) for i in range(math.ceil((top-3000)/space)+1)]:
                    for a,b in zip(xs,xs[1:]):
                        for lo,hi in allowed_segments(a,b,z,openings):
                            p=[origin[0]+lo,d,z];q=[origin[0]+hi,d,z]
                            row={k:example[k] for k in ('role','material','profile','unit','checks') if k in example}
                            row.update(start=p,end=q,level=model.level(z),id=model.pre+f'GABLE-GIRT-{side}-{z:g}-{lo:g}')
                            f.data['members'].append(row);f.members.append(row);girts.append(row)
                            A=sum(s.area for s in f.shapes_for(row['profile']))
                            f.extra_mass[row['level']]+=A*math.dist(p,q)*7.85e-6
            if not structure:raise ValueError(f"{model.u.name}: wall {ix}/{side} has no wind supports")
            column_plane=max(dot(n,r['start'])+f.extremity(r,n)[1] for r in structure)
            for lint in lintels:
                if lint['start'][tangent]>lint['end'][tangent]:lint['start'],lint['end']=lint['end'],lint['start']
                ends=list(endpoints(lint))
                for end,raw in enumerate(ends):
                    j=next((r for r in jambs if abs(r['start'][tangent]-raw[tangent])<.5),None)
                    if not j:continue
                    j['ref_direction']=list(unit(cross(n,UP)))
                    temp=tuple(1 if k==tangent else 0 for k in range(3))
                    lo,hi=f.extremity(j,temp)
                    sh=-hi if end==0 else -lo
                    off=column_plane-dot(n,j['start'])-f.extremity(j,n)[1]
                    for k in ('start','end'):j[k]=location(j[k],(n,off),(temp,sh))
                # The soffit of the lintel leaves the nominal doorway clear.
                run=unit(sub(lint['end'],lint['start']));lint['ref_direction']=list(unit(cross(n,run)))
                lo,_=f.extremity(lint,UP);_,hi=f.extremity(lint,n)
                off=column_plane-dot(n,lint['start'])-hi
                for k in ('start','end'):lint[k]=location(lint[k],(n,off),(UP,-lo))
            supports=structure+jambs
            thickness=max((f.data['profiles'][m['profile']]['dimensions_mm']['d'] for m in girts),default=200.)
            outer=column_plane+thickness+100.
            offsets[(ix,side)]=outer-sign*d
            for m in girts:
                run=unit(sub(m['end'],m['start']));m['ref_direction']=list(unit(cross(n,run)))
                lo,hi=f.extremity(m,n)
                before={k:list(m[k]) for k in ('start','end')}
                shift=outer-dot(m['start'],n)-hi
                for k in before:m[k]=location(m[k],(n,shift))
                for end,p in before.items():
                    matches=[]
                    for r in supports:
                        if min(r['start'][2],r['end'][2])-.1<=p[2]<=max(r['start'][2],r['end'][2])+.1:
                            travel=tuple(1 if k==tangent else 0 for k in range(3))
                            l,h=f.extremity(r,travel)
                            if r['start'][tangent]+l-.5<=p[tangent]<=r['start'][tangent]+h+.5:
                                matches.append(r)
                    if not matches:
                        # At clear openings the jamb ends at the underside of
                        # the lintel. The girt above must span to an actual post.
                        f.missed.append([m['id'],end,'wall girt has no supporting post at this height'])
                        continue
                    r=max(matches,key=lambda v: dot(n,v['start'])+f.extremity(v,n)[1])
                    bare=dot(n,r['start'])+f.extremity(r,n)[1]
                    q=1.5*max(1.,f.model.cfg['load_plan']['wind_summary']['pd_kNm2']*1.8)
                    reaction=q*model.case.girt_spacing*math.dist(*endpoints(m))/2
                    f.stool(m,r,p,n,end,bare,outer-hi+lo,reaction)
                for panel in wallpan:
                    bb=original_bounds[panel['id']]
                    if panel['role']!='wall cladding':continue
                    c=centre(m)
                    dtype=f.data['profiles'][m['profile']]
                    sample=location(c,(frame(*endpoints(m),m.get('ref_direction'))[0],dtype['dimensions_mm']['b']*.45 if dtype['family']=='Z' else 0.))
                    from shapely.geometry import Polygon,Point
                    if Polygon([(v[tangent],v[2]) for v in panel['outline']]).contains(Point(sample[tangent],sample[2])):
                        panel.setdefault('bearing_members',[]).append(m['id'])
                        f.sample(model.pre+f'wall-{ix}-{side}-{m["profile"]}',[m['id'],panel['id']],n,sample)
            for p in wallpan:
                contacts[(ix,side)].append((p,n,outer))
    physical={}
    for ix in (0,1):
        for side in (0,1):
            physical[(ix,side)]=origin[ix]+side*sizes[ix]+(1 if side else -1)*offsets.get((ix,side),0.)
    for (ix,side),group in contacts.items():
        for p,n,outer in group:
            # Both wall and dado outline points start on their inside face and
            # extrude outwards. Dado and thin sheet share their external face.
            inner=outer if p['role']=='wall cladding' else outer+.5-p['thickness_mm']
            if dot(plane(p['outline'])[3],n)<0:p['outline'].reverse()
            for ring in [p['outline'],*p.get('openings',[])]:
                for v in ring:
                    original=list(v)
                    v[ix]=n[ix]*inner
                    for side2 in (0,1):
                        k=1-ix
                        if abs(original[k]-(origin[k]+side2*sizes[k]))<.1:v[k]=physical[(k,side2)]
                    if (p['role']=='wall cladding' and abs(original[2]-(model.roof_y(original[1]-origin[1]) if model.case.number==10
                                                                else model.roof_z(original[0]-origin[0])))<1.):
                        v[2]=round(roof_z(v),4)
    # The two roof surfaces and all wall edges meet at the same outside corner.
    for p in roof:
        n=plane(p['outline'])[3];d=dot(n,p['outline'][0])
        for ring in [p['outline'],*p.get('openings',[])]:
            for v in ring:
                for k in (0,1):
                    for side in (0,1):
                        if abs(v[k]-origin[k]-side*sizes[k])<.15:v[k]=physical[(k,side)]
                v[2]=round((d-n[0]*v[0]-n[1]*v[1])/n[2],4)
    for r in f.members:
        if r['role'] not in ('purlin','roof joist','secondary beam'):continue
        if r['role']=='secondary beam' and r['level']!=model.level(model.datums[-1]):continue
        run=unit(sub(r['end'],r['start']))
        for k in (0,1):
            if abs(run[k])<.999:continue
            for end in ('start','end'):
                for side in (0,1):
                    if abs(r[end][k]-origin[k]-side*sizes[k])<.15:
                        extension=(physical[(k,side)]-r[end][k])/run[k]
                        r[end]=location(r[end],(run,extension))
    f.scope.append(dict(roles=['wall cladding'],exterior_planes_global_mm={f'{k}-{s}':round(v,3) for (k,s),v in physical.items()}))
