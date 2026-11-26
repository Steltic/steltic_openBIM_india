"""First-pass layouts for the active CFS India briefs. Dimensions in m.

Each level comprises the union of the listed rectangles. This is the geometry
passed to the native structural analysis and to the physical member layout.
Closed edges and corners are identified from occupied cells, not bounding boxes.
"""
from dataclasses import dataclass
from itertools import accumulate


def seq(width, bays, offset=0):
    return [round(offset + width * i / bays, 6) for i in range(bays + 1)]


def join(*runs):
    return sorted(set(x for run in runs for x in run))


@dataclass
class Building:
    number: int
    site: str
    use: str
    zone: str
    soil: str
    x: list
    y: list
    heights: list
    regions: list
    notes: list

    @property
    def elevations(self):
        return [0, *accumulate(self.heights)]

    def cells(self, level):
        rects = self.regions[level - 1]
        return {(i, j) for i, (a, b) in enumerate(zip(self.x, self.x[1:]))
                for j, (c, d) in enumerate(zip(self.y, self.y[1:]))
                if any(x1 <= (a+b)/2 < x2 and y1 <= (c+d)/2 < y2 for x1,y1,x2,y2 in rects)}

    def nodes(self, level):
        return {(i+di, j+dj) for i,j in self.cells(level) for di,dj in ((0,0),(1,0),(0,1),(1,1))}

    def area(self, level):
        return sum((self.x[i+1]-self.x[i])*(self.y[j+1]-self.y[j]) for i,j in self.cells(level))

    def boundary(self, level):
        cells = self.cells(level)
        for i,j in sorted(cells):
            for side, other, a, b in (
                ("S",(i,j-1),(i,j),(i+1,j)), ("N",(i,j+1),(i,j+1),(i+1,j+1)),
                ("W",(i-1,j),(i,j),(i,j+1)), ("E",(i+1,j),(i+1,j),(i+1,j+1))):
                if other not in cells:
                    yield side, a, b

    def braces(self, level):
        # Brace the first and last panel on each continuous exterior line,
        # and slide internal brace lines to the re-entrant grid positions.
        available = self.nodes(level) & (self.nodes(level-1) if level>1 else self.nodes(level))
        lines = {}
        for side,a,b in self.boundary(level):
            if a not in available or b not in available:
                continue
            i,j = a
            if self.number in (1,2) and side in ("W","E"):
                continue
            if self.number==4 and side=="S" and j==0:
                continue
            if self.number==5 and side=="S" and 18 <= self.x[i] <= 27:
                continue
            dr, line, pos = ("X",j,i) if side in ("S","N") else ("Y",i,j)
            lines.setdefault((dr,line),[]).append(pos)
        output=set()
        for (dr,line),positions in lines.items():
            s=sorted(positions)
            for k,pos in enumerate(s):
                if k==0 or k==len(s)-1 or pos-1 not in s or pos+1 not in s or self.number==7:
                    output.add((dr,pos,line) if dr=="X" else (dr,line,pos))
        if self.number in (6,10,12,15):
            for dr,line in (("X",len(self.y)//2),("Y",len(self.x)//2)):
                limit=len(self.x)-1 if dr=="X" else len(self.y)-1
                valid=[]
                for pos in range(limit):
                    i,j=(pos,line) if dr=="X" else (line,pos)
                    if (i,j) in available and ((i+1,j) if dr=="X" else (i,j+1)) in available:
                        valid.append(pos)
                if valid:
                    for pos in {valid[0],valid[-1]}:
                        output.add((dr,pos,line) if dr=="X" else (dr,line,pos))
        return [list(edge) for edge in sorted(output)]


def all_buildings():
    out = []
    def add(city,use,zone,x,y,h,regions,notes,soil="medium"):
        if isinstance(regions[0],tuple):
            regions=[regions for _ in h]
        out.append(Building(len(out)+1,city,use,zone,soil,x,y,h,regions,notes))
    add("Chennai","general goods warehouse","III",seq(48,8),[0,18],[6],[(0,0,48,18)],
        ["Fixed-base transverse moment portals. Roof rises 1.5 m to the central ridge. End bays in both sidewalls are X-braced, with roof-plane bracing."])
    add("Srinagar","food storage","V",seq(76,19),[0,21],[8],[(0,0,76,21)],
        ["Ridge 9 m. Fixed transverse portals; longitudinal chevron frames with a 0.65 m eccentric link. No diaphragm credit for insulated panels.",
         "Freezer at -23 C. Specify E250 C and require a project-specific impact test at or below service temperature including welds and fasteners."])
    add("Hyderabad","general goods warehouse","II",[0,12,24],seq(30,6),[7],[(0,0,24,30)],
        ["Two 12 m gables rise to 8.4 m. Fixed-base paired channels. A 12 m by 8 m independently braced mezzanine at +3.5 m occupies the west span at the south end."])
    add("Nagpur","office and light industrial","II",seq(30,5),seq(36,6),[3.3,4.0],
        [[(6,24,30,36)],[(0,0,30,24),(6,24,30,36)]],
        ["Office wing 24 by 12 m adjoins the northeast corner. Align the upper office roof to the 7.3 m high-bay eave; upper storey 4.0 m (brief approximately 3.3 m). High-bay columns span continuously. The south storefront stays open with full-height bracing in its two returns and transverse bracing one bay back."])
    add("Visakhapatnam","motel residential","II",join(seq(10,2),seq(39,7,10)),join(seq(10,2),seq(21,4,10)),[3,2.85,2.85],
        [(0,0,49,10),(0,10,10,31)],["Retain continuous braced bays either side of the ground-level mid-bar breezeway. Exterior corridor load envelopes the guestrooms. Hot-dip galvanised members and coastal fasteners with compatible metals."])
    add("Coimbatore","outpatient clinic","III",seq(37,6),seq(21,4),[3,3.3,3.3,3.3],
        [[(0,0,37,10.5)]]+[[(0,0,37,21)]]*3,["South half walkout below north grade. North supports start at +3 m. Lower diaphragm is the south half only. The design uses the provisional imaging-suite load on every upper floor."])
    add("Delhi","residential flats","IV",[0,6,12],[0,4,8],[3]*4,[(0,0,12,8)],["Fixed-base 2 by 2 frame; 4 m joists, 400 mm centres; four flats per floor. 18 mm cement board."])
    add("Ahmedabad","student residence","III",join(seq(14.5,3),seq(14,3,14.5),seq(14.5,3,28.5)),
        join(seq(26,5),seq(14,3,26)),[3]+[2.95]*3,[(14.5,0,28.5,26),(0,26,43,40)],
        ["Two re-entrant corners at the T. Head and stem are supported on a common junction grid. Valley flashing and valley load buildup require separate detailing."])
    add("Lucknow","senior residential apartments","III",join(seq(20,4),seq(8,2,20),seq(12,2,28),seq(12,2,40)),[0,4,8,12,16,20],
        [3.2]+[2.9]*3, [[(0,0,20,20),(20,4,28,20),(28,0,52,20)]]*3+[[(0,0,20,20),(20,4,28,20),(28,0,40,20)]],
        ["Entry recess 8 by 4 m. East 12 m steps down one storey. Check the lower east roof and west pitched truss roof independently."])
    add("Mumbai","residential flats","III",seq(24,4),[0,5,7,12],[3]*5,[(0,0,24,12)],
        ["2 m double-loaded corridor flanked by 5 m spans. Protected external fasteners. Soil assumed soft pending site report."],soil="soft")
    add("Pune","multifamily residential","III",join(seq(19,3),seq(36,6,19)),join(seq(27,5),seq(19,4,27)),
        [3]+[2.9]*4,[(0,0,19,27),(0,27,55,46)],["North gabled wing and lower amenity roof over the west leg share the re-entrant collector line. Accessible deck carries a 4 kPa imposed load."])
    add("Bengaluru","student residence","II",seq(36,6),[0,5,7,12],[3.3]+[3]*5,[(0,0,36,12)],
        ["6 m longitudinal spacing. Braced corridor lines and end grids, 2 m central corridor, 400 mm stud spacing."])
    add("Surat","hotel","III",join(seq(38,7),seq(8,2,38),seq(38,7,46)),seq(54,12),
        [3.3]+[2.9]*5,[(0,36,46,54),(38,18,46,36),(38,0,84,18)],
        ["Two 46 by 18 m guest wings are joined by an 18 m long, 8 m wide corridor. Its opposite edges align with the end grids of the wings, producing two re-entrant corners. Mechanical roof allowance included."])
    add("Noida","residential over retail and parking","IV",seq(64,8),seq(40,8),[4,4]+[3]*5,
        [[(0,0,64,40)]]*2+[[(0,0,64,10),(0,10,16,40),(48,10,64,40)]]*5,
        ["Two full podium plates with composite deck, five residential levels forming a U open to the north. Braced lines continue below the U to the foundation. L1 retail and parking take 4.5 kPa permanent and 4 kPa imposed. L2 including the court takes 5.0 kPa permanent and 5 kPa imposed. Upper dwellings take 1.65 kPa permanent and 3 kPa imposed, plus partitions."])
    add("Kolkata","university dormitory residence","III",join(seq(14,2),seq(18,3,14),seq(14,2,32)),
        join(seq(14,3),seq(18,4,14),seq(14,3,32)),[3]+[2.9]*7,[(14,0,32,46),(0,14,46,32)],
        ["Core and four arms share a three-tier column schedule. Four re-entrant corners require a rigid/flexible diaphragm envelope. Soil assumed soft pending site report."],soil="soft")
    return out
