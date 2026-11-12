"""Ranking geográfico basado únicamente en evidencia de fuentes; el CUIT no contiene ubicación."""
import re
import unicodedata

def norm(s):
    t=unicodedata.normalize("NFKD",str(s or "").lower())
    return re.sub(r"[^a-z0-9]","", "".join(c for c in t if not unicodedata.combining(c)))

def evaluate(record, localidad="", provincia="", domicilio=""):
    """Devuelve puntaje y estado. No descarta ausencia de datos como contradicción."""
    lp,pp,dp=norm(localidad),norm(provincia),norm(domicilio)
    rl,rp,rd=norm(record.get("localidad")),norm(record.get("provincia")),norm(record.get("domicilio"))
    if pp and rp and pp!=rp:
        return (-1,"provincia_contradictoria")
    if lp and rl and lp!=rl:
        return (-1,"localidad_contradictoria")
    score=0
    if pp and rp==pp: score+=3
    if lp and rl==lp: score+=5
    if dp and rd and (dp in rd or rd in dp): score+=10
    return (score,"coincidencia_geografica" if score else "ubicacion_no_verificada")

def rank(records, localidad="", provincia="", domicilio="", excluir_contradictorios=True):
    out=[]
    for record in records:
        score,status=evaluate(record,localidad,provincia,domicilio)
        if score<0 and excluir_contradictorios: continue
        out.append(dict(record,puntaje_geografico=score,estado_geografico=status))
    return sorted(out,key=lambda r:r["puntaje_geografico"],reverse=True)
