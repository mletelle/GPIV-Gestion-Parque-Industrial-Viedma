"""
constantes del viewBox y funcion para construir los datos del mapa
desde el modelo Lote (campos mapa_x, mapa_y, mapa_w, mapa_h).

las posiciones se cargan en la bd via cargar_datos_prueba y se editan
desde el editor visual en /lotes/editor/.
"""

VIEWBOX_W = 1400
VIEWBOX_H = 700

SERVIDUMBRE_Y = 355


def build_mapa_data(lotes_qs):
    """construye la lista de datos para renderizar el mapa svg.
    lee las posiciones directamente del modelo."""
    items = []
    for lote in lotes_qs:
        if lote.mapa_x is None:
            continue
        items.append({
            'nro': lote.nro_parcela,
            'x': lote.mapa_x,
            'y': lote.mapa_y,
            'w': lote.mapa_w,
            'h': lote.mapa_h,
            'cx': lote.mapa_x + lote.mapa_w // 2,
            'cy': lote.mapa_y + lote.mapa_h // 2,
            'estado': lote.estado,
            'estado_label': lote.get_estado_display(),
            'superficie': float(lote.superficie_m2),
        })
    return items
