"""Validación y formato de CUIT/CUIL (dígito verificador módulo 11)."""
from __future__ import annotations

import re

_PESOS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
# Prefijos habituales: 20/23/24/27 personas físicas, 30/33/34 jurídicas.
PREFIJOS_JURIDICOS = {"30", "33", "34"}


def limpiar(valor) -> str:
    """Deja solo los dígitos de un CUIT escrito con guiones, puntos o espacios."""
    return re.sub(r"\D", "", str(valor or ""))


def digito_verificador(diez_digitos: str) -> int | None:
    """Calcula el dígito verificador de los primeros 10 dígitos.

    Devuelve None cuando el resto da 10: esa combinación no existe (ARCA
    asigna otro prefijo, por ejemplo 23 en lugar de 20).
    """
    if len(diez_digitos) != 10 or not diez_digitos.isdigit():
        raise ValueError("se esperan exactamente 10 dígitos")
    suma = sum(int(d) * p for d, p in zip(diez_digitos, _PESOS))
    resto = 11 - (suma % 11)
    if resto == 11:
        return 0
    if resto == 10:
        return None
    return resto


def es_valido(valor) -> bool:
    """True si el CUIT tiene 11 dígitos y su dígito verificador es correcto."""
    cuit = limpiar(valor)
    if len(cuit) != 11:
        return False
    dv = digito_verificador(cuit[:10])
    return dv is not None and dv == int(cuit[10])


def formatear(valor) -> str:
    """30715644130 -> 30-71564413-0. Si no tiene 11 dígitos lo devuelve limpio."""
    cuit = limpiar(valor)
    if len(cuit) != 11:
        return cuit
    return f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"


def es_juridica(valor) -> bool:
    return limpiar(valor)[:2] in PREFIJOS_JURIDICOS
