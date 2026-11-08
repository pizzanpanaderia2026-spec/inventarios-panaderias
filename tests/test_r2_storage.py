import os
import unittest
from unittest.mock import patch

import r2_storage


class R2StorageTests(unittest.TestCase):
    def test_rechaza_configuracion_incompleta_sin_exponer_secretos(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(r2_storage.R2ConfigurationError) as ctx:
                r2_storage.crear_cliente_r2()
        self.assertIn("R2_ACCESS_KEY_ID", str(ctx.exception))
        self.assertNotIn("SECRET_ACCESS_KEY=", str(ctx.exception))

    def test_comprueba_subida_lectura_y_borrado(self):
        class ClienteFalso:
            def __init__(self):
                self.subidos = []
                self.borrados = []

            def put_object(self, **kwargs):
                self.subidos.append(kwargs)

            def head_object(self, **kwargs):
                return {"ContentLength": len(b"R2 connection check")}

            def delete_object(self, **kwargs):
                self.borrados.append(kwargs)

        cliente = ClienteFalso()
        variables = {
            "R2_ENDPOINT": "https://example.r2.cloudflarestorage.com",
            "R2_BUCKET_NAME": "respaldos-web",
            "R2_ACCESS_KEY_ID": "test-access",
            "R2_SECRET_ACCESS_KEY": "test-secret",
            "R2_REGION": "auto",
        }
        with patch.dict(os.environ, variables, clear=True), patch.object(
            r2_storage, "crear_cliente_r2", return_value=cliente
        ):
            resultado = r2_storage.comprobar_conexion_r2()

        self.assertTrue(resultado["conectado"])
        self.assertEqual(resultado["bucket"], "respaldos-web")
        self.assertEqual(len(cliente.subidos), 1)
        self.assertEqual(len(cliente.borrados), 1)
        self.assertEqual(cliente.subidos[0]["Body"], b"R2 connection check")


if __name__ == "__main__":
    unittest.main()
