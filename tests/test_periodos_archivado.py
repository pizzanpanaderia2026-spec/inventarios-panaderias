import unittest
from datetime import date

from periodos_archivado import (
    cambiar_fin_periodo,
    periodo_inicial,
    siguiente_periodo,
)


class PeriodosArchivadoTests(unittest.TestCase):
    def test_periodo_inicial_dia_15(self):
        self.assertEqual(
            periodo_inicial(date(2026, 11, 4), 15),
            (date(2026, 10, 15), date(2026, 11, 14)),
        )

    def test_mes_corto_usa_ultimo_dia(self):
        self.assertEqual(
            periodo_inicial(date(2026, 2, 10), 31),
            (date(2026, 1, 31), date(2026, 2, 27)),
        )
        self.assertEqual(
            periodo_inicial(date(2028, 2, 10), 31),
            (date(2028, 1, 31), date(2028, 2, 28)),
        )

    def test_ciclos_seguidos_no_tienen_huecos_ni_duplicados(self):
        inicio, fin = periodo_inicial(date(2026, 11, 4), 15)
        siguiente_inicio, siguiente_fin = siguiente_periodo(fin, 15, -1)
        self.assertEqual((inicio, fin), (date(2026, 10, 15), date(2026, 11, 14)))
        self.assertEqual((siguiente_inicio, siguiente_fin), (date(2026, 11, 15), date(2026, 12, 14)))

    def test_cambio_a_dia_10_acorta_periodo_y_siguiente_empieza_11(self):
        nuevo_fin, offset = cambiar_fin_periodo(
            date(2026, 10, 15), date(2026, 11, 14), date(2026, 11, 4), 10
        )
        self.assertEqual(nuevo_fin, date(2026, 11, 10))
        inicio, fin = siguiente_periodo(nuevo_fin, 10, offset)
        self.assertEqual((inicio, fin), (date(2026, 11, 11), date(2026, 12, 10)))

    def test_cambio_a_dia_17_extiende_periodo_y_siguiente_empieza_18(self):
        nuevo_fin, offset = cambiar_fin_periodo(
            date(2026, 10, 15), date(2026, 11, 14), date(2026, 11, 4), 17
        )
        self.assertEqual(nuevo_fin, date(2026, 11, 17))
        inicio, fin = siguiente_periodo(nuevo_fin, 17, offset)
        self.assertEqual((inicio, fin), (date(2026, 11, 18), date(2026, 12, 17)))

    def test_no_cambia_periodo_que_ya_termino(self):
        nuevo_fin, offset = cambiar_fin_periodo(
            date(2026, 10, 15), date(2026, 11, 14), date(2026, 11, 20), 10
        )
        self.assertEqual(nuevo_fin, date(2026, 11, 14))
        inicio, fin = siguiente_periodo(nuevo_fin, 10, offset)
        self.assertEqual((inicio, fin), (date(2026, 11, 15), date(2026, 12, 10)))


if __name__ == "__main__":
    unittest.main()
