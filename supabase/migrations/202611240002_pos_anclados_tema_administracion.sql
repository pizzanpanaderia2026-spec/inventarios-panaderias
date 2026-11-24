-- Preferencias visuales suaves y productos anclados de forma persistente en el POS.
ALTER TABLE public.configuracion_colores
  ADD COLUMN IF NOT EXISTS administracion text NOT NULL DEFAULT '#D8CBE8';

ALTER TABLE public.productos
  ADD COLUMN IF NOT EXISTS pos_anclado boolean NOT NULL DEFAULT false;
