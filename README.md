# recalculo-com-replica

[![testes](https://github.com/BrunoMaia23/recalculo-com-replica/actions/workflows/testes.yml/badge.svg)](https://github.com/BrunoMaia23/recalculo-com-replica/actions/workflows/testes.yml)

Um número precisa ser recalculado todo dia em dois bancos: primeiro no transacional, onde estão os
lançamentos, e depois no analítico, que recebe as tabelas por replicação e soma por caso. Se o segundo
passo roda antes de a réplica chegar, ele soma em cima dos dados de ontem e grava um total errado que
parece certo. Foi um projeto do time em que eu trabalhei; este repositório refaz a ideia do zero, com
nomes genéricos (item, caso, retenção), SQLite e uma replicação simulada.

*In English: a daily recalculation across a source database and an analytics database linked by
replication. It waits until the replica provably matches the source (batch marker, row count and sum)
before computing anything, sums distinct items so a duplicated item is not counted twice, validates the
result, and refuses to run on a stale replica. Synthetic data.*

## Os quatro passos

1. **Origem.** Consolida o valor de cada item a partir dos lançamentos e grava uma linha de controle
   com uma marca única, a quantidade de itens e a soma.
2. **Espera.** Fica consultando o analítico até a marca aparecer e a quantidade e a soma do que chegou
   baterem com a linha de controle. Só a marca não basta: a replicação pode aplicar a tabela de
   controle antes da tabela de valores. Se não bater dentro do prazo, o processo para sem tocar nos
   casos e falha, para alguém olhar.
3. **Casos.** Recalcula o total de cada caso somando os itens distintos dele. Um item pode aparecer
   duas vezes no mesmo caso, e o JOIN direto contaria o valor duas vezes.
4. **Validação.** Nenhum caso sem total, todo total igual à soma dos seus itens distintos, aviso para
   item de caso que não tem valor na réplica, e erro se a origem mudou enquanto o processo rodava.

## A demo

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m recalculo demo
```

Três dias: no primeiro a replicação atrasa e o recálculo espera; no segundo ela para de vez; no terceiro
ela volta.

```
[dados]       200 itens com retenções na origem; 40 casos no analítico, 10 deles com um item repetido

== dia 1: a replicação demora 1,5s; o recálculo espera
[origem]      recálculo dia-1: 200 itens, soma 207.099,46
[réplica]     igual à origem depois de 1,8s (marca, itens e soma conferidos)
[casos]       40 casos recalculados com itens distintos
[validação]   OK
[repetição]   caso 4: total com itens distintos 2.466,11; o JOIN direto daria 3.570,69

== dia 2: chegam retenções novas e a replicação para
[origem]      recálculo dia-2: 200 itens, soma 208.334,02
[réplica]     a réplica não ficou igual à origem em 1,5s (marca dia-2): os casos NÃO foram recalculados
[casos]       totais intocados: sim

== dia 2, de novo, com a replicação de volta
[origem]      recálculo dia-2-de-novo: 200 itens, soma 208.334,02
[réplica]     igual à origem depois de 0,6s (marca, itens e soma conferidos)
[casos]       40 casos recalculados com itens distintos
[validação]   OK
```

Os tempos de espera variam um pouco de uma execução para outra.

## No projeto real

A origem é Oracle e o analítico é PostgreSQL, ligados por uma replicação que roda o tempo todo. O
processo é uma DAG diária do Airflow, e cada passo também pode ser rodado à mão.

## Testes

`pytest` cobre o recálculo na origem com a linha de controle, a espera que termina quando a réplica
chega, a que estoura o prazo, a marca que chega antes dos dados, o total por itens distintos (contra o
JOIN direto), a validação e o item sem valor.
