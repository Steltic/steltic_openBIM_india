"""Place envelope steel on actual supporting section faces in the India HR examples.

All source-bound beam and column worklines stay at the analysis coordinates. The
installation schedule distinguishes those worklines from the underside of deck.
"""
import math
from collections import defaultdict

from shapely.geometry import LineString
from steltic_openbim_india.geometry import cross, dot, frame, plane, sub, unit
from steltic_openbim_india.profiles import section_polygons
from native_joint_parts import location, plate


UP=(0.,0.,1.)
ROOF=('roof sheeting','roof deck','floor deck','lean-to structural deck')
CARRIED=('purlin','roof joist','secondary beam')
RECEIVERS=('beam','rafter','truss top chord','shear link','lean-to roof beam','lean-to purlin')


def negative(a):
    return tuple(-v for v in a)


def point_on(a,b,f):
    return tuple(p+f*(q-p) for p,q in zip(a,b))


def endpoints(row):
    return row['start'],row['end']


def centre(row):
    return point_on(*endpoints(row),.5)


def bounds(panel):
    return tuple((min(p[i] for p in panel['outline']),max(p[i] for p in panel['outline'])) for i in (0,1))


def contains(b,p,tol=.3):
    return all(lo-tol<=p[i]<=hi+tol for i,(lo,hi) in enumerate(b))


