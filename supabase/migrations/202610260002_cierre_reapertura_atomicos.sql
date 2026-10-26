-- Cierre y reapertura atómicos: estado y auditoría en una sola transacción.
create or replace function public.cerrar_cierre_diario(
  p_cierre_id bigint,
  p_usuario_id uuid,
  p_fecha timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_cierre public.cierres_diarios%rowtype;
begin
  select * into v_cierre
  from public.cierres_diarios
  where id = p_cierre_id
  for update;

  if not found then
    raise exception 'No existe el cierre indicado';
  end if;

  if v_cierre.estado = 'cerrado' then
    return jsonb_build_object('id', v_cierre.id, 'estado', v_cierre.estado, 'cerrado_en', v_cierre.cerrado_en);
  end if;

  if not exists (
    select 1 from public.inventario_detalles d where d.cierre_id = p_cierre_id
  ) then
    raise exception 'No se puede cerrar un día sin productos registrados';
  end if;

  update public.cierres_diarios
  set estado = 'cerrado',
      cerrado_en = p_fecha,
      cerrado_por = p_usuario_id,
      actualizado_en = now()
  where id = p_cierre_id
  returning * into v_cierre;

  insert into public.auditoria_inventario
    (cierre_id, panaderia_id, usuario_id, accion, detalles)
  values
    (v_cierre.id, v_cierre.panaderia_id, p_usuario_id, 'cerrar_dia',
     jsonb_build_object('estado_anterior', 'abierto', 'estado_nuevo', 'cerrado'));

  return jsonb_build_object('id', v_cierre.id, 'estado', v_cierre.estado, 'cerrado_en', v_cierre.cerrado_en);
end;
$$;

create or replace function public.reabrir_cierre_diario(
  p_cierre_id bigint,
  p_usuario_id uuid,
  p_motivo text,
  p_dentro_de_48h boolean,
  p_fecha timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_cierre public.cierres_diarios%rowtype;
begin
  select * into v_cierre
  from public.cierres_diarios
  where id = p_cierre_id
  for update;

  if not found then
    raise exception 'No existe el cierre indicado';
  end if;

  if v_cierre.estado = 'abierto' then
    return jsonb_build_object('id', v_cierre.id, 'estado', v_cierre.estado, 'reabierto_en', v_cierre.reabierto_en);
  end if;

  if not p_dentro_de_48h and length(btrim(coalesce(p_motivo, ''))) < 5 then
    raise exception 'La corrección administrativa requiere un motivo de al menos cinco caracteres';
  end if;

  update public.cierres_diarios
  set estado = 'abierto',
      reabierto_en = p_fecha,
      reabierto_por = p_usuario_id,
      motivo_correccion = case when p_dentro_de_48h then null else btrim(p_motivo) end,
      actualizado_en = now()
  where id = p_cierre_id
  returning * into v_cierre;

  insert into public.auditoria_inventario
    (cierre_id, panaderia_id, usuario_id, accion, motivo, detalles)
  values
    (v_cierre.id, v_cierre.panaderia_id, p_usuario_id,
     case when p_dentro_de_48h then 'reabrir_dentro_48h' else 'correccion_administrativa' end,
     case when p_dentro_de_48h then null else btrim(p_motivo) end,
     jsonb_build_object('estado_anterior', 'cerrado', 'estado_nuevo', 'abierto'));

  return jsonb_build_object('id', v_cierre.id, 'estado', v_cierre.estado, 'reabierto_en', v_cierre.reabierto_en);
end;
$$;

revoke all on function public.cerrar_cierre_diario(bigint, uuid, timestamptz) from public, anon, authenticated;
revoke all on function public.reabrir_cierre_diario(bigint, uuid, text, boolean, timestamptz) from public, anon, authenticated;
grant execute on function public.cerrar_cierre_diario(bigint, uuid, date) to service_role;
grant execute on function public.reabrir_cierre_diario(bigint, uuid, text, boolean, timestamptz) to service_role;
