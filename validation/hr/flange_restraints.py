"""Size transverse restraint trusses between actual parallel framing lines."""
from collections import defaultdict
from functools import lru_cache
import math

import engine3d as E
import india_connections as C
import india_is800 as I8
import openseespy.opensees as ops
import sections as S


@lru_cache(maxsize=1)
def tubes():
    return sorted((s for s in S.list_chs('CHS') if S.props(s)['d']>=48),key=lambda s:S.props(s)['A'])


@lru_cache(maxsize=2048)
def capacity(section,span):
    p=S.props(section)
    mat=I8.material_for_section(p,'YST310',process='HFS')
    comp=I8.compression_capacity(p,mat['fy_MPa'],KLz_mm=span,KLy_mm=span,process='HFS')
    # Section 12 workshop CJP to an end shoe, effective perimeter excluding
    # 15% for interrupted access; use the lower parent-metal yield.
    weld=C.cjp_weld_capacity_N(t_mm=p['tw'],length_mm=.85*math.pi*p['d'],fy_MPa=min(250,mat['fy_MPa']),action='shear')
    limit=min(comp.get('Pd_N') or 0,p['A']*mat['fy_MPa']/1.1,weld.get('capacity_N') or 0)
    return limit if comp.get('KL_over_r_max',float('inf'))<=180 else 0


def locate(record,nodes,f,side):
    a,b=[nodes[i] for i in record['n']];depth=S.props(record['section'])['d']; run=record['along']
    if a[run]>b[run]:a,b=b,a
    length=math.dist(a,b);dz=(b[2]-a[2])/length;dh=(b[run]-a[run])/length
    point=[a[k]+f*(b[k]-a[k]) for k in range(3)]
    point[run]-=side*depth*dz/2;point[2]+=side*depth*dh/2
    return [round(k,4) for k in point]


