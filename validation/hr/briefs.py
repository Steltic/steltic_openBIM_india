"""Fresh design inputs transcribed from the active India HR building briefs. SI metres and kN.

Only building geometry, occupancy, site and imposed requirements are taken from the
brief. The selection engine derives the member sizes. Unit offsets locate independent
structures in one drawing coordinate system.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Unit:
    name: str
    nx: int
    ny: int
    sx: float
    sy: float
    heights: tuple
    offset: tuple = (0, 0)
    shape: str = 'rect'


@dataclass(frozen=True)
class Case:
    number: int
    city: str
    units: tuple
    system: tuple
    zone: str
    importance: float
    wind_town: str
    terrain: int
    roof_dead: float
    floor_dead: float = 3.0
    floor_live: float = 4.0
    partitions: float = 1.0
    rise: float = 0.0
    purlin_spacing: float = 1.5
    girt_spacing: float = 1.8
    collateral: float = 0.0
    pv: float = 0.0
    openings: float = 0.1
    k1: float = 1.0
    k3: float = 1.0
    k4: float = 1.0
    notes: tuple = ()


def levels(first, typical, count):
    return (first,) + (typical,) * (count - 1)


def rect(nx, ny, sx, sy, heights, **kw):
    return (Unit('Main', nx, ny, sx, sy, heights, **kw),)


OM = 'OMRF'
SM = 'SMRF'
OC = 'OCBF'
SC = 'SCBF'
EB = 'EBF'


def cases():
    bengaluru = dict(city='Bengaluru', units=rect(1, 10, 30, 7.5, (10,)), system=(OM, OC), zone='II',
                     importance=1, wind_town='Bangalore', terrain=3, roof_dead=.16, collateral=.15, rise=1.5)
    return {
        1: Case(1, **bengaluru),
        2: Case(2, 'Bhiwandi', rect(4, 12, 24, 9, (13,)), (SM, SC), 'III', 1, 'Mumbai', 2, .20,
                collateral=.25, pv=.15, rise=2.4, notes=('Mumbai wind and seismic site proxy; confirm the wind isotach and zone at 19.30 N, 73.06 E.',)),
        3: Case(3, 'Nagpur', rect(1, 8, 24, 7.5, (10,)), (OM, OC), 'II', 1, 'Nagpur', 3, .16, collateral=.10, rise=1.2),
        4: Case(4, 'Farrukhnagar', rect(1, 12, 30, 7.5, (10.5,)), (SM, SC), 'IV', 1, 'Delhi', 2, .20,
                collateral=.20, rise=1.5, notes=('Delhi/Gurugram site proxy; confirm zone and wind at 28.45 N, 76.82 E.',)),
        5: Case(5, **bengaluru, pv=.15*.75, notes=('Existing frame and all member sizes are frozen from the independently generated Ex1 schedule.',
                                                 'Array weight is 0.15 kN/m² on 75% of plan. Local clamps, rails, and design wind on PV require supplier details.')),
        6: Case(6, 'Hyderabad', rect(3, 4, 6, 8, (4.5,4.5), shape='mezzanine'), (OM, OM), 'II', 1, 'Hyderabad', 2, .55,
                floor_dead=3, floor_live=7.5, partitions=0, girt_spacing=2),
        7: Case(7, 'Visakhapatnam', rect(1, 8, 21, 9, (11.5,)), (OM, OC), 'II', 1, 'Visakhapatnam', 2, .55,
                rise=1.05, girt_spacing=2.3, k4=1.15),
        8: Case(8, 'Chennai', rect(1, 6, 24, 6, (8,)), (SM, SM), 'III', 1, 'Chennai', 2, .55,
                rise=1.2, girt_spacing=2, k4=1.15),
        9: Case(9, 'Shimla', rect(1, 8, 24, 7.5, (8,)), (SM, SC), 'IV', 1, 'Shimla', 2, .35,
                rise=3, girt_spacing=1.5, k3=1.2, notes=('Ridge-site factor 1.2 is an assumption pending topographical survey.',)),
        10: Case(10, 'Indore', rect(6, 4, 15, 15, (9.5,)), (SC, SC), 'III', 1.2, 'Indore', 3, .85,
                 openings=.03, purlin_spacing=2.5, girt_spacing=2.375,
                 notes=('Single-tenant mercantile occupancy over 200 persons. Owner verification of occupancy classification and measured bare-deck shear stiffness is outstanding.',)),
        11: Case(11, 'Jaipur', (Unit('Office',4,3,7.5,7.5,levels(4.2,3.6,4)), Unit('Workshop',4,2,7.5,7.5,(6,4.8),(30.4,0))),
                 (OC, OC), 'II', 1.2, 'Jaipur', 3, 2.8, notes=('A 400 mm joint is reserved. The workshop uses I=1.0, floor DL 3.5, and floor LL 5.0 kN/m².',)),
        12: Case(12, 'Chandigarh', (Unit('Classroom',3,2,8.5,8.5,(3.6,)*3), Unit('Link',2,2,8.5,8.5,(3.6,)*2,(25.75,8.5)),
                                    Unit('Gym',2,2,8.5,8.5,(8,),(43,17),'gym')), (SM, SM), 'IV', 1.5, 'Chandigarh', 3, 2.8,
                 openings=.04, notes=('250 mm seismic joints separate all three wings; gym roof DL 1.2 kN/m².',)),
        13: Case(13, 'New Delhi', rect(5,4,6,6,(3.6,)*5), (SC, SC), 'IV', 1.2, 'Delhi', 3, 2.8),
        14: Case(14, 'Kolkata', rect(5,4,7.5,7.5,(3.6,)*8), (SC, SC), 'III', 1.5, 'Kolkata', 3, 2.8, k1=1.08),
        15: Case(15, 'Pune', rect(7,5,9,9,levels(4.8,3.9,8),shape='stepped_l'), (EB, EB), 'III', 1.2, 'Pune', 3, 2.8,
                 notes=('Assumed 100 mm concrete topping of fck 25 MPa; verify diaphragm stiffness and openings with deck supplier.',)),
        16: Case(16, 'Mumbai', rect(4,4,7.5,7.5,(3.5,)*9), (SM, SM), 'III', 1.2, 'Mumbai', 3, 2.8),
        17: Case(17, 'Ahmedabad', rect(6,4,8.5,8.5,levels(4.5,3.6,10)), (SC, SC), 'III', 1.2, 'Ahmedabad', 3, 2.8),
        18: Case(18, 'Kochi', rect(4,3,9,9,levels(6.6,3.3,11)), (SM, SM), 'III', 1.2, 'Kochi', 3, 2.8),
        19: Case(19, 'Guwahati', (Unit('Flange',6,2,8.5,8.5,levels(4.2,3.2,12),(0,17.4)), Unit('Stem',2,2,8.5,8.5,levels(4.2,3.2,12),(17,0))),
                 (EB, EB), 'V', 1.2, 'Guwahati', 3, 2.8, floor_live=3, notes=('400 mm seismic joint is provisional pending displacement check.',)),
        20: Case(20, 'Noida', rect(3,2,9,9,levels(5.4,3.2,18)), (SC, SC), 'IV', 1.2, 'Noida', 3, 2.8),
        21: Case(21, 'Hosur', rect(1,6,18,6,(6.5,)), (OM, OC), 'II', 1, 'Bangalore', 3, .16,
                 collateral=.15, rise=2.25, notes=('Bengaluru is the brief’s 40 km site proxy, pending confirmation at the actual site.',)),
    }


def floor_cells(unit, storey):
    cells = {(i,j) for i in range(unit.nx) for j in range(unit.ny)}
    if unit.shape == 'mezzanine' and storey == 1:
        return {(i,j) for i,j in cells if i < 2}
    if unit.shape == 'stepped_l':
        return {(i,j) for i,j in cells if j >= 3 or (storey <= 5 and i < 4)}
    return cells


def vertices(cells):
    return {(i + di,j + dj) for i,j in cells for di,dj in ((0,0),(0,1),(1,0),(1,1))}
