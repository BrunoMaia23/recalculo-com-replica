"""Os dois bancos, em SQLite.

- origem (o banco transacional): as retenções lançadas por item, e duas tabelas que o recálculo
  mantém e que são replicadas: o valor consolidado por item e uma linha de controle por recálculo.
- analítico: recebe as duas tabelas pela replicação e guarda os casos, cada um com os seus itens.
  Um item pode aparecer mais de uma vez no mesmo caso.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ORIGEM = """
CREATE TABLE IF NOT EXISTS retencao (item INTEGER NOT NULL, centavos INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS item_valor (item INTEGER PRIMARY KEY, centavos INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS recalculo (
    marca TEXT PRIMARY KEY, itens INTEGER NOT NULL, soma INTEGER NOT NULL, feito_em TEXT NOT NULL);
"""
ANALITICO = """
CREATE TABLE IF NOT EXISTS item_valor (item INTEGER PRIMARY KEY, centavos INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS recalculo (
    marca TEXT PRIMARY KEY, itens INTEGER NOT NULL, soma INTEGER NOT NULL, feito_em TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS caso (id INTEGER PRIMARY KEY, total_centavos INTEGER, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS caso_item (caso INTEGER NOT NULL REFERENCES caso (id), item INTEGER NOT NULL);
"""
REPLICADAS = ("item_valor", "recalculo")


def conectar(caminho: Path | str, esquema: str) -> sqlite3.Connection:
    con = sqlite3.connect(caminho, isolation_level=None, check_same_thread=False)
    con.executescript(esquema)
    return con


def replicar(origem: sqlite3.Connection, analitico: sqlite3.Connection) -> None:
    """Um ciclo da replicação: as tabelas replicadas ficam iguais às da origem, numa transação só."""
    analitico.execute("BEGIN")
    for tabela in REPLICADAS:
        linhas = origem.execute(f"SELECT * FROM {tabela}").fetchall()
        analitico.execute(f"DELETE FROM {tabela}")
        if linhas:
            analitico.executemany(f"INSERT INTO {tabela} VALUES ({', '.join('?' * len(linhas[0]))})", linhas)
    analitico.execute("COMMIT")
