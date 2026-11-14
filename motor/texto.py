"""Normalizacion compartida de nombres, domicilios, jurisdicciones y CUIT."""
import re
import unicodedata

SOCIETARIAS = {"SA", "SRL", "SAS", "SAU", "SACI", "SAIC", "SCA", "SH", "SOCIEDAD", "ANONIMA",
               "RESPONSABILIDAD", "LIMITADA", "SIMPLIFICADA", "ACCIONES", "POR", "CIA", "COMPANIA"}
ARTICULOS = {"DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "E", "EN"}
RUBROS = {"BAR", "CAFE", "RESTAURANTE", "RESTO", "PARRILLA", "PIZZERIA", "KIOSCO", "ALMACEN",
          "PANADERIA", "FARMACIA", "HOTEL", "CERVECERIA", "HELADERIA", "BODEGON"}
CALLE_RUIDO = {"AV", "AVDA", "AVENIDA", "CALLE", "BV", "BOULEVARD", "PJE", "PASAJE", "DR", "DOCTOR",
               "GRAL", "GENERAL", "TTE", "TENIENTE", "CNEL", "CORONEL", "PTE", "PRESIDENTE",
               "ING", "INGENIERO", "SGTO", "CAP", "CAPITAN", "ALTE", "ALMIRANTE"} | ARTICULOS
CABA = {"CABA", "CIUDAD AUTONOMA BUENOS AIRES", "CIUDAD AUTONOMA DE BUENOS AIRES", "CAPITAL FEDERAL",
        "CIUDAD DE BUENOS AIRES"}


def norm(valor):
    """Mayusculas, sin acentos ni signos, espacios simples."""
    texto = unicodedata.normalize("NFKD", str(valor or "").upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", texto).strip()


def solo_digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


def cuit_valido(valor):
    d = solo_digitos(valor)
    if len(d) != 11:
        return False
    pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    resto = (11 - sum(int(x) * p for x, p in zip(d, pesos)) % 11) % 11
    return resto == int(d[10])


def tokens_nombre(valor, quitar_rubro=False):
    """Palabras significativas de un nombre; conserva algo aunque todo sea ruido."""
    palabras = norm(valor).split()
    ruido = SOCIETARIAS | ARTICULOS | (RUBROS if quitar_rubro else set())
    utiles = [p for p in palabras if p not in ruido and len(p) > 1]
    return utiles or [p for p in palabras if len(p) > 1]


def tokens_calle(valor):
    return {p for p in norm(valor).split() if p not in CALLE_RUIDO and not p.isdigit() or
            (p.isdigit() and len(p) <= 2)}  # "9 DE JULIO", "25 DE MAYO"


def partir_direccion(valor):
    """'Av. Costa Rica 5709 PB' -> ('COSTA RICA', '5709'). Sin altura devuelve numero ''."""
    texto = norm(valor)
    m = re.search(r"^(.*?[A-Z].*?)\s+(\d{1,6})(?:\s|$)", texto)
    if not m:
        return texto, ""
    return m.group(1).strip(), str(int(m.group(2)))


def misma_calle(a, b):
    """Coincide si las palabras propias de una calle estan contenidas en la otra."""
    ta, tb = tokens_calle(a), tokens_calle(b)
    return bool(ta and tb and (ta <= tb or tb <= ta))


def provincia_canonica(valor):
    texto = norm(valor)
    return "CABA" if texto in CABA else texto


def misma_provincia(a, b):
    """None si falta alguno de los dos datos (no se penaliza lo desconocido)."""
    pa, pb = provincia_canonica(a), provincia_canonica(b)
    if not pa or not pb:
        return None
    return pa == pb
