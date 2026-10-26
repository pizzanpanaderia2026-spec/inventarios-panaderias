-- Refuerza la integridad de las líneas y calcula la ventana de reapertura en PostgreSQL.
-- No cambia las tablas de interfaz ni borra datos históricos.

create or replace function public.reemplazar_lineas_cierre(
  p_cierre_id bigint,
  p_lineas jsonb,
  p_usuario_id uuid
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_panaderia_id bigint;
  v_estado text;
begin
  if jsonb_typeof(p_lineas) <> 'array' then
    raise exception 'Las líneas deben enviarse como una lista';
  end if;

  select c.panaderia_id, c.estado into v_panaderia_id, v_estado
  from public.cierres_diarios c
  where c.id = p_cierre_id
  for update;

  if v_panaderia_id is null then
    raise exception 'No existe el cierre indicado';
  end if;

  if v_estado <> 'abierto' then
    raise exception 'El cierre está cerrado; debe reabrirse antes de editar';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_lineas) as lines(value)
    left join public.productos p on p.id = (lines.value->>'producto_id')::bigint
    where p.id is null
       or p.panaderia_id <> v_panaderia_id
       or p.activo is not true
       or (lines.value->>'cantidad')::integer < 0
       or (lines.value->>'precio_unitario')::numeric(12,2) < 0
       or nullif(btrim(lines.value->>'producto_nombre'), '') is null
  ) then
    raise exception 'Una línea contiene un producto inactivo o un valor no válido';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_lineas) as lines(value)
    group by (lines.value->>'producto_id')::bigint
    having count(*) > 1
  ) then
    raise exception 'No se puede repetir un producto en el mismo registro';
  end if;

  delete from public.inventario_detalles
  where cierre_id = p_cierre_id;

  insert into public.inventario_detalles
    (cierre_id, producto_id, cantidad, precio_unitario, producto_nombre)
  select
    p_cierre_id,
    (lines.value->>'producto_id')::bigint,
    (lines.value->>'cantidad')::integer,
    (lines.value->>'precio_unitario')::numeric(12,2),
    btrim(lines.value->>'producto_nombre')
  from jsonb_array_elements(p_lineas) as lines(value);

  insert into public.auditoria_inventario
    (cierre_id, panaderia_id, usuario_id, accion, detalles)
  values (
    p_cierre_id,
    v_panaderia_id,
    p_usuario_id,
    'guardar_registro',
    jsonb_build_object('cantidad_lineas', jsonb_array_length(p_lineas))
  );
end;
$$;

revoke all on function public.reemplazar_lineas_cierre(bigint, jsonb, uuid) from public, anon, authenticated;
grant execute on function public.reemplazar_lineas_cierre(bigint, jsonb, uuid) to service_role;

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
  v_dentro_de_48h boolean;
  v_motivo text;
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

  if v_cierre.cerrado_en is null then
    raise exception 'El cierre no tiene una fecha de cierre válida';
  end if;

  -- La ventana se calcula en la base de datos, nunca se confía en el booleano del cliente.
  v_dentro_de_48h := (now() - v_cierre.cerrado_en) < interval '48 hours';
  v_motivo := btrim(coalesce(p_motivo, ''));

  if not v_dentro_de_48h and length(v_motivo) < 5 then
    raise exception 'La corrección administrativa requiere un motivo de al menos cinco caracteres';
  end if;

  update public.cierres_diarios
  set estado = 'abierto',
      reabierto_en = now(),
      reabierto_por = p_usuario_id,
      motivo_correccion = case when v_dentro_de_48h then null else v_motivo end,
      actualizado_en = now()
  where id = p_cierre_id
  returning * into v_cierre;

  insert into public.auditoria_inventario
    (cierre_id, panaderia_id, usuario_id, accion, motivo, detalles)
  values
    (v_cierre.id, v_cierre.panaderia_id, p_usuario_id,
     case when v_dentro_de_48h then 'reabrir_dentro_48h' else 'correccion_administrativa' end,
     case when v_dentro_de_48h then null else v_motivo end,
     jsonb_build_object('estado_anterior', 'cerrado', 'estado_nuevo', 'abierto'));

  return jsonb_build_object('id', v_cierre.id, 'estado', v_cierre.estado, 'reabierto_en', v_cierre.reabierto_en);
end;
$$;

revoke all on function public.reabrir_cierre_diario(bigint, uuid, text, boolean, timestamptz) from public, anon, authenticated;
grant execute on function public.reabrir_cierre_diario(bigint, uuid, text, boolean, timestamptz) to service_role;
