-- Categorías independientes por panadería y protección del historial.
create table if not exists public.categorias_productos (
  id bigint generated always as identity primary key,
  panaderia_id bigint not null references public.panaderias(id) on delete cascade,
  nombre text not null,
  activa boolean not null default true,
  protegida boolean not null default false,
  creada_en timestamptz not null default now(),
  actualizada_en timestamptz not null default now()
);
create unique index if not exists categorias_productos_nombre_unico
on public.categorias_productos (panaderia_id, lower(nombre));
alter table public.productos
  add column if not exists categoria_id bigint references public.categorias_productos(id) on delete set null,
  add column if not exists categoria_original_id bigint references public.categorias_productos(id) on delete set null;
create index if not exists productos_categoria_id_idx on public.productos(categoria_id);
create index if not exists productos_categoria_original_id_idx on public.productos(categoria_original_id);
alter table public.categorias_productos enable row level security;
revoke all on public.categorias_productos from anon, authenticated;
grant all on public.categorias_productos to service_role;
grant usage, select on sequence public.categorias_productos_id_seq to service_role;

-- Cada panadería obtiene su carpeta permanente para productos desactivados.
insert into public.categorias_productos (panaderia_id,nombre,activa,protegida)
select p.id,'Productos desactivados',true,true
from public.panaderias p
where not exists (
  select 1 from public.categorias_productos c
  where c.panaderia_id=p.id and c.protegida=true
);

-- Catálogo inicial exclusivo de Pizzan. Rebanadas se omite hasta confirmar su precio.
with pizzan as (
  select id from public.panaderias
  where lower(nombre) = lower('Pizzan')
  order by id limit 1
), iniciales(nombre) as (
  values
  ('Hojaldres'),('Conchas y pan dulce'),('Croissants y más'),('Apastelada'),
  ('Muffins y panqués'),('Bisquet'),('Donas'),('Pan tradicional')
)
insert into public.categorias_productos(panaderia_id,nombre)
select p.id,i.nombre from pizzan p cross join iniciales i
where not exists (
  select 1 from public.categorias_productos c
  where c.panaderia_id=p.id and lower(c.nombre)=lower(i.nombre)
);

with pizzan as (
  select id from public.panaderias
  where lower(nombre) = lower('Pizzan')
  order by id limit 1
), datos(categoria, nombre, precio) as (
  values
  ('Hojaldres','Empanada crema',8.00),('Hojaldres','Empanada piña',8.00),
  ('Hojaldres','Empanada Hawaiana',12.00),('Hojaldres','Cubilete',12.00),
  ('Hojaldres','Estrudel varios',8.00),('Hojaldres','Tacos cobertura',8.00),
  ('Hojaldres','Tornillo hojaldre',7.00),
  ('Conchas y pan dulce','Concha',8.00),('Conchas y pan dulce','Borrego',8.00),
  ('Conchas y pan dulce','Ojo de concha',8.00),('Conchas y pan dulce','Conchita',5.00),
  ('Conchas y pan dulce','Panecillo cuadrado',14.00),('Conchas y pan dulce','Panecillos redondo',10.00),
  ('Conchas y pan dulce','Cerillo',8.00),
  ('Croissants y más','Croissant',8.00),('Croissants y más','Bigote chocolate',8.00),
  ('Croissants y más','Tornillo',8.00),('Croissants y más','Bigote grande de chocolate',12.00),
  ('Croissants y más','Libro chico',5.00),('Croissants y más','Croissant chico',5.00),
  ('Croissants y más','Moño',5.00),('Croissants y más','Crossantin',10.00),
  ('Croissants y más','Roles diferentes',10.00),('Croissants y más','Croffin',8.00),
  ('Apastelada','Ojo de pancha (vainilla y chocolate)',8.00),('Apastelada','Acordeón',7.00),
  ('Apastelada','Rosquilla',6.00),('Apastelada','Almohada',8.00),
  ('Muffins y panqués','Muffin chico chocolate y vainilla',6.00),
  ('Muffins y panqués','Muffin grande',10.00),('Muffins y panqués','Panqué entero',60.00),
  ('Bisquet','Bisquet',7.00),
  ('Donas','Dona grande',10.00),('Donas','Dona chica',6.00),('Donas','Dona mini',4.00),
  ('Pan tradicional','Beso',10.00),('Pan tradicional','Colorado',5.00),
  ('Pan tradicional','Pambazo',4.00),('Pan tradicional','Torta',3.00)
)
insert into public.productos(panaderia_id,nombre,precio,activo,categoria_id)
select p.id,d.nombre,d.precio,true,c.id
from pizzan p cross join datos d
join public.categorias_productos c
  on c.panaderia_id=p.id and lower(c.nombre)=lower(d.categoria)
where not exists (
  select 1 from public.productos x
  where x.panaderia_id=p.id and lower(x.nombre)=lower(d.nombre)
);

-- La carpeta de desactivados es única, permanente y no puede modificarse.
create or replace function public.proteger_categoria_productos_desactivados()
returns trigger language plpgsql set search_path=''
as $$
begin
  if old.protegida then
    if tg_op='DELETE' then
      raise exception 'La categoría Productos desactivados es permanente.';
    end if;
    if new.nombre <> old.nombre or new.protegida is distinct from true or new.activa is distinct from true then
      raise exception 'La categoría Productos desactivados está protegida.';
    end if;
  end if;
  if tg_op='DELETE' then return old; end if;
  return new;
end;
$$;
drop trigger if exists proteger_categoria_desactivados on public.categorias_productos;
create trigger proteger_categoria_desactivados
before update or delete on public.categorias_productos
for each row execute function public.proteger_categoria_productos_desactivados();
