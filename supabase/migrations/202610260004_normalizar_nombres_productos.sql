-- Evita duplicados por panadería aunque cambien mayúsculas, acentos o espacios.
-- Conserva el nombre original para mostrarlo; esta función solo crea una clave de comparación.
create or replace function public.clave_nombre_producto(p_nombre text)
returns text
language sql
immutable
strict
parallel safe
set search_path = pg_catalog
as $$
    select translate(
        lower(regexp_replace(btrim(p_nombre), '[[:space:]]+', ' ', 'g')),
        'áéíóúüñ',
        'aeiouun'
    );
$$;

revoke all on function public.clave_nombre_producto(text) from public;
grant execute on function public.clave_nombre_producto(text) to authenticated, service_role;

drop index if exists public.productos_panaderia_nombre_unico;

create unique index productos_panaderia_nombre_unico
on public.productos (
    panaderia_id,
    public.clave_nombre_producto(nombre)
);
