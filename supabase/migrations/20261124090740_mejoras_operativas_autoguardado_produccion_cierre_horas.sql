alter table public.produccion_registros
  add column if not exists precio_unitario numeric(12,2),
  add column if not exists importe numeric(14,2);
do $$
begin
  if not exists (select 1 from pg_constraint where conname='produccion_registros_precio_unitario_check') then
    alter table public.produccion_registros add constraint produccion_registros_precio_unitario_check check (precio_unitario is null or precio_unitario >= 0);
  end if;
  if not exists (select 1 from pg_constraint where conname='produccion_registros_importe_check') then
    alter table public.produccion_registros add constraint produccion_registros_importe_check check (importe is null or importe >= 0);
  end if;
end $$;

alter table public.configuracion_edicion
  add column if not exists horas_inventario smallint not null default 0,
  add column if not exists dias_ventas smallint not null default 0,
  add column if not exists horas_ventas smallint not null default 0,
  add column if not exists horas_produccion smallint not null default 0;
do $$
begin
  if not exists (select 1 from pg_constraint where conname='configuracion_edicion_horas_inventario_check') then
    alter table public.configuracion_edicion add constraint configuracion_edicion_horas_inventario_check check (horas_inventario between 0 and 23);
  end if;
  if not exists (select 1 from pg_constraint where conname='configuracion_edicion_dias_ventas_check') then
    alter table public.configuracion_edicion add constraint configuracion_edicion_dias_ventas_check check (dias_ventas between 0 and 365);
  end if;
  if not exists (select 1 from pg_constraint where conname='configuracion_edicion_horas_ventas_check') then
    alter table public.configuracion_edicion add constraint configuracion_edicion_horas_ventas_check check (horas_ventas between 0 and 23);
  end if;
  if not exists (select 1 from pg_constraint where conname='configuracion_edicion_horas_produccion_check') then
    alter table public.configuracion_edicion add constraint configuracion_edicion_horas_produccion_check check (horas_produccion between 0 and 23);
  end if;
end $$;

create unique index if not exists inventario_detalles_cierre_producto_uidx on public.inventario_detalles(cierre_id, producto_id);

create or replace function public.guardar_linea_inventario(p_panaderia_id bigint,p_fecha date,p_producto_id bigint,p_cantidad integer,p_usuario_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_cierre public.cierres_diarios%rowtype;
  v_producto public.productos%rowtype;
  v_linea public.inventario_detalles%rowtype;
  v_nombre text;
begin
  if p_cantidad < 0 then raise exception 'La cantidad no puede ser negativa'; end if;
  select * into v_producto from public.productos where id=p_producto_id and panaderia_id=p_panaderia_id and activo is true;
  if not found then raise exception 'El producto no existe o está inactivo en este local'; end if;
  insert into public.cierres_diarios(panaderia_id,fecha,estado) values(p_panaderia_id,p_fecha,'abierto')
    on conflict(panaderia_id,fecha) do nothing;
  select * into v_cierre from public.cierres_diarios where panaderia_id=p_panaderia_id and fecha=p_fecha for update;
  if v_cierre.estado <> 'abierto' then raise exception 'El día está cerrado; debe reabrirse antes de editar'; end if;
  select nombre into v_nombre from public.perfiles where id=p_usuario_id;
  insert into public.inventario_detalles(cierre_id,producto_id,cantidad,precio_unitario,producto_nombre)
    values(v_cierre.id,p_producto_id,p_cantidad,v_producto.precio,v_producto.nombre)
    on conflict(cierre_id,producto_id) do update set cantidad=excluded.cantidad
    returning * into v_linea;
  insert into public.auditoria_inventario(cierre_id,panaderia_id,usuario_id,accion,detalles)
    values(v_cierre.id,p_panaderia_id,p_usuario_id,'guardar_linea_registro',
      jsonb_build_object('producto_id',p_producto_id,'cantidad',p_cantidad,'usuario_nombre',coalesce(v_nombre,'Usuario')));
  return jsonb_build_object('id',v_linea.id,'producto_id',v_linea.producto_id,'cantidad',v_linea.cantidad,
    'precio_unitario',v_linea.precio_unitario,'producto_nombre',v_linea.producto_nombre,'cierre_id',v_cierre.id);
end; $$;

create or replace function public.eliminar_linea_inventario(p_panaderia_id bigint,p_fecha date,p_producto_id bigint,p_usuario_id uuid)
returns boolean language plpgsql security definer set search_path = '' as $$
declare
  v_cierre public.cierres_diarios%rowtype;
  v_cantidad integer;
begin
  select * into v_cierre from public.cierres_diarios where panaderia_id=p_panaderia_id and fecha=p_fecha for update;
  if not found then return false; end if;
  if v_cierre.estado <> 'abierto' then raise exception 'El día está cerrado; debe reabrirse antes de editar'; end if;
  delete from public.inventario_detalles where cierre_id=v_cierre.id and producto_id=p_producto_id returning cantidad into v_cantidad;
  if not found then return false; end if;
  insert into public.auditoria_inventario(cierre_id,panaderia_id,usuario_id,accion,detalles)
    values(v_cierre.id,p_panaderia_id,p_usuario_id,'eliminar_linea_registro',
      jsonb_build_object('producto_id',p_producto_id,'cantidad_anterior',v_cantidad));
  return true;
end; $$;

create or replace function public.cerrar_dias_automaticamente()
returns integer language plpgsql security definer set search_path = '' as $$
declare
  v_fecha date := (now() at time zone 'America/Mexico_City')::date;
  v_cierre record;
  v_total integer := 0;
begin
  for v_cierre in
    select id,panaderia_id,fecha from public.cierres_diarios
    where estado='abierto' and fecha < v_fecha order by fecha,panaderia_id for update
  loop
    update public.cierres_diarios set estado='cerrado',cerrado_en=now(),cerrado_por=null,
      cerrado_por_nombre='Cierre automático',actualizado_en=now()
      where id=v_cierre.id and estado='abierto';
    if found then
      insert into public.auditoria_inventario(cierre_id,panaderia_id,usuario_id,accion,detalles)
        values(v_cierre.id,v_cierre.panaderia_id,null,'cierre_automatico',
          jsonb_build_object('fecha',v_cierre.fecha,'zona_horaria','America/Mexico_City'));
      v_total := v_total + 1;
    end if;
  end loop;
  return v_total;
end; $$;

do $$
declare v_job bigint;
begin
  select jobid into v_job from cron.job where jobname='cerrar-dias-panaderia-medianoche';
  if v_job is not null then perform cron.unschedule(v_job); end if;
  perform cron.schedule('cerrar-dias-panaderia-medianoche','0 6 * * *','select public.cerrar_dias_automaticamente();');
end $$;
