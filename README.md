# recalculo-com-replica

[![testes](https://github.com/BrunoMaia23/recalculo-com-replica/actions/workflows/testes.yml/badge.svg)](https://github.com/BrunoMaia23/recalculo-com-replica/actions/workflows/testes.yml)

Um número precisa ser recalculado todo dia em dois bancos: primeiro no transacional (lá, Oracle), onde
estão os lançamentos, e depois no analítico (lá, PostgreSQL), que recebe as tabelas por replicação e
soma por caso. Se o segundo passo roda antes de a réplica chegar, ele soma em cima dos dados de ontem e
grava um total errado que parece certo. Foi um projeto do time em que eu trabalhei, rodando como uma DAG
diária do Airflow. Para mostrar aqui, troquei os nomes por genéricos (item, caso, retenção) e simulei a
replicação entre dois SQLite.

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

## Três dias

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m recalculo demo
```

No primeiro dia a replicação atrasa e o recálculo espera; no segundo ela para de vez; no terceiro volta.

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

Os tempos de espera variam um pouco de uma execução para outra. Os testes cobrem também o caso mais
traiçoeiro, que a demo não mostra: a marca chega à réplica antes dos dados.
