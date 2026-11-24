
alter table public.inventario_detalles
  add column if not exists usuario_id uuid references auth.users(id) on delete set null,
  add column if not exists usuario_nombre text;

create or replace function public.guardar_linea_inventario(
  p_panaderia_id bigint,
  p_fecha date,
  p_producto_id bigint,
  p_cantidad integer,
  p_usuario_id uuid
) returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_cierre public.cierres_diarios%rowtype;
  v_producto public.productos%rowtype;
  v_linea public.inventario_detalles%rowtype;
  v_nombre text;
begin
  if p_cantidad < 0 then raise exception 'La cantidad no puede ser negativa'; end if;
  select * into v_producto from public.productos
    where id=p_producto_id and panaderia_id=p_panaderia_id and activo is true;
  if not found then raise exception 'El producto no existe o está inactivo en este local'; end if;
  insert into public.cierres_diarios(panaderia_id,fecha,estado)
    values(p_panaderia_id,p_fecha,'abierto')
    on conflict(panaderia_id,fecha) do nothing;
  select * into v_cierre from public.cierres_diarios
    where panaderia_id=p_panaderia_id and fecha=p_fecha for update;
  if v_cierre.estado <> 'abierto' then raise exception 'El día está cerrado; debe reabrirse antes de editar'; end if;
  select nombre into v_nombre from public.perfiles where id=p_usuario_id;
  insert into public.inventario_detalles(
    cierre_id,producto_id,cantidad,precio_unitario,producto_nombre,usuario_id,usuario_nombre
  ) values(
    v_cierre.id,p_producto_id,p_cantidad,v_producto.precio,v_producto.nombre,p_usuario_id,coalesce(v_nombre,'Usuario')
  )
  on conflict(cierre_id,producto_id) do update set
    cantidad=excluded.cantidad,
    usuario_id=coalesce(public.inventario_detalles.usuario_id,excluded.usuario_id),
    usuario_nombre=coalesce(public.inventario_detalles.usuario_nombre,excluded.usuario_nombre)
  returning * into v_linea;
  insert into public.auditoria_inventario(cierre_id,panaderia_id,usuario_id,accion,detalles)
    values(v_cierre.id,p_panaderia_id,p_usuario_id,'guardar_linea_registro',
      jsonb_build_object('producto_id',p_producto_id,'cantidad',p_cantidad,'usuario_nombre',coalesce(v_nombre,'Usuario')));
  return jsonb_build_object('id',v_linea.id,'producto_id',v_linea.producto_id,'cantidad',v_linea.cantidad,
    'precio_unitario',v_linea.precio_unitario,'producto_nombre',v_linea.producto_nombre,
    'usuario_id',v_linea.usuario_id,'usuario_nombre',v_linea.usuario_nombre,'cierre_id',v_cierre.id);
end;
$$;
revoke all on function public.guardar_linea_inventario(bigint,date,bigint,integer,uuid) from public,anon,authenticated;
grant execute on function public.guardar_linea_inventario(bigint,date,bigint,integer,uuid) to service_role;