def design(case,u,cfg,actions):
    beam_tags=set(actions.get('beam_tags',[]));columns=set(actions.get('column_tags',[]))
    if not beam_tags:return
    native=E.build(cfg,'Linear');nodes={n:list(ops.nodeCoord(n)) for n in ops.getNodeTags()};groups=defaultdict(list);required_tops={}
    if case.number==9:
        # The lower roof bears on both the secondary compression posts and
        # the split hall columns. Give these real bearing points the same
        # top/bottom flange support even though the roof girder is pinned.
        beam_tags.update(tag for tag,role in native.get('physical_roles',{}).items() if role=='lean-to roof beam')
    records={}
    for tag,kind,section,a,b in native['ele']:
        if tag in columns:required_tops[tag]=max((a,b),key=lambda n:nodes[n][2])
        if kind!='beam':continue
        pt,qt=nodes[a],nodes[b];index=max((0,1),key=lambda k:abs(pt[k]-qt[k]))
        if abs(pt[1-index]-qt[1-index])>1 or abs(pt[index]-qt[index])<100:continue
        aa,bb=sorted((a,b),key=lambda n:nodes[n][index]);pa,pb=nodes[aa],nodes[bb]
        key=(index,round(pa[index]),round(pb[index]),round(pa[2]),round(pb[2]))
        record={'tag':tag,'n':[aa,bb],'along':index,'section':section,'plane':(pa[1-index]+pb[1-index])/2,'key':key}
        groups[key].append(record);records[tag]=record
    near=min((25*S.props(records[t]['section'])['ry'] for t in beam_tags if t in records),default=0)
    if near<100:return
    pitch=max(100,min(2500,100*math.floor(.96*near/100)))
    pairs={};covered=set();covered_nodes=set();pieces=[];nodal=defaultdict(float);seen=set()
    for tag in sorted(beam_tags):
        a=records.get(tag)
        if not a:continue
        alternatives=[r for r in groups[a['key']] if r['tag']!=tag and abs(r['plane']-a['plane'])>100]
        if case.number==8:
            # The eave and ridge struts run parallel at different elevations.
            # Either actual section provides a permanent cross-frame support.
            alternatives=[r for r in records.values() if r['key'][:3]==a['key'][:3] and r['tag']!=tag and abs(r['plane']-a['plane'])>100]
        if not alternatives:continue
        b=min(alternatives,key=lambda r:(abs(r['plane']-a['plane']),r['tag']))
        pair=tuple(sorted((tag,b['tag'])))
        pairs.setdefault(pair,(a,b))
    for a,b in pairs.values():
        L=math.dist(*(nodes[n] for n in a['n']));count=math.ceil(L/pitch)
        # Both beam axes may require restraint at once. Account for the force
        # of both connected flanges before resolving the cross-frame diagonal.
        force=0.
        for member in (a,b):
            p=S.props(member['section']);fy=I8.material_for_section(p,cfg['steel_grade'])['fy_MPa']
            force+=.02*p['bf']*p['tf']*fy
        pair_ok=True
        for i in range(count+1):
            f=i/count
            for first,last in ((1,1),(-1,1),(1,-1)):
                start,end=locate(a,nodes,f,first),locate(b,nodes,f,last)
                # An independent crossing brace may share the endpoints of the
                # neighbouring panel's edge brace at a column joint.
                key=tuple(sorted((tuple(start),tuple(end))))
                span=math.dist(start,end);horizontal=abs(a['plane']-b['plane']);demand=force*span/horizontal
                span_ceiling=25*math.ceil(span/25)
                pick=next((s for s in tubes() if capacity(s,span_ceiling)>=1.15*demand),None)
                if not pick:pair_ok=False;continue
                if key in seen:continue
                seen.add(key);lim=capacity(pick,span_ceiling)
                pieces.append({'a':start,'b':end,'profile':pick,'source_beams':[a['tag'],b['tag']],
                    'role':'transverse flange tie' if first==last else 'diagonal flange restraint',
                    'force_N':round(demand,2),'capacity_N':round(lim,2)})
                weight=S.props(pick)['A']*span*7.85e-5
                for rec in (a,b):
                    for nd,fraction in zip(rec['n'],(1-f,f)):nodal[nd]+=weight*fraction/2
        if pair_ok:
            for rec in (a,b):covered.add(rec['tag']);covered_nodes.update(rec['n'])
    unbraced=sorted(beam_tags-covered)
    outstanding_columns=sorted(t for t,nd in required_tops.items() if nd not in covered_nodes)
    cfg['seismic_restraint_layout']={'members':pieces,'spacing_mm':pitch,'unsupported_beam_tags':unbraced,
                                     'unsupported_column_tags':outstanding_columns,'previous_native_package_sha256':actions['source_package_sha256']}
    if not unbraced:
        cfg['beam_lateral_bracing']={'default':{'near_end_mm':pitch,'elsewhere_mm':pitch,
              'basis':'Paired CHS three-member cross-frames at both flanges. See physical locations and local axial/CJP checks.'}}
    if columns and not outstanding_columns:cfg['column_lateral_support_both_flanges']=True
    elevations=[];h=0
    for k in cfg['heights']:h+=k;elevations.append(h)
    for nd,weight in nodal.items():
        if weight<1:continue
        level=1+min(range(len(elevations)),key=lambda i:abs(nodes[nd][2]-elevations[i]))
        cfg.setdefault('nodal_dead_loads',[]).append({'node':nd,'level':level,'Fz_N':-weight,'note':'Flange restraint tributary steel weight.'})


def draw(model):
    from handoff import check
    layout=model.cfg.get('seismic_restraint_layout') or {};groups={}
    for x in layout.get('members',[]):
        g=groups.setdefault(x['profile'],{'force':0,'ratio':0,'count':0})
        g['force']=max(g['force'],x['force_N']);g['ratio']=max(g['ratio'],x['force_N']/x['capacity_N']);g['count']+=1
    ids={sec:check(model.data['checks'],model.pre+f'RF-{sec}',f"{sec}, {g['count']} flange-restraint members, strength and CJP parent-metal check",'pass',g['ratio'],
              'IS 800:2007 7.1, 10.5.7.1.2, 12.11.3.3; IS 18168:2023 6.2') for sec,g in groups.items()}
    for i,x in enumerate(layout.get('members',[]),1):
        m=model.member(x['role'],x['profile'],x['a'],x['b'],material='YST310',checks=[ids[x['profile']]],mid=f'FLANGE-{i}',bind=False)
        m['supports']=[model.pre+'E'+str(t) for t in x['source_beams']]
    if groups:
        model.data['assumptions'].append('The transverse restraint brings the two flange levels to adjacent framing lines. Check the local end shoes, supporting web and transfer to the roof or floor diaphragm during fabrication coordination.')
