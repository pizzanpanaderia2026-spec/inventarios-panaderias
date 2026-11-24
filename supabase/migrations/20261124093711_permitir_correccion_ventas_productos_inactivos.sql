
create or replace function public.actualizar_venta_pos(p_venta_id bigint,p_usuario_id uuid,p_lineas jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_venta public.ventas_pos%rowtype;
  v_line jsonb;
  v_producto public.productos%rowtype;
  v_anteriores jsonb;
  v_nuevas jsonb;
  v_precio numeric(12,2);
  v_nombre text;
  v_cantidad integer;
  v_total numeric(14,2) := 0;
  v_cantidad_lineas integer := 0;
begin
  if jsonb_typeof(p_lineas) <> 'array' or jsonb_array_length(p_lineas)=0 then
    raise exception 'La venta debe conservar al menos un producto';
  end if;
  select * into v_venta from public.ventas_pos where id=p_venta_id for update;
  if not found then raise exception 'No existe la venta indicada'; end if;
  select coalesce(jsonb_agg(jsonb_build_object(
    'producto_id',producto_id,'producto_nombre',producto_nombre,'cantidad',cantidad,
    'precio_unitario',precio_unitario,'importe',importe)), '[]'::jsonb)
    into v_anteriores from public.ventas_pos_detalles where venta_id=p_venta_id;
  if exists(select 1 from jsonb_array_elements(p_lineas) as lines(value)
    group by (lines.value->>'producto_id')::bigint having count(*)>1) then
    raise exception 'No repitas productos en una misma venta';
  end if;
  delete from public.ventas_pos_detalles where venta_id=p_venta_id;
  for v_line in select value from jsonb_array_elements(p_lineas) as incoming(value)
  loop
    v_cantidad := (v_line->>'cantidad')::integer;
    if v_cantidad < 1 then raise exception 'Las cantidades deben ser mayores a cero'; end if;
    select * into v_producto from public.productos
      where id=(v_line->>'producto_id')::bigint
        and panaderia_id=v_venta.panaderia_id;
    if not found then raise exception 'Uno de los productos no pertenece a este local o está inactivo'; end if;
    v_precio := null; v_nombre := null;
    select (old_line.value->>'precio_unitario')::numeric,old_line.value->>'producto_nombre'
      into v_precio,v_nombre from jsonb_array_elements(v_anteriores) as old_line(value)
      where (old_line.value->>'producto_id')::bigint=v_producto.id limit 1;
    if v_precio is null then v_precio := v_producto.precio; end if;
    if v_nombre is null then v_nombre := v_producto.nombre; end if;
    insert into public.ventas_pos_detalles(venta_id,producto_id,producto_nombre,cantidad,precio_unitario,importe)
      values(p_venta_id,v_producto.id,v_nombre,v_cantidad,v_precio,v_precio*v_cantidad);
    v_total := v_total + v_precio*v_cantidad;
    v_cantidad_lineas := v_cantidad_lineas + 1;
  end loop;
  select coalesce(jsonb_agg(jsonb_build_object(
    'producto_id',producto_id,'producto_nombre',producto_nombre,'cantidad',cantidad,
    'precio_unitario',precio_unitario,'importe',importe)), '[]'::jsonb)
    into v_nuevas from public.ventas_pos_detalles where venta_id=p_venta_id;
  update public.ventas_pos set total=v_total where id=p_venta_id;
  insert into public.auditoria_ventas(venta_id,panaderia_id,usuario_id,accion,detalles)
    values(p_venta_id,v_venta.panaderia_id,p_usuario_id,'editar_venta',
      jsonb_build_object('total_anterior',v_venta.total,'total_nuevo',v_total,
        'lineas_anteriores',v_anteriores,'lineas_nuevas',v_nuevas));
  return jsonb_build_object('id',p_venta_id,'total',v_total,'lineas',v_cantidad_lineas);
end; $$;
revoke all on function public.actualizar_venta_pos(bigint,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.actualizar_venta_pos(bigint,uuid,jsonb) to service_role;
