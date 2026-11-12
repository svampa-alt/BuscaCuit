"""Consulta el artefacto SQLite generado por actualizar-padron.yml."""
import argparse
import json
import sqlite3

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("consulta")
    parser.add_argument("--db",default="output/padron.sqlite")
    parser.add_argument("--limite",type=int,default=30)
    args=parser.parse_args()
    if len(args.consulta.strip())<3:
        parser.error("Ingresá al menos tres caracteres")
    conn=sqlite3.connect(f"file:{args.db}?mode=ro",uri=True)
    query="%"+args.consulta.upper().replace("%",r"\%").replace("_",r"\_")+"%"
    rows=conn.execute("SELECT cuit, denominacion FROM contribuyentes WHERE upper(denominacion) LIKE ? ESCAPE '\\' OR cuit LIKE ? ESCAPE '\\' LIMIT ?",(query,query,args.limite)).fetchall()
    print(json.dumps([{"cuit":r[0],"razon_social":r[1],"fuente":"padrón ARCA; verificar titularidad comercial"} for r in rows],ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
