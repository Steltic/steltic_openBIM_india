"""Check the Hosur modal/static replays, including the finite ridge-link stiffness."""
import argparse
import ast
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
import sys


def inspect(path):
    nodes={};fix={};rows=[]
    for statement in ast.parse(path.read_text(encoding="utf-8")).body:
        call=statement.value if isinstance(statement,ast.Expr) else None
        if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute):continue
        if call.func.attr not in ("node","fix","element"):continue
        args=[ast.literal_eval(value) for value in call.args]
        if call.func.attr=="node":nodes[args[0]]=args[1:]
        elif call.func.attr=="fix":fix[args[0]]=args[1:]
        else:rows.append(args)
    n=Counter();seen={}
    for typ,tag,i,j,*details in rows:
        if tag in seen and (7001000<=tag<=7001024 or 7201000<=tag<7202000):
            assert seen[tag]==(typ,i,j,details),(path,tag)
            continue
        seen[tag]=(typ,i,j,details)
        if typ=="zeroLength":
            assert math.dist(nodes[i],nodes[j])<.001,(path,tag,nodes[i],nodes[j])
            if 7001000<=tag<=7001024:n["coincident_eave_springs"]+=1
        if typ=="twoNodeLink" and 7001014<=tag<=7001024:
            assert nodes[i][:2]==nodes[j][:2] and nodes[j][2]-nodes[i][2]==2250
            assert fix[i][3:5]==[1,1]
            assert details[0:3]==["-mat",990001,"-dir"] and details[4:]==["-orient",0,0,1,0,1,0,"-shearDist",1.,1.]
            n["ridge_X" if details[3]==3 else "ridge_Y"]+=1
        if 7201000<=tag<7202000:
            assert typ=="Truss" and details==[698.,1]
            assert nodes[i][0]==nodes[j][0] and nodes[i][2]==nodes[j][2]
            assert abs(nodes[j][1]-nodes[i][1])==6000
            assert abs(nodes[i][2]-(6500+2250*(1-abs(2*nodes[i][0]/18000-1))))<.01
            n["secondary_axial_worklines"]+=1
    assert n=={"coincident_eave_springs":14,"ridge_X":7,"ridge_Y":4,"secondary_axial_worklines":60},(path,n)
    return dict(counts=dict(n),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def check_link(direction):
    """Measure the tangent seen by the free ridge node in all six global DOFs."""
    import numpy as np
    import openseespy.opensees as ops
    from hosur import roof_link
    ops.wipe();ops.model("basic","-ndm",3,"-ndf",6)
    ops.node(1,0,0,6500);ops.node(2,0,0,8750);ops.node(3,0,0,8750)
    for fixed in (1,3):ops.fix(fixed,1,1,1,1,1,1)
    ops.uniaxialMaterial("Elastic",1,1.e9);ops.uniaxialMaterial("Elastic",2,1.)
    args=roof_link(("zeroLength",1,1,2,"-mat",1,"-dir",direction),ops.nodeCoord)
    ops.element(*args)
    # Identity test springs allow extraction of the tangent without singular
    # free rotations. Subtract exactly their unit contribution below.
    ops.element("zeroLength",2,3,2,"-mat",2,2,2,2,2,2,"-dir",1,2,3,4,5,6)
    ops.constraints("Plain");ops.numberer("Plain");ops.system("FullGeneral")
    ops.algorithm("Linear");ops.integrator("GimmeMCK",0.,0.,1.,0.);ops.analysis("Transient")
    assert ops.analyze(1,0.)==0
    K=np.array(ops.printA("-ret")).reshape(6,6)
    ordering=ops.nodeDOFs(2)
    actual=K[np.ix_(ordering,ordering)]-np.eye(6)
    expected=np.zeros((6,6));expected[direction-1,direction-1]=1.e9
    assert np.allclose(actual,expected,atol=.0001),actual
    return dict(direction="XY"[direction-1],rigidity_N_per_mm=actual[direction-1,direction-1],
                maximum_discrepancy=float(abs(actual-expected).max()))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("job",type=Path);p.add_argument("--hr",type=Path,required=True)
    p.add_argument("--corpus",type=Path,required=True);p.add_argument("--output",type=Path);a=p.parse_args()
    sys.path.insert(0,str(a.hr.resolve()/"steel_engine"))
    from briefs import cases
    from design import make
    import engine3d
    case=cases()[21];cfg=make(case,case.units[0],a.corpus.resolve())
    replays={n:inspect(a.job/n) for n in ("model_opensees.py","model_static.py")}
    tangent=[check_link(d) for d in (1,2)]
    periods,eigenvalues,ex,ey,_=engine3d.modal(cfg,3)
    assert len(periods)==3 and all(w>0 for w in eigenvalues) and min(sum(ex),sum(ey))>.99
    result=dict(case="IN_Ex21",replays=replays,finite_link_tangents=tangent,periods_s=periods,
                effective_mass_fraction_X=sum(ex),effective_mass_fraction_Y=sum(ey),
                calc_sha256=hashlib.sha256((a.job/"design/calc_package.json").read_bytes()).hexdigest(),
                governing_design="Native equivalent-static seismic analysis, 102 combinations; the modal check tests the three roof degrees of freedom.")
    data=json.dumps(result,indent=2,allow_nan=False)+"\n"
    if a.output:a.output.write_text(data,encoding="utf-8")
    print(data,end="")
