import streamlit as st

#!/usr/bin/env python3
"""
Buscador de datos
-----------------
Importa un archivo CSV a una base SQLite (con búsqueda de texto completo)
y permite consultarlo desde la terminal. No necesita instalar nada.

Uso:
    python buscador.py demo                        # crea datos de ejemplo (clientes.csv)
    python buscador.py importar clientes.csv       # carga el CSV en la base
    python buscador.py buscar "lima movistar"      # busca en todas las columnas
    python buscador.py buscar "lima" -c ciudad     # busca solo en una columna
    python buscador.py buscar "ana" -n 5 --csv salida.csv   # limita y exporta resultados
    python buscador.py interactivo                 # modo de búsqueda continua
    python buscador.py columnas                    # muestra las columnas disponibles
"""
import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

DB_POR_DEFECTO = "datos.db"


# ---------- Base de datos ----------

def conectar(ruta_db):
    con = sqlite3.connect(ruta_db)
    con.row_factory = sqlite3.Row
    return con


def limpiar_nombre(nombre, usados):
    """Convierte un encabezado en un nombre de columna seguro y único."""
    base = re.sub(r"\W+", "_", nombre.strip().lower()).strip("_") or "columna"
    if base[0].isdigit():
        base = "c_" + base
    nombre_final, i = base, 2
    while nombre_final in usados:
        nombre_final = f"{base}_{i}"
        i += 1
    usados.add(nombre_final)
    return nombre_final


def importar_csv(ruta_csv, ruta_db):
    if not Path(ruta_csv).exists():
        sys.exit(f"No encuentro el archivo: {ruta_csv}")

    # utf-8-sig quita la marca BOM que añade Excel
    with open(ruta_csv, newline="", encoding="utf-8-sig") as f:
        muestra = f.read(4096)
        f.seek(0)
        try:
            dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
        except csv.Error:
            dialecto = csv.excel
        lector = csv.reader(f, dialecto)
        try:
            encabezados = next(lector)
        except StopIteration:
            sys.exit("El CSV está vacío.")

        usados = set()
        columnas = [limpiar_nombre(h, usados) for h in encabezados]
        filas = [
            (fila + [""] * len(columnas))[: len(columnas)]
            for fila in lector
            if any(c.strip() for c in fila)
        ]

    con = conectar(ruta_db)
    con.execute("DROP TABLE IF EXISTS datos")
    con.execute("DROP TABLE IF EXISTS meta")
    # FTS5: búsqueda rápida, sin distinguir mayúsculas ni tildes
    con.execute(
        f"CREATE VIRTUAL TABLE datos USING fts5({', '.join(columnas)}, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    con.execute("CREATE TABLE meta (orden INTEGER, columna TEXT, original TEXT)")
    con.executemany(
        "INSERT INTO meta VALUES (?, ?, ?)",
        [(i, c, o) for i, (c, o) in enumerate(zip(columnas, encabezados))],
    )
    marcas = ", ".join("?" * len(columnas))
    con.executemany(f"INSERT INTO datos VALUES ({marcas})", filas)
    con.commit()
    con.close()
    print(f"Listo: {len(filas)} registros importados, {len(columnas)} columnas.")
    print("Columnas:", ", ".join(columnas))


def obtener_columnas(con):
    try:
        return [r["columna"] for r in con.execute("SELECT columna FROM meta ORDER BY orden")]
    except sqlite3.OperationalError:
        sys.exit("Aún no hay datos. Primero ejecuta: python buscador.py importar archivo.csv")


# ---------- Búsqueda ----------

def construir_consulta(texto, columna=None, exacto=False):
    """Convierte lo que escribe el usuario en una consulta FTS5 segura."""
    palabras = re.findall(r"\w+", texto, flags=re.UNICODE)
    if not palabras:
        return None
    if exacto:
        consulta = '"' + " ".join(palabras) + '"'          # frase exacta
    else:
        consulta = " ".join(f'"{p}"*' for p in palabras)    # todas las palabras, por prefijo
    if columna:
        consulta = f"{columna} : ({consulta})"
    return consulta


def buscar(ruta_db, texto, columna=None, limite=20, exacto=False):
    con = conectar(ruta_db)
    columnas = obtener_columnas(con)
    if columna and columna.lower() not in columnas:
        con.close()
        sys.exit(f"La columna '{columna}' no existe. Disponibles: {', '.join(columnas)}")

    consulta = construir_consulta(texto, columna.lower() if columna else None, exacto)
    if consulta is None:
        con.close()
        return columnas, []

    filas = con.execute(
        "SELECT * FROM datos WHERE datos MATCH ? ORDER BY rank LIMIT ?",
        (consulta, limite),
    ).fetchall()
    con.close()
    return columnas, [dict(f) for f in filas]


# ---------- Presentación ----------

def mostrar_tabla(columnas, filas, ancho_max=28):
    if not filas:
        print("Sin resultados.")
        return

    def corto(valor):
        valor = str(valor).replace("\n", " ")
        return valor if len(valor) <= ancho_max else valor[: ancho_max - 1] + "…"

    anchos = {
        c: min(ancho_max, max(len(c), *(len(corto(f[c])) for f in filas)))
        for c in columnas
    }
    print(" | ".join(c.upper().ljust(anchos[c]) for c in columnas))
    print("-+-".join("-" * anchos[c] for c in columnas))
    for f in filas:
        print(" | ".join(corto(f[c]).ljust(anchos[c]) for c in columnas))
    print(f"\n{len(filas)} resultado(s).")


def exportar_csv(ruta, columnas, filas):
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas)
    print(f"Resultados guardados en {ruta}")


