"""Special member geometry added to the native frame builder for shed jobs."""
import math

import engine3d as E
import frame_build as FB
import openseespy.opensees as ops
import peb_build as PB
import sections as S


_COMMANDS=('wipe','model','node','fix','geomTransf','element','rigidDiaphragm','mass','uniaxialMaterial','equalDOF','rigidLink')
_NATIVE={k:getattr(ops,k) for k in _COMMANDS}


def specialized(case,u,cfg):
    n=case.number
    if not case.rise:
        return
    cfg['integration_case']=n
    cfg['integration_shape']=[u.nx,u.ny,u.sx*1000,u.sy*1000,sum(u.heights)*1000,case.rise*1000]
    if n in (3,7):
        heavy=n==7
        rail=8500 if heavy else 7500
        cfg['crane']=dict(capacity_kN=200 if heavy else 100,crab_kN=40 if heavy else 15,bridge_kN=180 if heavy else 60,
                          span_mm=19500 if heavy else 22500,hook_approach_mm=1000 if heavy else 900,
                          wheels_per_side=2,wheel_base_mm=3500 if heavy else 3000,gantry_span_mm=u.sy*1000,
                          **{'class':'II'},type='electric',operation='pendant',span_axis='X',rail_height_mm=rail,
                          bracket_eccentricity_mm=600 if heavy else 750,
                          bracket_nodes={'L':8000000+u.ny//2,'R':8000000+100*u.nx+u.ny//2},
                          fatigue={'detail_category_MPa':92,'cycles':2000000,'gamma_mft':1.35})
        cr=cfg['crane']
        if n==7:
            from crane_runway import design
            design(cfg)
        # Gantry self-weight is added as a nodal allowance at every bracket (unmodelled runway beam).
        cfg['nodal_dead_loads']=[dict(node=8000000+100*i+j,level=1,Fz_N=-(25.4 if heavy else 14.5)*1000*(.5 if j in (0,u.ny) else 1),
                                      note='Gantry, rail and fixtures, delivered at bracket node.')
                                 for i in (0,u.nx) for j in range(u.ny+1)]
    if n==21:
        from hosur import PURLIN
        cfg["hosur_roof_purlin"]=dict(PURLIN)
        S.register_double_angle('PAIRISA150','ISA150X150X15',8)
        cfg['gold']['col_sec']['lateral']={'default':'MB600'}
        cfg['_gold']['col_sec']=lambda i,j,k:'MB600'
        cfg['truss_candidate']={'top':'PAIRISA150','bottom':'PAIRISA150','web':'ISA90X90X8','knee':'ISA120X120X12'}
        cfg['truss_connections']={'default':dict(n_bolts=4,d_mm=20,grade='8.8',d0_mm=22,pitch_mm=65,end_mm=45,gauge_mm=45,
             gusset_t_mm=8,gusset_grade='E250',edge='rolled',fixity='hinged',gusset_edge_mm=45,packing_t_mm=8,
             bolt_type='HSFG',slip_surface='sand_blasted',stitch_bolt_d_mm=20,
             gusset_support='two_edges',gusset_free_mm=120,gusset_width_mm=250),
             'truss_knee_brace':{'n_bolts':10,'d_mm':24,'d0_mm':26,'pitch_mm':65,'gauge_mm':60,'end_mm':52,
                                 'gusset_edge_mm':80,'gusset_width_mm':500,'gusset_t_mm':20,'gusset_support':'one_edge'},
             'knee_gusset':{'face_length_mm':1050,'projection_mm':650,'t_mm':20,'grade':'E250','weld':'cjp',
                            'angle_clearance_mm':20,'edge_cut':'machine flame'},
             'knee_chord_node':{'toward_column_mm':650,'toward_midspan_mm':350,'above_mm':420,'below_mm':660,'t_mm':8,
                                'gusset_grade':'E250','chord_heel':'bottom','angle_clearance_mm':15,'edge_cut':'machine flame',
                                'n_bolts':10,'d_mm':24,'d0_mm':26,'pitch_mm':75,'end_mm':50,'gauge_mm':70,'grade':'8.8'},
             'heel':{'n_bolts':6,'d_mm':24,'d0_mm':26,'grade':'8.8','pitch_mm':75,'end_mm':55,'t_plate_mm':20,
                     'fu_plate_MPa':410,'nn':2,'ns':0,'bolt_type':'HSFG','slip_surface':'sand_blasted','cap_weld':'cjp'}}
        cfg['roof_planes'][0]['purlins_at_nodes']=True
    if n==9:
        import india_loads as loads
        dx=12000.;sy=u.sy*1000
        s0=cfg['snow']/.8
        drift=loads.snow_drift_5_2_4(s0,3.,12.,12.,beta_upper_deg=math.degrees(math.atan(.25)))
        cfg['lower_roof_snow_drift']=drift
        # Integrate the triangular surcharge at the actual transverse beam stations.
        l3=drift['l3_m']*1000
        mu1=drift['mu1'];mu2=drift['mu2']
        cfg['nodal_dead_loads']=[];cfg['nodal_imposed_loads']=[];cfg['nodal_snow_loads']=[]
        for j in range(5):
            trib=sy*(.5 if j in (0,4) else 1)
            for i in range(5):
                a=max(0,(i-.5)*dx/4);b=min(dx,(i+.5)*dx/4)
                nd=150000+j*100+i
                area=trib*(b-a)/1e6
                def integral(x):
                    t=min(x,l3)
                    return s0*(mu1*x+(mu2-mu1)*(t-t*t/(2*l3)))
                for target,force in [('nodal_dead_loads',2.5*area),('nodal_imposed_loads',.75*area),
                                    ('nodal_snow_loads',trib*(integral(b)-integral(a))/1e6)]:
                    cfg[target].append(dict(node=nd,level=1,kind='roof',Fz_N=-force*1000,note='Attached lower roof tributary'))
    cfg['custom_build']=ordered_build


def ordered_build(cfg,transf='PDelta'):
    """Present the finished physical elements to Steltic's staticizer in registry order.

    Steltic records the builder's OpenSees calls and pairs each element with the
    metadata at the same row index. Geometry construction below replaces individual
    frame segments; replay only the final model after assembling those segments.
    Auxiliary roof springs follow all physical elements. Recompute masses from the
    active cfg on every invocation, including after Steltic sets the steel self-weight.
    """
    entries={k:[] for k in _COMMANDS}
    previous={k:getattr(ops,k) for k in _COMMANDS}
    def record(key):
        def wrapped(*args):
            if key=="element" and cfg.get("integration_case")==21 and args[0]=="zeroLength":
                from hosur import roof_link
                args=roof_link(args,ops.nodeCoord)
            value=_NATIVE[key](*args)
            entries[key].append(args)
            return value
        return wrapped
    try:
        for key in _COMMANDS: setattr(ops,key,record(key))
        info=shed_build(cfg,transf)
        active=set(ops.getEleTags())
    finally:
        for key,op in previous.items(): setattr(ops,key,op)
    final_elements={a[1]:a for a in entries['element'] if a[1] in active}
    physical=[row[0] for row in info['ele']]
    aux=sorted(active-set(physical))
    for key in ('wipe','model','node','fix','geomTransf','uniaxialMaterial'):
        for args in entries[key]: previous[key](*args)
    for tag in physical+aux:
        previous['element'](*final_elements[tag])
    for key in ('equalDOF','rigidLink','rigidDiaphragm','mass'):
        for args in entries[key]: previous[key](*args)
    return info


def shed_build(cfg,transf='PDelta'):
    info=FB.frame_build(cfg,transf)
    n=cfg['integration_case']
    nx,ny,sx,sy,h,rise=cfg['integration_shape']
    nx,ny=int(nx),int(ny)
    width=nx*sx
    el=info['ele']
    tag=max(x[0] for x in el)+1
    roles={}; knees=[]
    def add(kind,sec,a,b,role,*,strong='X',release=None,truss=None,group=None):
        nonlocal tag
        if kind=='col': E.add_column(tag,a,b,sec,strong,releases=release)
        elif kind=='truss': E.add_truss(tag,a,b,sec,truss=truss,group=group)
        elif kind=='brace': ops.element('Truss',tag,a,b,S.props(sec)['A'],1)
        else: E.add_beam(tag,a,b,sec,releases=release)
        if group in ('top_chord','bottom_chord'):E.register_truss_member(tag,truss=truss,group=group,sec=sec)
        el.append((tag,kind,sec,a,b));roles[tag]=role
        tag+=1
        return tag-1
    def node(ident,x,y,z):
        ops.node(ident,x,y,z)
        return ident
    if n in (1,2,3,4,5,7):
        for row in list(el):
            t,kind,sec,a,b=row
            if kind!='col': continue
            i=(a%100000)//100; j=a%100
            if n==7 and i not in (0,nx): continue
            ops.remove('element',t);el.remove(row)
            lab=(cfg['gold'].get('peb_column',sec) if i in (0,nx)
                 else cfg['gold'].get('interior_peb_col',sec))
            if n==7:
                rail=cfg['crane']['rail_height_mm']
                station=node(8000000+100*i+j,i*sx,j*sy,rail)
                add('col',lab,a,station,'column'); add('col',lab,station,b,'column')
            else:
                kw={'extra_stations_mm':[cfg['canopy_axis_height_mm']]} if n==2 and i==nx else (
                    {'extra_stations_mm':[cfg['crane']['rail_height_mm']]} if n==3 else {})
                release='J' if n==2 and i not in (0,nx) else None
                tag=PB.column(tag,el,a,b,lab,'X',i=i,j=j,releases=release,**kw)
        if n==2:
            canopy_z=cfg['canopy_axis_height_mm']
            for j in range(ny+1):
                inner=PB.station_node(f'C{nx}-{j}',canopy_z)
                face=PB.section_at(cfg['gold']['peb_column'],canopy_z/h)
                offset=S.props(face)['d']/2
                end_plate_node=node(7500000+j,width+offset,sy*j,canopy_z)
                # A finite column panel arm transmits the canopy moment from the
                # flange face to its centreline. The panel steel is in the column
                # take-off; this internal force-transfer element has no extra mass.
                panel_section='WI700X300X20X12'
                PB.ensure(panel_section)
                E.add_beam(7840000+j,inner,end_plate_node,panel_section)
                canopy_nodes=[end_plate_node]+[node(7510000+100*k+j,width+offset+750*k,sy*j,canopy_z)
                                                for k in range(1,9)]
                lab='TI700-300X300X20X12'
                PB.ensure(lab)
                tag=PB.beam(tag,el,canopy_nodes,lab,kind='canopy',member_id=f'DOCK-{j+1}')
    # End-wall wind posts are located at the brief's specified gable intervals;
    # the bearing rafter is split at a station when an existing native node is unavailable.
    if n in (1,2,3,4,5,21):
        spacing={1:7500,2:8000,3:6000,4:7500,5:7500,21:6000}[n]
        for j in (0,ny):
            y=j*sy
            for i in range(1,round(width/spacing)):
                x=i*spacing
                if any(abs(x-q*sx)<1 for q in range(nx+1)): continue
                z=h+rise*(1-abs(2*x/width-1))
                if n==21: continue  # truss panel nodes are installed below
                top=next((a for a in ops.getNodeTags() if math.dist(ops.nodeCoord(a),(x,y,z))<1),None)
                if top is None:
                    host=next((r for r in el if r[1]=='beam' and all(abs(ops.nodeCoord(nd)[1]-y)<1 for nd in r[3:]) and
                               min(ops.nodeCoord(nd)[0] for nd in r[3:])<x<max(ops.nodeCoord(nd)[0] for nd in r[3:])),None)
                    if host is None: raise ValueError(f'Gable post at {x} has no bearing rafter')
                    t,_,sec,a,b=host
                    top=node(150000+100*i+j,x,y,z)
                    ops.remove('element',t);el.remove(host)
                    add('beam',sec,a,top,'gable rafter');add('beam',sec,top,b,'gable rafter')
                post_below=x-800 if n==3 and i==1 else x
                base=node(50000+100*i+j,post_below,y,0)
                ops.fix(base,1,1,1,0,0,0)
                section=cfg.get('gable_post_section','MB450')
                if post_below!=x:
                    # Keep the 6 m roof bearing grid. The cranked upper shaft
                    # returns to it above the 6 m clear rectangular shutter.
                    turn=node(55000+100*i+j,post_below,y,6800.)
                    add('col',section,base,turn,'gable post',strong='Y')
                    add('col',section,turn,top,'gable post',strong='Y',release='J')
                else:add('col',section,base,top,'gable post',strong='Y',release='J')
    if n==21:
        # Rebuild each X-plane as a 12-panel Pratt truss at its true pitch.
        for row in list(el):
            t,kind,sec,a,b=row
            ca,cb=ops.nodeCoord(a),ops.nodeCoord(b)
            if kind=='beam' and abs(ca[1]-cb[1])<1 and abs(ca[0]-cb[0])>1:
                ops.remove('element',t);el.remove(row)
        tc,bc={},{}
        for j in range(ny+1):
            for p in range(13):
                x=p*width/12; y=j*sy
                if p in (0,12):
                    tp=bp=E.ntag(int(p==12),j,1)
                else:
                    z=h+rise*(1-abs(p-6)/6)
                    tp=next((nd for nd in ops.getNodeTags() if math.dist(ops.nodeCoord(nd),(x,y,z))<1),None)
                    if tp is None: tp=node(7310000+j*100+p,x,y,z)
                    bp=node(7320000+j*100+p,x,y,h)
                tc[j,p]=tp;bc[j,p]=bp
            for p in range(12):
                release=('I','I') if p==0 else ('J','J') if p==11 else None
                add('beam',cfg['truss_candidate']['top'],tc[j,p],tc[j,p+1],'truss top chord',group='top_chord',truss=f'T{j+1}',release=release)
                add('beam',cfg['truss_candidate']['bottom'],bc[j,p],bc[j,p+1],'truss bottom chord',group='bottom_chord',truss=f'T{j+1}',release=release)
                if 0<p<11:
                    a,b=(tc[j,p],bc[j,p+1]) if p<6 else (bc[j,p],tc[j,p+1])
                    add('truss','ISA90X90X8',a,b,'truss diagonal',group='diagonal',truss=f'T{j+1}')
            for p in range(1,12):
                add('truss','ISA90X90X8',bc[j,p],tc[j,p],'truss vertical',group='vertical',truss=f'T{j+1}')
            for ix,p in ((0,1),(1,11)):
                col=next(r for r in el if r[1]=='col' and r[3]==E.ntag(ix,j,0))
                t,_,sec,a,b=col
                knee=node(7330000+j*100+p,ix*width,j*sy,h-1500)
                ops.remove('element',t);el.remove(col)
                add('col',sec,a,knee,'column');add('col',sec,knee,b,'column')
                br=add('truss','ISA120X120X12',knee,bc[j,p],'knee brace',group='knee_brace',truss=f'T{j+1}')
                knees.append(dict(id=f'K{j+1}-{ix}',heel_node=b,knee_node=knee,chord_node=bc[j,p],brace_tag=br,
                                  truss=f'T{j+1}',span_mm=width,trib_mm=sy*(.5 if j in (0,ny) else 1.)))
            if j in (0,ny):
                for p in (4,8):
                    # The native splice gate uses floor-encoded node tags. A
                    # ground-level wind-post foot must be in the level-0 range.
                    base=node(50000+100*j+p,p*width/12,j*sy,0)
                    ops.fix(base,1,1,1,0,0,0)
                    add('col','MB600',base,tc[j,p],'gable post',strong='Y')
            if j:
                for p in (3,6,9): add('brace','CHS168.3X8',bc[j-1,p],bc[j,p],'bottom chord tie')
                if j in (1,ny):
                    for p in range(12):
                        add('truss','ISA200X200X20',tc[j-1,p],tc[j,p+1],'roof brace',group='roof_plan',truss=f'End{j}')
                        add('truss','ISA200X200X20',tc[j-1,p+1],tc[j,p],'roof brace',group='roof_plan',truss=f'End{j}')
                from hosur import purlin_lines
                purlin_lines(tc,j,cfg["hosur_roof_purlin"],ops)
        info['truss_roles']=roles
        info['truss_knees']=knees
    if n==9:
        # The lean-to is supported at the hall column at 5 m. Five points per
        # transverse beam receive the integrated lower-roof gravity/snow loading.
        for j in range(5):
            y=j*sy; web=[]
            for i in range(5):web.append(node(150000+j*100+i,-i*3000,y,5000))
            old=next(r for r in el if r[1]=='col' and r[3]==E.ntag(0,j,0))
            t,_,section,a,b=old
            ops.remove('element',t);el.remove(old)
            add('col',section,a,web[0],'column'); add('col',section,web[0],b,'column')
            foot=node(70000+j,-12000,y,0)
            ops.fix(foot,1,1,1,1,1,1)
            add('col',cfg['lean_column'],foot,web[-1],'lean-to column')
            for i,(a,b) in enumerate(zip(web,web[1:])):
                release=('I','I') if i==0 else ('J','J') if i==3 else None
                add('beam',cfg['lean_beam'],a,b,'lean-to roof beam',release=release)
            if j:
                for i in (1,2,3,4):add('beam',cfg['lean_purlin'],150000+(j-1)*100+i,web[i],'lean-to purlin',release=('both','both'))
                if j in (1,4):
                    add('brace',cfg['brace'],70000+j-1,web[-1],'lean-to wall brace')
                    add('brace',cfg['brace'],foot,150000+(j-1)*100+4,'lean-to wall brace')
        off_level=[r for r in el if roles.get(r[0]) in ('lean-to roof beam','lean-to purlin')]
        # Interior load stations are points on one continuous rolled girder.
        # The purlins at those stations are pin-ended, so none is a moment
        # joint in the lateral system. Preserve the actual FE stiffness and
        # tag only the physical moment joints for the native connection gate.
        E._MOMENT_NODES.difference_update(150000+j*100+i for j in range(5) for i in (1,2,3))
        if not cfg.get('_lean_nodal_steel'):
            for t,_,sec,a,b in off_level:
                half=S.props(sec)['A']*math.dist(ops.nodeCoord(a),ops.nodeCoord(b))*7.85e-5/2
                for nd in (a,b):
                    cfg['nodal_dead_loads'].append(dict(node=nd,level=1,Fz_N=-half,note=f'Lean-to steel, half self-weight of e{t}'))
            cfg['_lean_nodal_steel']=True
        cfg['self_weight_in_nodal_loads']={'tags':[r[0] for r in off_level],'cite':'IS 875 Part 1, structural steel unit weight',
                                         'note':'Lower-roof beams are below the main diaphragm; both half reactions of every listed member are included explicitly.'}
    PB.finish(info)
    info['physical_roles']=roles
    return info
