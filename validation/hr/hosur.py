"""Analysis links for Hosur's actual pitched truss and longitudinal roof steel."""
from math import isclose


PURLIN = {"section":"LZ260X75X20X1.6","area_mm2":698.0,"span_mm":6000.0,
          "basis":"IS 811 lipped Z catalogue. Axial-only in the primary model; CFS service bending separately."}


def roof_link(command, coordinate):
    """Use a finite link between the roof master plane and each elevated ridge node."""
    if command[0]!="zeroLength":
        return command
    element,tag,a,b,*options=command
    p,q=coordinate(a),coordinate(b)
    if all(isclose(i,j,abs_tol=.001) for i,j in zip(p,q)):
        return command
    if p[:2]!=q[:2] or q[2]<=p[2] or options[0]!="-mat" or options[2]!="-dir" or options[3] not in (1,2):
        raise ValueError(f"Unexpected Hosur diaphragm link endpoints or direction at {tag}")
    # Local x is vertical, y is global Y, z is minus global X. Put the centre
    # of shear at the retained projected node. Its rotations about X and Y are
    # fixed. Ridge rotations and vertical translation therefore remain free.
    return ("twoNodeLink",tag,a,b,"-mat",options[1],"-dir",3 if options[3]==1 else 2,
            "-orient",0,0,1,0,1,0,"-shearDist",1.,1.)


def purlin_lines(top,frame,design,ops):
    for point in (1,2,3,4,5,7,8,9,10,11):
        a,b=top[frame-1,point],top[frame,point]
        if abs(ops.nodeCoord(b)[1]-ops.nodeCoord(a)[1]-design["span_mm"])>.01:
            raise ValueError("Hosur purlin workpoints disagree with the selected service span")
        # Present these springs in both the modal construction and the native
        # static replay. The physical purlins are declared once by the CFS pack.
        ops.element("Truss",7_201_000+100*frame+point,a,b,design["area_mm2"],1)
