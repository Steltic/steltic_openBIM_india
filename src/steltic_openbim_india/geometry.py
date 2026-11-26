"""Coordinate frames for physical section axes and arbitrary planar hosts, in mm."""

import math


EPS = 1e-7


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    ax, ay, az = a
    bx, by, bz = b
    return (ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx)


def unit(vector):
    length = math.hypot(*vector)
    if length < EPS:
        raise ValueError("zero length or parallel frame directions")
    return tuple(v / length for v in vector)


def frame(start, end, direction=None):
    """IFC local X is section width, local Y is depth and local Z is the axis."""
    z = unit(sub(end, start))
    if direction is None:
        width = cross((0, 0, 1), z)
        direction = (1, 0, 0) if math.hypot(*width) < EPS else width
    x = unit(sub(direction, tuple(dot(direction, z) * v for v in z)))
    return x, cross(z, x), z


def weld_outline(part):
    """Effective weld metal in the local width/depth plane, in millimetres."""
    if part.get("weld_type", "fillet") == "cjp":
        y = part["throat_mm"] / 2
        x = part.get("width_mm", part["throat_mm"]) / 2
        return [(-x, -y), (x, -y), (x, y), (-x, y)]
    leg = part["leg_mm"]
    return [(0., 0.), (leg, 0.), (0., leg)]


def plane(ring):
    """Right-handed plane whose normal follows the ordered outer boundary."""
    origin = ring[0]
    x = unit(sub(ring[1], origin))
    normal = tuple(sum(cross(sub(p, origin), sub(q, origin))[i]
                       for p, q in zip(ring, (*ring[1:], ring[0]))) for i in range(3))
    z = unit(normal)
    return origin, x, cross(z, x), z


def project(ring, basis):
    origin, x, y, z = basis
    points = []
    for p in ring:
        delta = sub(p, origin)
        if abs(dot(delta, z)) > 0.01:
            raise ValueError("vertices depart from their panel plane by more than 0.01 mm")
        points.append((dot(delta, x), dot(delta, y)))
    return points


def member_body_ends(member):
    """Physical end planes along the native analysis axis, in global mm."""
    a,b=member["start"],member["end"]
    if "end_cutbacks_mm" not in member:
        return a,b
    start,end=member["end_cutbacks_mm"]
    direction=unit(sub(b,a))
    return ([v+start*k for v,k in zip(a,direction)],[v-end*k for v,k in zip(b,direction)])
