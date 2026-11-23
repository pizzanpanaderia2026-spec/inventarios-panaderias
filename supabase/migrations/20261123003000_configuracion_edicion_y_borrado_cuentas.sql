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


-- La ventana de inventario se calcula por días naturales en la zona horaria
-- de México. El booleano solo lo envía el backend service_role después de
-- validar el plazo configurable y los permisos de la cuenta.
CREATE OR REPLACE FUNCTION public.reabrir_cierre_diario(
  p_cierre_id bigint,
  p_usuario_id uuid,
  p_motivo text,
  p_dentro_de_48h boolean,
  p_fecha timestamptz
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_cierre public.cierres_diarios%rowtype;
  v_dentro_de_48h boolean;
  v_motivo text;
BEGIN
  SELECT * INTO v_cierre
  FROM public.cierres_diarios
  WHERE id = p_cierre_id
  FOR UPDATE;

  IF NOT FOUND THEN RAISE EXCEPTION 'No existe el cierre indicado'; END IF;
  IF v_cierre.estado = 'abierto' THEN
    RETURN jsonb_build_object('id', v_cierre.id, 'estado', v_cierre.estado, 'reabierto_en', v_cierre.reabierto_en);
  END IF;
  IF v_cierre.cerrado_en IS NULL THEN RAISE EXCEPTION 'El cierre no tiene una fecha de cierre válida'; END IF;

  v_dentro_de_48h := COALESCE(p_dentro_de_48h, false);
  v_motivo := btrim(coalesce(p_motivo, ''));
  IF NOT v_dentro_de_48h AND length(v_motivo) < 5 THEN
    RAISE EXCEPTION 'La corrección administrativa requiere un motivo de al menos cinco caracteres';
  END IF;

  UPDATE public.cierres_diarios
  SET estado = 'abierto',
      reabierto_en = now(),
      reabierto_por = p_usuario_id,
      motivo_correccion = CASE WHEN v_dentro_de_48h THEN NULL ELSE v_motivo END,
      actualizado_en = now()
  WHERE id = p_cierre_id
  RETURNING * INTO v_cierre;

  INSERT INTO public.auditoria_inventario
    (cierre_id, panaderia_id, usuario_id, accion, motivo, detalles)
  VALUES
    (v_cierre.id, v_cierre.panaderia_id, p_usuario_id,
     CASE WHEN v_dentro_de_48h THEN 'reabrir_dentro_plazo' ELSE 'correccion_administrativa' END,
     CASE WHEN v_dentro_de_48h THEN NULL ELSE v_motivo END,
     jsonb_build_object('estado_anterior', 'cerrado', 'estado_nuevo', 'abierto'));

  RETURN jsonb_build_object('id', v_cierre.id, 'estado', v_cierre.estado, 'reabierto_en', v_cierre.reabierto_en);
END;
$$;

REVOKE ALL ON FUNCTION public.reabrir_cierre_diario(bigint, uuid, text, boolean, timestamptz) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reabrir_cierre_diario(bigint, uuid, text, boolean, timestamptz) TO service_role;
