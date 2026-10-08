"""Recálculo diário em dois bancos ligados por replicação, com a espera pela réplica."""
from __future__ import annotations

import argparse
import random
import shutil
import sys
import threading
from pathlib import Path

from . import bancos, passos

MARCADOR = ".recalculo-demo"


def reais(centavos: int) -> str:
    return f"{centavos / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def semear(origem, analitico, semente: int = 9) -> tuple[int, int]:
    rng = random.Random(semente)
    origem.execute("BEGIN")
    for item in range(1, 201):
        for _ in range(rng.randint(1, 4)):
            origem.execute("INSERT INTO retencao VALUES (?, ?)", [item, rng.randint(500, 90_000)])
    origem.execute("COMMIT")
    analitico.execute("BEGIN")
    repetidos = 0
    for caso in range(1, 41):
        analitico.execute("INSERT INTO caso (id) VALUES (?)", [caso])
        itens = rng.sample(range(1, 201), rng.randint(2, 8))
        if caso % 4 == 0:  # o mesmo item duas vezes no caso, como acontece quando ele vem de duas fontes
            itens.append(itens[0])
            repetidos += 1
        analitico.executemany("INSERT INTO caso_item VALUES (?, ?)", [(caso, i) for i in itens])
    analitico.execute("COMMIT")
    return 200, repetidos


def rodar(origem, analitico, prazo: float, intervalo: float, atraso_replicacao: float | None,
          marca: str | None = None) -> list[str] | None:
    controle = passos.recalcular_origem(origem, marca)
    print(f"[origem]      recálculo {controle.marca}: {controle.itens} itens, soma {reais(controle.soma)}")
    if atraso_replicacao is not None:  # a replicação de verdade roda sozinha; aqui, numa thread com atraso
        threading.Timer(atraso_replicacao, bancos.replicar, args=(origem, analitico)).start()
    try:
        esperou = passos.aguardar_replica(analitico, controle, prazo=prazo, intervalo=intervalo)
    except passos.ReplicaAtrasada as exc:
        print(f"[réplica]     {exc}: os casos NÃO foram recalculados")
        return None
    print(f"[réplica]     igual à origem depois de {esperou:.1f}s (marca, itens e soma conferidos)".replace(".", ",", 1))
    print(f"[casos]       {passos.recalcular_casos(analitico)} casos recalculados com itens distintos")
    problemas = passos.validar(origem, analitico, controle)
    print("[validação]   OK" if not problemas else "[validação]   " + "; ".join(problemas))
    return problemas


def demo(pasta: Path) -> int:
    if pasta.exists():
        if not (pasta / MARCADOR).exists():
            print(f"A pasta {pasta} já existe e não foi criada pela demo; escolha outra com --pasta.")
            return 2
        shutil.rmtree(pasta)
    pasta.mkdir(parents=True)
    (pasta / MARCADOR).write_text("pasta da demo do recálculo\n", encoding="utf-8")
    origem = bancos.conectar(pasta / "origem.sqlite", bancos.ORIGEM)
    analitico = bancos.conectar(pasta / "analitico.sqlite", bancos.ANALITICO)
    itens, repetidos = semear(origem, analitico)
    print(f"[dados]       {itens} itens com retenções na origem; 40 casos no analítico, "
          f"{repetidos} deles com um item repetido\n")

    print("== dia 1: a replicação demora 1,5s; o recálculo espera")
    primeiro = rodar(origem, analitico, prazo=10, intervalo=0.3, atraso_replicacao=1.5, marca="dia-1")
    caso = 4
    distinto = analitico.execute("SELECT total_centavos FROM caso WHERE id = ?", [caso]).fetchone()[0]
    print(f"[repetição]   caso {caso}: total com itens distintos {reais(distinto)}; "
          f"o JOIN direto daria {reais(passos.total_ingenuo(analitico, caso))}\n")

    print("== dia 2: chegam retenções novas e a replicação para")
    origem.execute("INSERT INTO retencao VALUES (1, 123456)")
    totais_antes = analitico.execute("SELECT sum(total_centavos) FROM caso").fetchone()[0]
    segundo = rodar(origem, analitico, prazo=1.5, intervalo=0.3, atraso_replicacao=None, marca="dia-2")
    totais_depois = analitico.execute("SELECT sum(total_centavos) FROM caso").fetchone()[0]
    print(f"[casos]       totais intocados: {'sim' if totais_antes == totais_depois else 'NÃO'}\n")

    print("== dia 2, de novo, com a replicação de volta")
    terceiro = rodar(origem, analitico, prazo=10, intervalo=0.3, atraso_replicacao=0.5, marca="dia-2-de-novo")
    origem.close()
    analitico.close()
    ok = primeiro == [] and segundo is None and totais_antes == totais_depois and terceiro == []
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="recalculo", description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("demo", help="três dias de recálculo, um deles com a replicação parada")
    p.add_argument("--pasta", type=Path, default=Path("demo"))
    a = parser.parse_args(argv)
    return demo(a.pasta)