def relative_plan_point(row,p):
    a,b=endpoints(row)
    dx,dy=b[0]-a[0],b[1]-a[1]
    den=dx*dx+dy*dy
    if den<1:return None
    t=((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den
    if t<-.0001 or t>1.0001:return None
    nearest=point_on(a,b,min(max(t,0),1))
    return nearest if math.hypot(nearest[0]-p[0],nearest[1]-p[1])<.5 else None


class Fitting:
    plate=staticmethod(plate)

    def __init__(self,model):
        self.model=model
        self.data=model.data
        self.members=[r for r in self.data['members'] if r['unit']==model.u.name]
        self.panels=[r for r in self.data['panels'] if r['unit']==model.u.name]
        self.shapes={}
        self.samples=[]
        self.mass=defaultdict(float)
        self.extra_mass=defaultdict(float)
        self.references=[]
        self.checks=[]
        self.candidate={}
        self.moves={}
        self.scope=[]
        self.verified=0
        self.missed=[]

    def shapes_for(self,name):
        if name not in self.shapes:self.shapes[name]=section_polygons(self.data['profiles'][name])
        return self.shapes[name]

    def extremity(self,row,n):
        x,y,_=frame(*endpoints(row),row.get('ref_direction'))
        ax,ay=dot(x,n),dot(y,n)
        values=[ax*i+ay*j for s in self.shapes_for(row['profile']) for i,j in s.exterior.coords]
        return min(values),max(values)

    def ray(self,row,station,n):
        """Global signed intervals of a ray through the actual section loops."""
        x,y,z=frame(*endpoints(row),row.get('ref_direction'))
        off=sub(station,row['start']);u,v=dot(off,x),dot(off,y);dx,dy=dot(n,x),dot(n,y)
        if dx*dx+dy*dy<1e-7:return None
        line=LineString([(u-5000*dx,v-5000*dy),(u+5000*dx,v+5000*dy)])
        values=[]
        for s in self.shapes_for(row['profile']):
            cut=s.intersection(line)
            for polyline in getattr(cut,'geoms',[cut]):
                for i,j in getattr(polyline,'coords',[]):
                    d=((i-u)*dx+(j-v)*dy)/(dx*dx+dy*dy)
                    along=dot(off,z)+d*dot(n,z)
                    trim=row.get('end_cutbacks_mm',(0.,0.))
                    if trim[0]-.001<=along<=math.dist(*endpoints(row))-trim[1]+.001:values.append(dot(station,n)+d)
        return (min(values),max(values)) if values else None

    def sample(self,key,ids,n,p):
        # One representative for each genuinely different stack in this unit.
        if any(i['id']==key for i in self.samples):return
        self.samples.append(dict(id=key,chain=ids,normal=list(n),stations_mm=[list(p)],
                                 expected_gaps_mm=[0.]*(len(ids)-1),tolerance_mm=1.))

    def record_plate(self,p,level,area):
        self.mass[level]+=area*p['thickness_mm']*7.85e-6
        return p

    def stool(self,carried,support,axispoint,n,side,zbare,zlow,load,installed_at=None):
        """Two half-seats at an internal frame each carry their own span's reaction."""
        axis=unit(sub(carried['end'],carried['start']))
        axis=negative(axis) if side=='end' else axis
        across=unit(cross(n,axis))
        along=unit(cross(across,n))
        if dot(axis,along)<0:raise ValueError('Reversed seat axis')
        x,y,_=frame(*endpoints(carried),carried.get('ref_direction'))
        dims=self.data['profiles'][carried['profile']].get('dimensions_mm',{})
        b=dims['b']; prof=self.data['profiles'][carried['profile']]['family']
        # The lower flange of a lipped Z lies on its negative local-X side.
        off=-b*.46 if prof=='Z' else 0.
        if installed_at is not None:
            installed=installed_at
        elif side in ('start','end'):
            installed=carried[side]
        else:
            datum=carried['start']
            installed=location(datum,(axis,dot(sub(axispoint,datum),axis)))
        c=location(installed,(x,off))
        c=location(c,(n,zlow-dot(c,n)))
        # Source axispoint uses the receiver reference elevation; the plane
        # normal determines all physical part faces independent of that elevation.
        width=min(170., max(20.,b*(.72 if prof=='Z' else .78)))
        length=100.
        key=carried['id']+'-BEAR-'+side.upper()
        level=carried['level']; material='E250B0'
        parts=[]
        def new_plate(suffix,loc,a,b,w,h,t):
            p=plate(key+suffix,loc,a,b,w,h,t,material)
            parts.append(self.record_plate(p,level,w*h))
            return p
        # Select an actual point of nominal flange contact. This matters for
        # the two isolated legs of a back-to-back angle truss chord.
        options=[support]
        if support['role']=='truss top chord':
            options.extend(r for r in self.possible_supports(axispoint,axis) if r['id']!=support['id'])
        values=[]
        for receiver in options:
            for frac in (.06,.12,.18,.28,.5,.73,.88,.97):
                for horizontal in (0.,.21,-.21):
                    probe=location(c,(along,frac*length),(across,horizontal*width))
                    contact=self.ray(receiver,probe,n)
                    if contact:values.append((contact[1],frac,probe,receiver))
                if values and receiver is options[0] and len(options)==1 and len(values)>3:break
        if values:
            zbare,_,_,support=max(values,key=lambda item:item[0])
        hits=[(frac,p) for height,frac,p,receiver in values if receiver is support and abs(height-zbare)<.8]
        c=location(c,(n,zbare-dot(c,n)))
        corner=location(c,(across,-width/2))
        gap=zlow-zbare
        if gap<2.9:raise ValueError(f"{carried['id']}: insufficient steel seat gap {gap:.2f} mm")
        if not hits:
            self.missed.append([key,'receiver upper face',support['id']])
        lever=max(8.,length*(1-max((f for f,_ in hits),default=0.)))
        t=5*math.ceil(max(10.,math.sqrt(6*load*lever*1.1/(width*230)))/5.)
        if gap<=max(100.,2*t+20):
            bridge=new_plate('-PACK',corner,along,across,length,width,gap)
            chain=[support['id'],bridge['id'],carried['id']]
        else:
            base=new_plate('-LOWER',corner,along,across,length,width,t)
            cap=new_plate('-CAP',location(corner,(n,gap-t)),along,across,length,width,t)
            h=gap-2*t
            web=5*math.ceil(max(10.,h/32.,load*1.1/(2*length*230))/5.)
            for i,offset in enumerate((.22*width,.78*width),1):
                # along x n extrudes towards -across
                at=location(corner,(n,t),(across,offset+web/2))
                new_plate(f'-WEB{i}',at,along,n,length,h,web)
            chain=[support['id'],base['id']]
        if hits:
            f,probe=hits[0]
            self.sample(self.model.pre+f"support-{support['role']}-{carried['role']}-{len(parts)}",
                        chain,n,probe)
            if len(parts)>1:
                self.sample(self.model.pre+f"cap-{carried['role']}",[cap['id'],carried['id']],n,probe)
            self.verified+=1
        q=dict(id=key,type='secondary bearing',unit=self.model.u.name,level=level,
               at=location(c,(along,length/2),(n,gap)),members=[carried['id'],support['id']],parts=parts,
               parameters=dict(interface_normal=list(n),interface_side=side,seat_count=1,
                    design_bearing_length_mm=length,assembly_gap_limit_mm=1.,vertical_steel_depth_mm=round(gap,3),
                    factored_support_reaction_kN=round(load/1000,3),nominal_seating_width_mm=round(width,3)),
               description='Shop-welded E250 B0 bearing shoe, with full 100 mm support under the carried span. Verify bearing flange local resistance, attachment under reversal, erection and access.')
        self.data['connections'].append(q)

    def possible_supports(self,p,axis):
        hits=[]
        for row in self.members:
            if row['role'] not in RECEIVERS:continue
            q=relative_plan_point(row,p)
            if q is None or abs(q[2]-p[2])>1.:continue
            dx,dy=row['end'][0]-row['start'][0],row['end'][1]-row['start'][1]
            cross_dir=abs(dx*axis[1]-dy*axis[0])/math.hypot(dx,dy)
            if cross_dir>.75:hits.append(row)
        return hits

    def place_surface(self,group):
        n,d,panels,secondaries=group
        if not secondaries:return
        ranked=[]; required=0.
        for m in secondaries:
            run=unit(sub(m['end'],m['start']));m['ref_direction']=list(unit(cross(n,run)))
            lo,hi=self.extremity(m,n)
            supports={}
            for side in ('start','end'):
                p=m[side];candidates=self.possible_supports(p,run)
                if not candidates:
                    self.missed.append([m['id'],side,'no intersecting cross member']);continue
                receiver=max(candidates,key=lambda r:self.extremity(r,n)[1])
                face=dot(p,n)+self.extremity(receiver,n)[1]
                supports[side]=(receiver,list(p),face)
                required=max(required,face-d+hi-lo)
            ranked.append((m,lo,hi,supports))
        # A constant increment permits real seat plates even on the highest
        # receiver. Both slopes use the same datum within a symmetric roof.
        lift=math.ceil((required+100.)/5)*5.
        for p in panels:
            self.references.append(dict(panel=p['id'],role=p['role'],reference_elevation_mm=round(min(v[2] for v in p['outline']),3),
                          installed_soffit_elevation_mm=round(min(v[2] for v in p['outline'])+lift/n[2],3),
                          normal_offset_mm=round(lift,3)))
            for ring in [p['outline'],*p.get('openings',[])]:
                for v in ring:v[2]=round(v[2]+lift/n[2],4)
            p['bearing_members']=[]
        for m,lo,hi,supports in ranked:
            dz=(d+lift-dot(m['start'],n)-hi)/n[2]
            self.moves[m['id']]=(list(m['start']),list(m['end']),dz)
            m['start'][2]=round(m['start'][2]+dz,4);m['end'][2]=round(m['end'][2]+dz,4)
            mid=centre(m)
            top_offset=self.data['profiles'][m['profile']]['dimensions_mm']['b']*.45 if self.data['profiles'][m['profile']]['family']=='Z' else 0
            width_axis=frame(*endpoints(m),m.get('ref_direction'))[0]
            sample=location(mid,(width_axis,top_offset))
            for p in panels:
                if contains(bounds(p),sample,.5):
                    p['bearing_members'].append(m['id'])
                    self.sample(self.model.pre+f"skin-{p['role']}-{m['profile']}",[m['id'],p['id']],n,sample)
            roof=any(p['role']!='floor deck' and contains(bounds(p),mid) for p in panels)
            q=max(2.5,1.5*(self.model.case.roof_dead+self.model.case.collateral+1.5)) if roof else 1.5*(self.model.case.floor_dead+self.model.case.floor_live+self.model.case.partitions+1.)
            tributary=self.model.case.purlin_spacing if m['role']=='purlin' else min(3.,self.model.u.sy)
            reaction=q*tributary*(m.get('bearing_span_mm') or math.dist(*endpoints(m)))/2.
            for side,(receiver,p,zbare) in supports.items():
                instal=None
                if m['id'] in self.candidate:
                    run=unit(sub(m['end'],m['start']))
                    inward=run if side=='start' else negative(run)
                    col=next((r for r in self.members if r['role']=='column' and
                        math.dist(r['start'][:2],p[:2])<.5 and r['end'][2]>=m[side][2] and r['start'][2]<=m[side][2]),None)
                    cut=self.extremity(col,inward)[1]+12. if col else 0.
                    old_ref=m[side]
                    if cut:m[side]=location(m[side],(inward,cut))
                    for offset in (cut+15,cut+75,cut+150,cut+250,cut+400,cut+600):
                        pick=location(p,(inward,offset))
                        parallel=next((r for r in self.members if r['role'] in RECEIVERS and abs(dot(run,unit(sub(r['end'],r['start']))))>.99 and
                            (pt:=relative_plan_point(r,pick)) and abs(pt[2]-pick[2])<1 and self.ray(r,pick,n)),None)
                        if parallel:
                            receiver=parallel;p=pick;instal=location(old_ref,(inward,offset))
                            zbare=dot(n,p)+self.extremity(receiver,n)[1]
                            break
                self.stool(m,receiver,p,n,side,zbare,d+lift-(hi-lo),reaction,instal)
            for index,(p,receiver) in enumerate(self.candidate.get(m['id'],[]),1):
                zbare=dot(n,p)+self.extremity(receiver,n)[1]
                self.stool(m,receiver,p,n,f'station-{index}',zbare,d+lift-(hi-lo),2*reaction)
        self.scope.append(dict(roles=sorted({p['role'] for p in panels}),normal=list(n),datum_mm=round(d,3),soffit_lift_mm=lift,
                               installed_secondary_count=len(ranked)))

    def roof(self):
        groups={}
        for p in self.panels:
            if p['role'] not in ROOF or p['role']=='lean-to structural deck':continue
            n=plane(p['outline'])[3]
            if n[2]<0:raise ValueError(p['id']+' cover outline points downwards')
            d=dot(n,p['outline'][0]);key=tuple(round(i,5) for i in n)+(round(d,2),)
            groups.setdefault(key,(n,d,[],[]))[2].append(p)
        for m in self.members:
            if m['role'] not in CARRIED:continue
            mid=centre(m)
            valid=[g for g in groups.values() if abs(dot(g[0],mid)-g[1])<.4 and any(contains(bounds(p),mid) for p in g[2])]
            if not valid:self.missed.append([m['id'],'no hosting deck']);continue
            valid[0][3].append(m)
        self.edge_lines(groups.values())
        for group in groups.values():self.place_surface(group)
        self.adjust_bridging()

    def edge_lines(self,groups):
        """Close the double-width unsupported strip at each grid, ridge and eave."""
        done=set()
        for n,d,panels,secondaries in groups:
            if not secondaries:continue
            typical=secondaries[0]
            axis=unit(sub(typical['end'],typical['start']))
            span=math.dist(*endpoints(typical))
            for p in panels:
                for first,last in zip(p['outline'],p['outline'][1:]+p['outline'][:1]):
                    run=unit(sub(last,first))
                    if abs(dot(run,axis))<.999:continue
                    count=max(1,round(math.dist(first,last)/span))
                    for k in range(count):
                        a,b=point_on(first,last,k/count),point_on(first,last,(k+1)/count)
                        if dot(sub(b,a),axis)<0:a,b=b,a
                        other_plane=any(abs(dot(nn,a)-dd)<.35 and abs(dot(nn,b)-dd)<.35
                                        for nn,dd,pp,ss in groups if abs(dot(n,nn)-1.)>1e-5)
                        outside_eave=typical['role']=='purlin' and min(first[2],last[2])<max(v[2] for v in p['outline'])-1.
                        if other_plane or outside_eave:
                            # Two distinct purlins sit on opposite sides of the
                            # crease. Spacing uses the actual lower flange width.
                            perp=unit(cross(n,axis))
                            mid=point_on(a,b,.5)
                            ctr=[sum(v[i] for v in p['outline'])/len(p['outline']) for i in range(3)]
                            sign=1 if dot(sub(ctr,mid),perp)>0 else -1
                            dist=sign*max(self.data['profiles'][typical['profile']]['dimensions_mm']['b']+25.,
                                           650. if typical['role']=='purlin' else 100.)
                            a,b=location(a,(perp,dist)),location(b,(perp,dist))
                        key=tuple(round(v,2) for v in (*a,*b))
                        if key in done:continue
                        done.add(key)
                        m={k:v for k,v in typical.items() if k in ('unit','level','profile','role','material','checks')}
                        m.update(id=p['id']+'-EDGE-'+str(len(done)),start=list(a),end=list(b),
                                 basis='Additional physical edge/grid bearer on the same design span and spacing envelope as its neighbouring secondary.')
                        if typical['role']!='purlin':
                            # An existing parallel primary allows a short-span
                            # cap rail on intermediate stools instead of a
                            # second, full-bay joist above that primary.
                            length=math.dist(a,b);intervals=math.ceil(length/1000)
                            stations=[]
                            for h in range(1,intervals):
                                at=point_on(a,b,h/intervals)
                                aligned=next((r for r in self.members if r['role'] in RECEIVERS and
                                    abs(dot(unit(sub(r['end'],r['start'])),axis))>.99 and
                                    (hit:=relative_plan_point(r,at)) and abs(at[2]-hit[2])<.5),None)
                                if aligned is None:break
                                stations.append((at,aligned))
                            if len(stations)==intervals-1:
                                name='RHS120X80X6-EDGE'
                                import sections
                                sections.register_box(name,80,120,6,6)
                                self.data['profiles'].setdefault(name,dict(family='RHS',dimensions_mm=dict(d=120.,b=80.,tw=6.,tf=6.)))
                                m.update(profile=name,material='E250B0',bearing_span_mm=length/intervals,checks=[],
                                    basis='Fabricated RHS edge rail, supported at maximum 1 m centres on the native parallel beam.')
                                self.candidate[m['id']]=stations
                                spacing=min(3.,self.model.u.sy)
                                q=1.5*(max(self.model.case.floor_dead+self.model.case.floor_live+self.model.case.partitions,
                                        self.model.case.roof_dead+2.)+1.)*spacing
                                ix=(80*120**3-68*108**3)/12
                                testspan=1000.
                                ratio=max(q*testspan**2/8/(ix/60*250/1.1),q*testspan/2/(2*6*108*250/math.sqrt(3)/1.1),
                                    5*(q/1.5)*testspan**4/(384*2e5*ix)/(testspan/360))
                                k=self.model.pre+'EDGE-RHS-1M'
                                if not any(v['id']==k for v in self.data['checks']):
                                    self.data['checks'].append(dict(id=k,description='Welded RHS 120 x 80 x 6 boundary bearer. Simple bending, shear and L/360 deflection at the maximum 1 m support interval.',
                                      utilization=round(ratio,5),status='pass' if ratio<=1 else 'fail',reference='IS 800 8.2, 8.4 and Table 6.'))
                                m['checks']=[k]
                        self.data['members'].append(m);self.members.append(m);secondaries.append(m)
                        area=sum(s.area for s in self.shapes_for(m['profile']))
                        self.extra_mass[m['level']]+=area*math.dist(a,b)*7.85e-6

    def adjust_bridging(self):
        purlins=[(m,self.moves[m['id']]) for m in self.members if m['id'] in self.moves]
        for m in self.members:
            if m['role'] not in ('purlin bridging','rafter flange brace','girder flange brace'):continue
            for side in (('end',) if 'flange brace' in m['role'] else ('start','end')):
                pt=m[side]
                for support,(a,b,dz) in purlins:
                    q=relative_plan_point({'start':a,'end':b},pt)
                    if q and abs(q[2]-pt[2])<1:
                        # Meet the rolled channel/joist web at the web centre.
                        width=frame(*endpoints(support),support.get('ref_direction'))[0]
                        dims=self.data['profiles'][support['profile']]['dimensions_mm']
                        x=(dims['tw']-dims['b'])/2 if self.data['profiles'][support['profile']]['family']=='C' else 0
                        m[side]=location(pt,(UP,dz),(width,x));break

    def complete(self):
        self.roof()
        from bearing_wall import fit_walls,fit_lean_to
        fit_lean_to(self)
        fit_walls(self)
        from eave_supports import fit as fit_eaves
        fit_eaves(self)
        self.deck_penetrations()
        review=self.model.pre+'-INSTALLED-BEARING'
        self.data['checks'].append(dict(id=review,status='review',description='Member bearing seats located on selected steel. Check the receiver flange, attachments for wind uplift, local bearing, welding and erection against final shop details.',
                    reference='IS 800:2007 8.7, Section 10; IS 801:1975 6.5 where applicable'))
        if self.missed:
            self.data['checks'].append(dict(id=self.model.pre+'-BEARING-OPEN',status='review',
                     description=f'{len(self.missed)} installed support contacts require geometric resolution. See bearing evidence.'))
        return dict(installed_surfaces=self.references,seat_steel_mass_kg_by_source_level={k:round(v,2) for k,v in self.mass.items()},
                    added_boundary_bearer_mass_kg_by_source_level={k:round(v,2) for k,v in self.extra_mass.items()},
                    source_workline_to_soffit=self.scope,physical_receiver_contacts=self.verified,open_contacts=self.missed),self.samples

    def deck_penetrations(self):
        """Cut own unit's columns through raised floors, including at panel corners."""
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        while_above=[r for r in self.members if r['role']=='column']
        for p in self.panels:
            if p['role'] not in ('floor deck','roof deck') or p['material']!='CONC':continue
            z=p['outline'][0][2];ex=p['outline'];raw=Polygon([(v[0],v[1]) for v in ex])
            blockers=[]
            for r in while_above:
                a,b=endpoints(r)
                if not min(a[2],b[2])<z+p['thickness_mm'] or not z<max(a[2],b[2]):continue
                if not contains(bounds(p),a,1000.):continue
                x,y,_=frame(a,b,r.get('ref_direction'))
                pts=[(a[0]+i*x[0]+j*y[0],a[1]+i*x[1]+j*y[1]) for sh in self.shapes_for(r['profile']) for i,j in sh.exterior.coords]
                from shapely.geometry import MultiPoint
                void=MultiPoint(pts).convex_hull.buffer(12,join_style=2)
                if raw.intersects(void):blockers.append(void)
            if not blockers:continue
            out=raw.difference(unary_union(blockers))
            if out.geom_type!='Polygon':raise ValueError(p['id']+' deck disconnected by the column openings')
            from shapely.geometry.polygon import orient
            out=orient(out,sign=1.)
            p['outline']=[[round(x,4),round(y,4),z] for x,y in list(out.exterior.coords)[:-1]]
            p['openings']=[[[round(x,4),round(y,4),z] for x,y in list(ring.coords)[:-1]] for ring in out.interiors]
            p['column_clearance_mm']=12.
            p['column_opening_count']=len(blockers)


def detail(model):
    return Fitting(model).complete()
