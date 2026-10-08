import threading

import pytest

from recalculo import bancos, passos


@pytest.fixture
def bases(tmp_path):
    origem = bancos.conectar(tmp_path / "origem.sqlite", bancos.ORIGEM)
    analitico = bancos.conectar(tmp_path / "analitico.sqlite", bancos.ANALITICO)
    origem.executemany("INSERT INTO retencao VALUES (?, ?)", [(1, 100), (1, 50), (2, 200), (3, 300)])
    analitico.executemany("INSERT INTO caso (id) VALUES (?)", [(10,), (20,)])
    analitico.executemany("INSERT INTO caso_item VALUES (?, ?)", [(10, 1), (10, 2), (10, 1), (20, 3)])
    yield origem, analitico
    origem.close()
    analitico.close()


def test_recalculo_na_origem_grava_o_controle(bases):
    origem, _ = bases
    c = passos.recalcular_origem(origem, "m1")
    assert (c.itens, c.soma) == (3, 650)
    assert origem.execute("SELECT item, centavos FROM item_valor ORDER BY item").fetchall() == [(1, 150), (2, 200), (3, 300)]
    assert origem.execute("SELECT itens, soma FROM recalculo WHERE marca = 'm1'").fetchone() == (3, 650)


def test_espera_a_replicacao_chegar(bases):
    origem, analitico = bases
    c = passos.recalcular_origem(origem, "m1")
    threading.Timer(0.3, bancos.replicar, args=(origem, analitico)).start()
    assert 0.2 < passos.aguardar_replica(analitico, c, prazo=5, intervalo=0.05) < 5


def test_sem_replicacao_para_no_prazo(bases):
    origem, analitico = bases
    c = passos.recalcular_origem(origem, "m1")
    with pytest.raises(passos.ReplicaAtrasada, match="m1"):
        passos.aguardar_replica(analitico, c, prazo=0.3, intervalo=0.05)


def test_marca_chegou_mas_os_dados_ainda_nao(bases):
    origem, analitico = bases
    c = passos.recalcular_origem(origem, "m1")
    # a replicação aplicou a tabela de controle antes da de valores
    analitico.execute("INSERT INTO recalculo VALUES ('m1', 3, 650, 'agora')")
    analitico.execute("INSERT INTO item_valor VALUES (1, 150)")
    with pytest.raises(passos.ReplicaAtrasada):
        passos.aguardar_replica(analitico, c, prazo=0.3, intervalo=0.05)


def test_total_do_caso_conta_item_repetido_uma_vez_so(bases):
    origem, analitico = bases
    passos.recalcular_origem(origem, "m1")
    bancos.replicar(origem, analitico)
    assert passos.recalcular_casos(analitico) == 2
    totais = dict(analitico.execute("SELECT id, total_centavos FROM caso").fetchall())
    assert totais == {10: 350, 20: 300}
    assert passos.total_ingenuo(analitico, 10) == 500  # 150 contado duas vezes


def test_validacao(bases):
    origem, analitico = bases
    c = passos.recalcular_origem(origem, "m1")
    bancos.replicar(origem, analitico)
    passos.recalcular_casos(analitico)
    assert passos.validar(origem, analitico, c) == []
    analitico.execute("UPDATE caso SET total_centavos = 1 WHERE id = 20")
    origem.execute("INSERT INTO retencao VALUES (9, 10)")
    origem.execute("DELETE FROM item_valor")
    problemas = passos.validar(origem, analitico, c)
    assert any("total diferente" in p for p in problemas)
    assert any("a origem mudou" in p for p in problemas)


def test_item_de_caso_sem_valor_vira_zero_e_aviso(bases):
    origem, analitico = bases
    analitico.execute("INSERT INTO caso_item VALUES (20, 99)")
    c = passos.recalcular_origem(origem, "m1")
    bancos.replicar(origem, analitico)
    passos.recalcular_casos(analitico)
    assert analitico.execute("SELECT total_centavos FROM caso WHERE id = 20").fetchone()[0] == 300
    assert passos.validar(origem, analitico, c) == ["1 item de caso sem valor na réplica (aviso: entram como zero)"]
