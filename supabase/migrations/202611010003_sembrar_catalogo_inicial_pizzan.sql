-- Semilla idempotente del catálogo de Panadería Pizzan.
-- El precio de Rebanadas queda pendiente de confirmación y por eso no se inserta.
with pizzan as (
  select id from public.panaderias
  where lower(nombre) like '%pizzan%'
  order by id limit 1
), iniciales(nombre) as (
  values ('Hojaldres'),('Conchas y pan dulce'),('Croissants y más'),('Apastelada'),
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
  where lower(nombre) like '%pizzan%'
  order by id limit 1
), datos(categoria,nombre,precio) as (
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
