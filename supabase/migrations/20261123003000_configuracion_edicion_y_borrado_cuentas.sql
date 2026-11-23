CREATE TABLE IF NOT EXISTS public.configuracion_edicion (
  id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  dias_inventario smallint NOT NULL DEFAULT 2 CHECK (dias_inventario BETWEEN 0 AND 365),
  dias_produccion smallint NOT NULL DEFAULT 1 CHECK (dias_produccion BETWEEN 0 AND 365),
  actualizado_por uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  actualizado_en timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.configuracion_edicion (id,dias_inventario,dias_produccion) VALUES (1,2,1) ON CONFLICT (id) DO NOTHING;
ALTER TABLE public.configuracion_edicion ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.configuracion_edicion FROM anon, authenticated;
GRANT ALL ON public.configuracion_edicion TO service_role;

ALTER TABLE public.perfiles DROP CONSTRAINT IF EXISTS perfiles_id_fkey;
ALTER TABLE public.perfiles ADD CONSTRAINT perfiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE public.accesos_panaderias DROP CONSTRAINT IF EXISTS accesos_panaderias_usuario_id_fkey;
ALTER TABLE public.accesos_panaderias ADD CONSTRAINT accesos_panaderias_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.perfiles(id) ON DELETE CASCADE;
ALTER TABLE public.configuracion_archivado DROP CONSTRAINT IF EXISTS configuracion_archivado_actualizado_por_fkey;
ALTER TABLE public.configuracion_archivado ADD CONSTRAINT configuracion_archivado_actualizado_por_fkey FOREIGN KEY (actualizado_por) REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE public.auditoria_inventario DROP CONSTRAINT IF EXISTS auditoria_inventario_usuario_id_fkey;
ALTER TABLE public.auditoria_inventario ADD CONSTRAINT auditoria_inventario_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE public.cierres_diarios DROP CONSTRAINT IF EXISTS cierres_diarios_cerrado_por_fkey;
ALTER TABLE public.cierres_diarios ADD CONSTRAINT cierres_diarios_cerrado_por_fkey FOREIGN KEY (cerrado_por) REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE public.cierres_diarios DROP CONSTRAINT IF EXISTS cierres_diarios_reabierto_por_fkey;
ALTER TABLE public.cierres_diarios ADD CONSTRAINT cierres_diarios_reabierto_por_fkey FOREIGN KEY (reabierto_por) REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE public.produccion_registros ADD COLUMN IF NOT EXISTS usuario_nombre text;
UPDATE public.produccion_registros pr SET usuario_nombre=p.nombre FROM public.perfiles p WHERE pr.usuario_id=p.id AND pr.usuario_nombre IS NULL;
ALTER TABLE public.produccion_registros ALTER COLUMN usuario_id DROP NOT NULL;
ALTER TABLE public.produccion_registros DROP CONSTRAINT IF EXISTS produccion_registros_usuario_id_fkey;
ALTER TABLE public.produccion_registros ADD CONSTRAINT produccion_registros_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES auth.users(id) ON DELETE SET NULL;
