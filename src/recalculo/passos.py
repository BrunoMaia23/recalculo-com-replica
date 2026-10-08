"""Os quatro passos do recálculo diário.

1. Na origem, consolida o valor de cada item a partir das retenções e grava uma linha de controle com
   uma marca única, a quantidade de itens e a soma.
2. Espera a replicação levar as duas tabelas ao banco analítico. Não basta a marca aparecer: a
   quantidade e a soma do que chegou têm que bater com a linha de controle. Se não bater dentro do
   prazo, para tudo; somar em cima de uma réplica velha dá um número errado com cara de certo.
3. No analítico, recalcula o total de cada caso somando os itens DISTINTOS do caso.
4. Confere o resultado antes de terminar.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime


class ReplicaAtrasada(Exception):
    pass


@dataclass(frozen=True)
class Controle:
    marca: str
    itens: int
    soma: int


def recalcular_origem(origem: sqlite3.Connection, marca: str | None = None) -> Controle:
    marca = marca or uuid.uuid4().hex[:12]
    origem.execute("BEGIN")
    origem.execute("DELETE FROM item_valor")
    origem.execute("INSERT INTO item_valor SELECT item, sum(centavos) FROM retencao GROUP BY item")
    itens, soma = origem.execute("SELECT count(*), coalesce(sum(centavos), 0) FROM item_valor").fetchone()
    origem.execute("INSERT INTO recalculo VALUES (?, ?, ?, ?)",
                   [marca, itens, soma, datetime.now().isoformat(timespec="seconds")])
    origem.execute("COMMIT")
    return Controle(marca, itens, soma)


def aguardar_replica(analitico: sqlite3.Connection, controle: Controle, prazo: float = 60.0,
                     intervalo: float = 2.0) -> float:
    """Espera a réplica ficar igual à origem para esta marca. Devolve quanto tempo esperou."""
    inicio = time.monotonic()
    while True:
        chegou = analitico.execute("SELECT itens, soma FROM recalculo WHERE marca = ?", [controle.marca]).fetchone()
        if chegou:
            itens, soma = analitico.execute(
                "SELECT count(*), coalesce(sum(centavos), 0) FROM item_valor").fetchone()
            if (itens, soma) == (controle.itens, controle.soma):
                return time.monotonic() - inicio
        if time.monotonic() - inicio >= prazo:
            raise ReplicaAtrasada(f"a réplica não ficou igual à origem em {prazo:g}s (marca {controle.marca})".replace(".", ","))
        time.sleep(intervalo)


def recalcular_casos(analitico: sqlite3.Connection) -> int:
    agora = datetime.now().isoformat(timespec="seconds")
    analitico.execute("BEGIN")
    alterados = analitico.execute("""
        UPDATE caso SET total_centavos = coalesce((
            SELECT sum(v.centavos)
            FROM (SELECT DISTINCT item FROM caso_item WHERE caso_item.caso = caso.id) d
            JOIN item_valor v ON v.item = d.item), 0),
            atualizado_em = ?""", [agora]).rowcount
    analitico.execute("COMMIT")
    return alterados


def total_ingenuo(analitico: sqlite3.Connection, caso: int) -> int:
    """A soma direta pelo JOIN, que conta duas vezes o item repetido no caso. Só para comparar."""
    return analitico.execute("""
        SELECT coalesce(sum(v.centavos), 0) FROM caso_item ci JOIN item_valor v ON v.item = ci.item
        WHERE ci.caso = ?""", [caso]).fetchone()[0]


def validar(origem: sqlite3.Connection, analitico: sqlite3.Connection, controle: Controle) -> list[str]:
    problemas = []
    sem_total = analitico.execute("SELECT count(*) FROM caso WHERE total_centavos IS NULL").fetchone()[0]
    if sem_total:
        problemas.append(f"{sem_total} casos sem total")
    divergentes = analitico.execute("""
        SELECT c.id FROM caso c WHERE c.total_centavos <> coalesce((
            SELECT sum(v.centavos) FROM (SELECT DISTINCT item FROM caso_item WHERE caso = c.id) d
            JOIN item_valor v ON v.item = d.item), 0)""").fetchall()
    if divergentes:
        problemas.append(f"{len(divergentes)} casos com total diferente da soma dos itens distintos")
    sem_valor = analitico.execute("""
        SELECT count(DISTINCT ci.item) FROM caso_item ci LEFT JOIN item_valor v ON v.item = ci.item
        WHERE v.item IS NULL""").fetchone()[0]
    if sem_valor:
        quais = "item de caso" if sem_valor == 1 else "itens de casos"
        problemas.append(f"{sem_valor} {quais} sem valor na réplica (aviso: entram como zero)")
    origem_itens, origem_soma = origem.execute("SELECT count(*), coalesce(sum(centavos), 0) FROM item_valor").fetchone()
    if (origem_itens, origem_soma) != (controle.itens, controle.soma):
        problemas.append("a origem mudou depois do recálculo; rode de novo")
    return problemas
