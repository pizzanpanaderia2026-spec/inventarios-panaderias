"""Cálculo de periodos mensuales de archivado, incluidos meses cortos."""
from calendar import monthrange
from datetime import date, timedelta


def fecha_del_dia(year: int, month: int, day: int) -> date:
    """Devuelve el día solicitado o el último día del mes si no existe."""
    ultimo = monthrange(year, month)[1]
    return date(year, month, min(max(1, day), ultimo))


def siguiente_ocurrencia(referencia: date, dia: int, inclusiva: bool = False) -> date:
    """Primera ocurrencia del día mensual en o después de la referencia."""
    year, month = referencia.year, referencia.month
    for _ in range(14):
        candidata = fecha_del_dia(year, month, dia)
        if candidata >= referencia if inclusiva else candidata > referencia:
            return candidata
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    raise ValueError("No se pudo calcular la siguiente fecha mensual.")


def periodo_inicial(hoy: date, dia_inicio: int) -> tuple[date, date]:
    """Periodo activo inicial: día elegido hasta el día anterior al siguiente."""
    inicio_mes = fecha_del_dia(hoy.year, hoy.month, dia_inicio)
    if inicio_mes <= hoy:
        inicio = inicio_mes
    else:
        year, month = hoy.year, hoy.month - 1
        if month == 0:
            year, month = year - 1, 12
        inicio = fecha_del_dia(year, month, dia_inicio)
    limite = siguiente_ocurrencia(inicio, dia_inicio)
    return inicio, limite - timedelta(days=1)


def cambiar_fin_periodo(
    inicio_actual: date,
    fin_actual: date,
    hoy: date,
    nuevo_dia: int,
) -> tuple[date, int]:
    """Ajusta el fin del periodo activo según el cambio confirmado por el usuario.

    Si el periodo aún no terminó, se extiende/acorta hasta la próxima fecha
    seleccionada, inclusive. Si ya terminó, no se modifica retroactivamente.
    El desplazamiento 0 indica que los periodos futuros terminan en el día
    seleccionado; -1 conserva el comportamiento inicial (día seleccionado
    como inicio del ciclo).
    """
    if fin_actual < hoy:
        return fin_actual, 0
    nuevo_fin = siguiente_ocurrencia(hoy, nuevo_dia, inclusiva=True)
    if nuevo_fin < inicio_actual:
        raise ValueError("El nuevo periodo no puede terminar antes de comenzar.")
    return nuevo_fin, 0


def siguiente_periodo(
    fin_actual: date,
    dia: int,
    desplazamiento_fin: int,
) -> tuple[date, date]:
    """Calcula el periodo posterior sin huecos ni días duplicados."""
    inicio = fin_actual + timedelta(days=1)
    limite = siguiente_ocurrencia(inicio, dia)
    fin = limite + timedelta(days=desplazamiento_fin)
    if fin < inicio:
        raise ValueError("El siguiente periodo tiene un rango inválido.")
    return inicio, fin
