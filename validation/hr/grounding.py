"""Read the owner's fixed BIS corpus locally. Persist locators and digests only."""
import csv
import hashlib
import math
import re
from pathlib import Path


class Grounding:
    def __init__(self, root):
        self.root = Path(root) / 'documents' / 'standards'
        self.hits = []

    def table(self, stem, pattern, cite, select=None,inputs=None):
        paths = sorted((self.root / stem / 'tables').glob(pattern))
        if not paths:
            raise FileNotFoundError(f'{stem} {pattern}')
        path = paths[0]
        with path.open(encoding='utf-8-sig', newline='') as handle:
            rows=list(csv.reader(handle))
        selected=[i for i,r in enumerate(rows[1:],2) if select and select(r)]
        if select and not selected:raise ValueError(f'{cite} has no matching row in {path.name}')
        self.hit(stem, path, cite,selected=selected,inputs=inputs)
        return rows

    def hit(self, stem, path, cite,selected=None,inputs=None):
        rec = dict(stem=stem, found=True, cite=cite, query=cite,
                   source_path=path.relative_to(self.root).as_posix(),
                   sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        if selected:rec['csv_rows']=selected
        if inputs:rec['selected_inputs']=inputs
        if rec not in self.hits:
            self.hits.append(rec)

    def page(self, stem, search, cite, *, pages=None, inputs=None):
        folder = self.root / stem / 'markdown' / 'pages_search'
        paths=([folder/f'page_{n:03d}.md' for n in pages] if pages else sorted(folder.glob('*.md')))
        for path in paths:
            txt = path.read_text(encoding='utf-8', errors='replace')
            if re.search(search, txt, re.I):
                self.hit(stem, path, cite, inputs=inputs)
                self.hits[-1]['search_pattern']=search
                return
        self.hits.append(dict(stem=stem, found=False, query=search, cite=cite))

    def site(self,case):
        stem='IS_1893_Part_1_2016'
        value={'II':.10,'III':.16,'IV':.24,'V':.36}[case.zone]
        maps={10:[22.72,75.86],20:[28.54,77.39]}
        if case.number in maps:
            self.page(stem,r'FIG\. 1 SEISMIC ZONES OF INDIA','IS 1893 Part 1, Figure 1, '+case.city,
                      pages=[13],inputs={'source':'brief map reading; site verification required',
                          'latitude_longitude_deg':maps[case.number],'zone':case.zone,'Z':value})
            return
        towns={1:'Bangalore (Bengaluru)',2:'Mumbai',4:'Delhi',5:'Bangalore (Bengaluru)',
               7:'Vishakhapatnam',13:'Delhi',21:'Bangalore (Bengaluru)'}
        town=towns.get(case.number,case.city)
        proxy={2:44,4:46,21:40}.get(case.number)
        meta={'source':'site proxy' if proxy else 'Annex E town','town':town,'zone':case.zone,'Z':value}
        if proxy:
            meta['approximate_distance_km']=proxy
            meta['verification']='Check site coordinates against the adopted map before design release.'
        pattern=re.escape(town)+r'\s+'+case.zone+r'\s+'+re.escape(f'{value:.2f}')
        self.page(stem,pattern,'IS 1893 Part 1, Annex E, '+town,pages=[38,39],inputs=meta)

    def wind(self, case, z):
        stem = 'IS_875_Part_3_2015'
        city = {'Bangalore':'Bengaluru','Visakhapatnam':'Vishakapatnam'}.get(case.wind_town,case.wind_town)
        tabulated=city not in ('Indore','Kochi','Noida')
        csv_path=next((self.root/stem/'tables').glob('*_Table_AnnexA_recovered.csv'))
        with csv_path.open(encoding='utf-8-sig',newline='') as fh:rows=list(csv.reader(fh))
        speeds = {k.casefold(): float(v) for k,v in rows[1:] if v.strip().isdigit()}
        if tabulated:
            vb = speeds[city.casefold()]
            self.table(stem,'*_Table_AnnexA_recovered.csv',f'IS 875 Part 3, Annex A, {city}',
                       lambda r:r[0].casefold()==city.casefold(),{'town':city,'Vb_mps':vb,'site_proxy':case.number in (2,4,21),
                       **({'approximate_distance_km':{2:44,4:46,21:40}[case.number]} if case.number in (2,4,21) else {})})
        else:
            path = self.root / stem / 'tables' / (stem+'_Fig_1_readings_recovered.md')
            row = next(row for row in path.read_text(encoding='utf-8').splitlines() if row.startswith('| '+city))
            vb = float(row.split('|')[3].strip())
            self.hit(stem, path, f'IS 875 Part 3, Figure 1, {city}',inputs={'town':city,'Vb_mps':vb})
            self.hits[-1]['search_pattern']=r'^\| '+city
        height_path=next((self.root/stem/'tables').glob('*_Table_2_recovered.csv'))
        with height_path.open(encoding='utf-8-sig',newline='') as fh:rows=list(csv.reader(fh))
        vals = [(float(r[1]),float(r[case.terrain+1])) for r in rows[1:] if len(r)>4 and r[1].strip().isdigit()]
        k2 = vals[-1][1]
        band=[vals[-1][0]]
        if z <= vals[0][0]:
            k2 = vals[0][1]
            band=[vals[0][0]]
        else:
            for (za,ka),(zb,kb) in zip(vals,vals[1:]):
                if z <= zb:
                    k2 = ka+(kb-ka)*(z-za)/(zb-za)
                    band=[za,zb]
                    break
        self.table(stem,'*_Table_2_recovered.csv',f'IS 875 Part 3, Table 2, terrain {case.terrain} at {z:g} m',
                   lambda r:len(r)>4 and r[1].strip().isdigit() and float(r[1]) in band,
                   {'terrain':case.terrain,'height_m':round(z,4),'k2':round(k2,6)})
        return vb,k2,0.0006*(vb*case.k1*k2*case.k3*case.k4)**2

    def essentials(self, case,u):
        self.site(case)
        pitch=math.degrees(math.atan2(2*case.rise,u.nx*u.sx))
        self.table('IS_800_2007','*_Table_2_recovered.csv','IS 800 Table 2, local classification',
                   lambda r:len(r)>1 and ('flange' in r[0].lower() and ('rolled' in r[0].lower() or 'welded' in r[0].lower())))
        key='ii)' if pitch>10 else 'i)(b)'
        self.table('IS_875_Part_2_1987','*_Table_2_recovered.csv','IS 875 Part 2, Table 2, maintenance roof',
                   lambda r:r[0]==key,{'row':key,'pitch_deg':round(pitch,4),'roof_imposed_kNm2':round(roof_imposed(u,case.rise),5)})
        self.table('IS_1893_Part_1_2016','*_Table_3_recovered.csv','IS 1893 Part 1, Table 3, zone factor',
                   lambda r:r[0]=='Z',{'zone':case.zone,'Z':{'II':.10,'III':.16,'IV':.24,'V':.36}[case.zone]})
        importance=1 if u.name=='Workshop' else case.importance
        row='i)' if importance==1.5 else 'ii)' if importance==1.2 else 'iii)'
        self.table('IS_1893_Part_1_2016','*_Table_8_recovered.csv','IS 1893 Part 1, Table 8 importance',
                   lambda r:r[0]==row,{'I':importance,'row':row})
        codes={'OMRF':'i)(c)','SMRF':'i)(d)','OCBF':'ii)(a)','SCBF':'ii)(b)','EBF':'ii)(c)'}
        self.table('IS_1893_Part_1_2016','*_Table_9_recovered.csv','IS 1893 Part 1, Table 9 steel framing systems',
                   lambda r:r[0] in [codes[s] for s in case.system],{'system_x':case.system[0],'system_y':case.system[1]})
        if case.number in (6,10,11,12,13,14,15,16,17,18,19,20):
            keys={6:['viii)(a)'],10:['vi)(a)'],11:['v)(b)','vii)(b)(1)'],12:['ii)(a)','ii)(m)'],
                  14:['iii)(g)'],19:['i)(a)(3)']}.get(case.number,['v)(b)'])
            if case.number==11:keys=['vii)(b)(1)'] if u.name=='Workshop' else ['v)(b)']
            self.table('IS_875_Part_2_1987','*_Table_1_recovered.csv','IS 875 Part 2, Table 1 occupancy',
                       lambda r:r[0] in keys,{'occupancy_rows':keys})
        self.page('IS_875_Part_1_2026',r'Density of steel sections','IS 875 Part 1, Table 1 item 49, steel self-weight',
                  pages=[22],inputs={'steel_unit_weight_kN_per_m3':78.5})
        self.page('IS_2062_Part_1_2025',r'E\s*350\s*\|\s*B0' if case.number<=5 else r'E\s*250\s*\|\s*B0','IS 2062 Part 1, Table 3, grade and plate thickness',
                  pages=[9],inputs={'grade':'E350' if case.number<=5 else 'E250 B0','basis':'Native thickness band per section'})
        self.table('IS_800_2007','*_Table_4_recovered.csv','IS 800 Table 4, load combinations',
                   lambda r:r[0].startswith(('DL+LL+CL','DL+WL/EL')),{'native_expansion':'IS 800 Table 4 with IS 1893 and Section 12 rows as applicable'})
        self.table('IS_1893_Part_1_2016','*_Table_6.4.2_spectrum_recovered.csv','IS 1893 Part 1, 6.4.2, horizontal design spectrum',
                   lambda r:'Type II)' in r[0],{'soil':'II','damping_percent':5})
        self.page('IS_808_2021',r'SECTIONAL PROPERTIES','IS 808, section 9 and dimensional tables',pages=[6])
        if case.zone != 'II':
            self.page('IS_18168_2023',r'overstrength','IS 18168, earthquake-resistant steel design')
        if 'SMRF' in case.system:
            self.page('IS_800_2007',r'12\.11\.3\.3','IS 800 12.11.3.3, column restraint at both beam-flange levels',
                      pages=[96],inputs={'minimum_fraction_of_beam_flange_strength':.02})
            self.page('IS_18168_2023',r'6\.2\s+','IS 18168 section 6.2, seismic beam flange restraints',pages=[9])
        if case.number in (9,10):
            self.page('IS_875_Part_4_1987',r'4\.4 Ponding Instability','IS 875 Part 4:2021, 4.4, drainage after deflection',pages=[4])

    def shimla_snow(self):
        stem = 'IS_875_Part_4_1987'
        rows = self.table(stem,'*_Fig_1_recovered.csv','IS 875 Part 4:2021, Figure 1, Shimla',
                          lambda r:r[0]=='Shimla',{'altitude_m':2200,'snow_zone':1})
        zone = next(int(r[5]) for r in rows[1:] if r[0]=='Shimla')
        return 1.624*(zone-.5)*(1+(2200/2677)**2)


def roof_imposed(unit, rise):
    angle = math.degrees(math.atan2(2*rise,unit.nx*unit.sx))
    return max(.40,.75-.02*max(0,angle-10))
