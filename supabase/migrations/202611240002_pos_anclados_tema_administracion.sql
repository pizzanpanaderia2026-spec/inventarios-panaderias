-- Preferencias visuales suaves y productos anclados de forma persistente en el POS.
ALTER TABLE public.configuracion_colores
  ADD COLUMN IF NOT EXISTS administracion text NOT NULL DEFAULT '#D8CBE8';

-- Actualiza únicamente los tonos originales de fábrica; conserva cualquier personalización previa.
UPDATE public.configuracion_colores
SET ventas = '#B9D7EA',
    produccion = '#B9DCC6',
    inventarios = '#F2C99B',
    administracion = COALESCE(NULLIF(administracion, ''), '#D8CBE8')
WHERE id = 1
  AND ventas = '#2563EB'
  AND produccion = '#16A34A'
  AND inventarios = '#D97706';

ALTER TABLE public.productos
  ADD COLUMN IF NOT EXISTS pos_anclado boolean NOT NULL DEFAULT false;
