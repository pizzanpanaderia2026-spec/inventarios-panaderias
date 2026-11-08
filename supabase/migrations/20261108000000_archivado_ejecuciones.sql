-- Estado persistente del respaldo para que la interfaz muestre progreso real
-- incluso si la administradora sale de la sección o recarga la aplicación.
create table if not exists public.archivado_ejecuciones (
  id uuid primary key default gen_random_uuid(),
  estado text not null check (estado in ('preparando','subiendo','verificando','completado','error')),
  periodo_inicio date not null,
  periodo_fin date not null,
  fechas_total integer not null default 0,
  fechas_completadas integer not null default 0,
  etapa text,
  detalle jsonb not null default '[]'::jsonb,
  error text,
  iniciado_en timestamptz not null default now(),
  actualizado_en timestamptz not null default now(),
  terminado_en timestamptz
);

create index if not exists archivado_ejecuciones_actualizado_idx
  on public.archivado_ejecuciones (actualizado_en desc);

create unique index if not exists archivado_una_ejecucion_activa_idx
  on public.archivado_ejecuciones ((1))
  where estado in ('preparando','subiendo','verificando');

alter table public.archivado_ejecuciones enable row level security;
