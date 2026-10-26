-- Índices de soporte para claves foráneas y consultas de historial.
-- No alteran registros existentes ni eliminan información.
create index if not exists accesos_panaderias_panaderia_id_idx
  on public.accesos_panaderias (panaderia_id);

create index if not exists auditoria_inventario_cierre_id_idx
  on public.auditoria_inventario (cierre_id);

create index if not exists auditoria_inventario_panaderia_id_idx
  on public.auditoria_inventario (panaderia_id);

create index if not exists auditoria_inventario_usuario_id_idx
  on public.auditoria_inventario (usuario_id);

create index if not exists cierres_diarios_cerrado_por_idx
  on public.cierres_diarios (cerrado_por);

create index if not exists cierres_diarios_reabierto_por_idx
  on public.cierres_diarios (reabierto_por);

create index if not exists inventario_detalles_cierre_id_idx
  on public.inventario_detalles (cierre_id);

create index if not exists inventario_detalles_producto_id_idx
  on public.inventario_detalles (producto_id);
