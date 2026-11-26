"""Set out gable CFS rails, their steel bearings and door openings from the native posts."""
import math
from collections import defaultdict

from enclosure import allowed_segments,doors
from handoff import check
from peb_envelope import flange,plus
from secondary import select_z
from steltic_openbim_india.geometry import cross,dot,frame,sub
from steltic_openbim_india.profiles import section_polygons


def section_range(m,profiles,n):
    x,y,_=frame(m['start'],m['end'],m.get('ref_direction'))
    vals=[dot(x,n)*u+dot(y,n)*v for p in section_polygons(profiles[m['profile']]) for u,v in p.exterior.coords]
    return min(vals),max(vals)


def door_frames(model,planes):
    data=model.data;pd=data['profiles'];members={m['id']:m for m in data['members']};pre=model.pre
    for key,(normal,skin) in planes.items():
        axis,side=key;along=(1,0,0) if axis=='X' else (0,1,0);height=(0,0,1)
        for j,(lo,hi,z) in enumerate(doors(model.case,model.u,axis,side),1):
            first,last=[members[f'{pre}JAMB-{axis}{side}-{j}-{i}'] for i in (1,2)]
            lintel=members[f'{pre}LINT-{axis}{side}-{j}']
            for m in (first,last,lintel):
                # The outside face of each MC aligns with the inside of the sheet.
                offset=skin-dot(normal,m['start'])-section_range(m,pd,normal)[1]
                for field in ('start','end'):m[field]=plus(m[field],normal,offset)
            jambs=[]
            for m,target,which in [(first,lo,1),(last,hi,0)]:
                low,high=section_range(m,pd,along)
                shift=target-dot(along,m['start'])-(high if which else low)
                for field in ('start','end'):m[field]=plus(m[field],along,shift)
                jambs.append(dot(along,m['start'])+(low if which else high))
            bottom=section_range(lintel,pd,height)[0]
            for field,target in zip(('start','end'),jambs):
                at=plus(lintel[field],along,target-dot(along,lintel[field]))
                lintel[field]=plus(at,height,z-at[2]-bottom)
            for m in (first,last,lintel):m['basis']='MC door frame placed outside the specified clear opening. Lintel underside and jamb faces define the opening.'