# ---------- Comandos ----------

def crear_demo(ruta="clientes.csv"):
    datos = [
        ("id", "nombre", "ciudad", "operador", "plan", "estado"),
        (1, "Ana Torres", "Lima", "Movistar", "Fibra 300 Mbps", "Activo"),
        (2, "Luis Quispe", "Arequipa", "Claro", "Móvil 20 GB", "Pendiente"),
        (3, "María Gómez", "Lima", "Movistar", "Móvil 50 GB", "Activo"),
        (4, "José Ramírez", "Cusco", "Entel", "Móvil 10 GB", "Cancelado"),
        (5, "Lucía Fernández", "Trujillo", "Movistar", "Fibra 500 Mbps", "Activo"),
        (6, "Carlos Medina", "Lima", "Bitel", "Móvil 30 GB", "Pendiente"),
        (7, "Andrea Salas", "Piura", "Claro", "Fibra 200 Mbps", "Activo"),
    ]
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(datos)
    print(f"Archivo de ejemplo creado: {ruta}")
    print(f"Ahora ejecuta: python buscador.py importar {ruta}")


def modo_interactivo(ruta_db):
    con = conectar(ruta_db)
    columnas = obtener_columnas(con)
    con.close()
    print("Búsqueda interactiva. Escribe 'salir' para terminar.")
    print(f"Columnas: {', '.join(columnas)}")
    print("Tip: usa columna:texto para filtrar, por ejemplo  ciudad:lima\n")
    while True:
        try:
            entrada = input("buscar> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if entrada.lower() in {"salir", "exit", "q"}:
            break
        if not entrada:
            continue
        columna, texto = None, entrada
        if ":" in entrada:
            posible, resto = entrada.split(":", 1)
            if posible.strip().lower() in columnas:
                columna, texto = posible.strip(), resto
        cols, filas = buscar(ruta_db, texto, columna)
        mostrar_tabla(cols, filas)
        print()


def main():
    parser = argparse.ArgumentParser(description="Buscador de datos sobre archivos CSV")
    parser.add_argument("--db", default=DB_POR_DEFECTO, help="archivo de base de datos")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("demo", help="crea un CSV de ejemplo")

    p_imp = sub.add_parser("importar", help="carga un CSV en la base")
    p_imp.add_argument("archivo")

    p_bus = sub.add_parser("buscar", help="busca texto en los datos")
    p_bus.add_argument("texto")
    p_bus.add_argument("-c", "--columna", help="buscar solo en esta columna")
    p_bus.add_argument("-n", "--limite", type=int, default=20, help="máximo de resultados")
    p_bus.add_argument("-e", "--exacto", action="store_true", help="coincidir la frase exacta")
    p_bus.add_argument("--csv", help="guardar los resultados en un CSV")

    sub.add_parser("interactivo", help="búsqueda continua")
    sub.add_parser("columnas", help="lista las columnas")

    args = parser.parse_args()

    if args.comando == "demo":
        crear_demo()
    elif args.comando == "importar":
        importar_csv(args.archivo, args.db)
    elif args.comando == "buscar":
        columnas, filas = buscar(args.db, args.texto, args.columna, args.limite, args.exacto)
        mostrar_tabla(columnas, filas)
        if args.csv and filas:
            exportar_csv(args.csv, columnas, filas)
    elif args.comando == "interactivo":
        modo_interactivo(args.db)
    elif args.comando == "columnas":
        con = conectar(args.db)
        print(", ".join(obtener_columnas(con)))
        con.close()


if __name__ == "__main__":
    main()
