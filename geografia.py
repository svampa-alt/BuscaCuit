"""Ranking contextual: cercanía al domicilio comercial, nunca exclusión por provincia fiscal."""
import math
import re
import unicodedata

def norm(s):
    t=unicodedata.normalize("NFKD",str(s or "").lower())
    return re.sub(r"[^a-z0-9]","", "".join(c for c in t if not unicodedata.combining(c)))

def distance_km(a,b):
    lat1,lon1=map(math.radians,map(float,a))
    lat2,lon2=map(math.radians,map(float,b))
    dlat=lat2-lat1
    dlon=lon2-lon1
    h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371.0088*2*math.asin(min(1,math.sqrt(h)))

def evaluate(record, localidad="", provincia="", domicilio="", coordenadas=None):
    """Domicilio comercial y sucursales priman sobre domicilio fiscal."""
    wanted=(norm(localidad),norm(provincia),norm(domicilio))
    locations=record.get("establecimientos") or [record]
    best=(0,"ubicacion_no_verificada")
    for loc in locations:
        rl,rp,rd=(norm(loc.get(k)) for k in ("localidad","provincia","domicilio"))
        score=0
        if wanted[1] and rp==wanted[1]: score+=10
        if wanted[0] and rl==wanted[0]: score+=20
        if wanted[2] and rd and (wanted[2] in rd or rd in wanted[2]): score+=60
        if coordenadas and loc.get("latitud") is not None and loc.get("longitud") is not None:
            km=distance_km(coordenadas,(loc["latitud"],loc["longitud"]))
            score+=max(0,50-10*km)
        if score>best[0]: best=(score,"coincidencia_geografica")
    return best

def rank(records, localidad="", provincia="", domicilio="", excluir_contradictorios=False, coordenadas=None):
    """Mantiene candidatos lejanos: el domicilio fiscal puede diferir del comercial."""
    out=[]
    for record in records:
        score,status=evaluate(record,localidad,provincia,domicilio,coordenadas)
        out.append(dict(record,puntaje_geografico=score,estado_geografico=status))
    return sorted(out,key=lambda r:r["puntaje_geografico"],reverse=True)
