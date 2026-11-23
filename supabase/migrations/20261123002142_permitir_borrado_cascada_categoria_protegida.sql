-- Permite eliminar en cascada la categoría protegida solo cuando se elimina
-- el local vacío que la contiene. La categoría no puede borrarse por separado.
CREATE OR REPLACE FUNCTION public.proteger_categoria_productos_desactivados()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
  IF OLD.protegida THEN
    IF TG_OP = 'DELETE' THEN
      IF EXISTS (
        SELECT 1 FROM public.panaderias p WHERE p.id = OLD.panaderia_id
      ) THEN
        RAISE EXCEPTION 'La categoría Productos desactivados es permanente.';
      END IF;
      RETURN OLD;
    END IF;
    IF NEW.nombre <> OLD.nombre
       OR NEW.protegida IS DISTINCT FROM TRUE
       OR NEW.activa IS DISTINCT FROM TRUE THEN
      RAISE EXCEPTION 'La categoría Productos desactivados está protegida.';
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;