def install(model,roof_offset,long_wall_offset):
    d=model.data;u=model.u;p=d['profiles'];length=u.sy*u.ny*1000;width=u.sx*u.nx*1000;h=model.datums[-1]
    n=model.case.number;step=model.cfg['girt_spacing_mm'];members=d['members'];pd=model.cfg['load_plan']['wind_summary']['pd_kNm2']
    posts=[m for m in members if m['role'] in ('column','gable post') and abs(m['start'][1]-m['end'][1])<.1 and
           min(abs(m['start'][1]),abs(m['start'][1]-length))<.1]
    counts=defaultdict(int);max_gap=0;lo=3000 if n!=3 else 0
    gable_span={1:7500,2:8000,3:6800,4:7500,5:7500}[n]
    label,dims,dc=select_z(model.cfs,gable_span,step,1.35*pd,1.35*pd)
    model.profile_lookup[label]=dict(family='Z',dimensions_mm=dims)
    ck=check(d['checks'],model.pre+'Z-GABLE',f'Gable Z rail on a maximum {gable_span:g} mm span, {step:g} mm tributary height.',
             'pass' if dc<=1 else 'fail',dc,'IS 801 sections 5.2 and 6.3–6.5. Section geometry from IS 811.')
    planes={('Y',0):((-1,0,0),long_wall_offset),('Y',1):((1,0,0),width+long_wall_offset)}
    for end in (0,1):
        at=end*length;y_sign=1 if end else -1;nrm=(0,y_sign,0)
        end_posts=[m for m in posts if abs(m['start'][1]-at)<.1]
        face=max(section_range(m,p,nrm)[1] for m in end_posts);datum=face+16+dims['d']/2
        skin=face+16+dims['d'];planes['X',end]=(nrm,y_sign*at+skin);holes=doors(model.case,u,'X',end)
        for sheet in d['panels']:
            if sheet['role'] not in ('masonry dado','wall cladding') or f'-X{end}-' not in sheet['id']:continue
            if dot(cross(sub(sheet['outline'][1],sheet['outline'][0]),sub(sheet['outline'][2],sheet['outline'][0])),nrm)<0:sheet['outline'].reverse()
            for pt in sheet['outline']:pt[1]=at+y_sign*(skin-(sheet['thickness_mm'] if sheet['role']=='masonry dado' else 0))
        for i,(a,b) in enumerate(((0.,width/2),(width/2,width))):
            poly=[[x,y,model.roof_z(x)+roof_offset] for x,y in ((a,at),(b,at),(b,at+y_sign*skin),(a,at+y_sign*skin))]
            if not end:poly.reverse()
            model.panel('gable verge flashing',poly,.5,'SHEET',f'VERGE-{end}-{i}')
        # The webs are normal to the wall. Full-length sticks stop at the
        # architectural opening and get a separate detailing review at its jamb.
        count=math.ceil((h-lo)/step);dz=(h-lo)/count;peak=max(m['end'][2] for m in end_posts)
        zs=[lo+k*dz for k in range(0 if lo else 1,math.ceil((peak-lo)/dz)) if lo+k*dz<peak-120]
        for k,z in enumerate(zs):
            if any(0<=m['end'][2]-z<80 for m in end_posts):z-=90
            if any(abs(z-head)<80 for _,_,head in holes):z+=90
            supports={}
            for m in end_posts:
                a,b=m['start'],m['end']
                if min(a[2],b[2])-.1<=z<=max(a[2],b[2])+.1:
                    x=a[0]+(b[0]-a[0])*(z-a[2])/(b[2]-a[2]);supports[round(x,3)]=m
            for bay,(x0,x1) in enumerate(zip(sorted(supports),sorted(supports)[1:])):
                max_gap=max(max_gap,x1-x0)
                for seq,(start,finish) in enumerate(allowed_segments(x0,x1,z,holes)):
                    if finish-start<10:continue
                    m=model.member('gable girt',label,(start,at+y_sign*datum,z),(finish,at+y_sign*datum,z),ref=[0,0,1],
                                   material='IS801-FY240',checks=[ck],mid=f'GABLE-GIRT-{end}-{k}-{bay}-{seq}',bind=False)
                    counts['girts']+=1
                    vx,vy,_=frame(m['start'],m['end'],m['ref_direction'])
                    fu,fv=flange(p[label],dot(vy,nrm)<0)
                    wallpt=plus(plus(plus(m['start'],vx,fu),vy,fv),nrm,-dims['tw']/2)
                    for cx,sign in ((start,1),(finish,-1)):
                        host=supports.get(round(cx,3))
                        if host is None:continue
                        # Corner/inner portal deep axes lie in the gable plane.
                        # Use the side of the actual flange, away from the empty web bay.
                        hz=host['start'][2];hz2=host['end'][2]
                        depth0=p[host['profile']]['dimensions_mm']['d'];depth1=p[host.get('end_profile',host['profile'])]['dimensions_mm']['d']
                        hd=depth0+(depth1-depth0)*(z-hz)/(hz2-hz);tf=p[host['profile']]['dimensions_mm']['tf']
                        fx,fy,_=frame(host['start'],host['end'],host.get('ref_direction'))
                        edge=abs(dot(fx,nrm))>.8
                        xcentre=cx+sign*(hd/2-tf/2 if edge else 48)
                        if not start+2<xcentre<finish-2:continue
                        contact_depth=section_range(host,p,nrm)[1];top=at+y_sign*(face+16)
                        bottom=at+y_sign*contact_depth;zc=wallpt[2];bwidth=min(30,tf*.55) if edge else 55
                        # Vertical plate on the primary's outside face, extruded
                        # towards the inside Z flange. Keep its footprint within both.
                        corners=[[xcentre+a*bwidth/2,bottom,zc+b*12] for a,b in ((-1,-1),(1,-1),(1,1),(-1,1))]
                        if y_sign>0:corners.reverse()
                        tag=m['id']+('-LEFT' if sign>0 else '-RIGHT')
                        block=dict(id=tag+'-BL',kind='plate',material='E250B0',outline=corners,thickness_mm=abs(top-bottom))
                        d['connections'].append(dict(id=tag,unit=u.name,level=m['level'],type='gable girt bearing',
                            at=[xcentre,top,zc],members=[host['id'],m['id']],parts=[block],
                            parameters={'seat_width_mm':bwidth,'seat_height_mm':24,'packing_mm':abs(top-bottom)},
                            description='Steel packing beneath the inside Z flange. Gable panel and wind-post attachments, end welding and local bearing require supplier detailing.'))
                        counts['seats']+=1
    door_frames(model,planes)
    check(d['checks'],model.pre+'GABLE-SPAN',f"{counts['girts']} gable rails and {counts['seats']} steel bearing blocks. "
          f'Greatest actual post spacing {max_gap:g} mm.','pass' if max_gap<=gable_span+.1 else 'fail',max_gap/gable_span,
          'IS 801 member span from physical end-wall wind posts.')
    d['assumptions'].append('The endwall sheeting is set on outward-facing IS 811 Z rails. Remaining triangular verge infill, local corner closure, lap lengths, gable cleats and cladding fasteners require envelope detailing.')
    if n==3:d['assumptions'].append('Nagpur retains 6.0 m wind-column centres at the gable roof. Each first interior post shifts 800 mm towards the lower-X column below 6.8 m and returns to the grid in its upper shaft. The shutter has 6.0 m clear between jambs and below its lintel, with at least 52 mm beyond the clear dimensions to the projecting anchor shanks. Detail the full-strength shop directional change before fabrication.')
