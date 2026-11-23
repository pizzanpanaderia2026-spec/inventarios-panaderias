import unittest
from types import SimpleNamespace
from locales import _estado_eliminacion_local

class Q:
    def __init__(self,t,d): self.t=t; self.d=d; self.f={}; self.n={}
    def select(self,*a): return self
    def eq(self,k,v): self.f[k]=v; return self
    def neq(self,k,v): self.n[k]=v; return self
    def in_(self,k,v): self.f[k]=list(v); return self
    def limit(self,n): self.l=n; return self
    def execute(self):
        if self.t=="panaderias": rows=[self.d["local"]] if self.d["local"]["id"]==self.f.get("id") else self.d.get("other_active",[])
        elif self.t=="accesos_panaderias": rows=self.d.get("other_access",{}).get(self.f["usuario_id"],[]) if "usuario_id" in self.f else self.d.get("access",[])
        else: rows=self.d.get(self.t,[])
        for k,v in self.f.items():
            if k=="id" and self.t=="panaderias": continue
            rows=[r for r in rows if r.get(k) in v] if isinstance(v,list) else [r for r in rows if r.get(k)==v]
        for k,v in self.n.items(): rows=[r for r in rows if r.get(k)!=v]
        return SimpleNamespace(data=rows[:getattr(self,"l",len(rows))])
class S:
    def __init__(self,d): self.d=d
    def table(self,n): return Q(n,self.d)
class T(unittest.TestCase):
    def core(self,**kw):
        d={"local":{"id":2,"nombre":"G","foto_key":None,"activa":True},"other_active":[{"id":1,"activa":True}],"access":[],"other_access":{},"productos":[],"inventario_detalles":[],"cierres_diarios":[],"produccion_registros":[],"archivos_archivados":[]}; d.update(kw); return SimpleNamespace(supabase=S(d))
    def test_empty(self): self.assertEqual(_estado_eliminacion_local(self.core(),2)[1],[])
    def test_disabled_products_ok(self): self.assertEqual(_estado_eliminacion_local(self.core(productos=[{"id":8,"activo":False}]),2)[1],[])
    def test_active_products_block(self): self.assertIn("Productos activos registrados",_estado_eliminacion_local(self.core(productos=[{"id":8,"activo":True}]),2)[1])
    def test_old_inventory_detail_blocks(self): self.assertTrue(_estado_eliminacion_local(self.core(productos=[{"id":8,"activo":False}],inventario_detalles=[{"id":1,"producto_id":8}]),2)[1])
    def test_access_with_other_local_ok(self): self.assertEqual(_estado_eliminacion_local(self.core(access=[{"usuario_id":"u","panaderia_id":2}],other_access={"u":[{"panaderia_id":1}]}),2)[1],[])
    def test_only_access_blocks(self): self.assertTrue(_estado_eliminacion_local(self.core(access=[{"usuario_id":"u","panaderia_id":2}]),2)[1])
if __name__=="__main__": unittest.main()
