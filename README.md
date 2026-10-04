<div align="center">

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/tests-105%20passing-brightgreen?style=flat-square" alt="Tests">
  <img src="https://img.shields.io/badge/coverage-90%25-green-brightgreen?style=flat-square" alt="Coverage">
  <img src="https://img.shields.io/badge/deps-PyYAML%20only-blue?style=flat-square" alt="Deps">
  <img src="https://img.shields.io/badge/license-MIT-yellow?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/platform-Windows-blue?style=flat-square" alt="Windows">
</p>

</div>

# vpc-3-tier-segura

Simulador local de uma VPC em três camadas com motor de firewall: avalia qual
tráfego é permitido e mostra em qual regra a decisão foi tomada.

A local simulator of a three-tier VPC with a firewall decision engine: it
evaluates which traffic is allowed and shows which rule made the decision.

> **Nada aqui é real.** Nenhuma nuvem é acessada por este projeto. As camadas
> são simuladas em código, o que é o único jeito de demonstrar o conceito sem
> custo e sem credencial. O pacote tem uma dependência externa e ela é o PyYAML.

## O que é

Uma VPC de três camadas — DMZ, aplicação, dados — com bastion e balanceador,
regras de segurança e um motor que **avalia** cada pacote contra as regras e a
topologia. Para cada pacote, o tracador mostra o caminho inteiro: origem,
destino, rota e a regra que decidiu.

## Por que foi feito

Entender regra de firewall por construção ensina mais do que ler
documentação. Uma regra se escreve em cinco minutos e se erra em cinco
minutos; o que ensina é construir o motor, avaliar combinações e ver o
resultado virar quando uma regra se move de lugar.

O argumento de quem automatiza infraestrutura não é "eu automatizei", é "eu
tenho uma máquina que me diz o que passa e o que não passa, e por quê".

## Como rodar

Um comando, saída esperada:

```powershell
python -m vpcsim cenarios
```

```
cenario                                        esperado    obtido      veredito
------------------------------------------------------------------------------
internet-para-banco                            bloqueado   bloqueado   ok
bastion-para-banco                             permitido   permitido   ok
app-para-banco                                 permitido   permitido   ok
...
todos os 20 cenarios concordam com o motor
```

O traçado de um pacote:

```powershell
python -m vpcsim tracar
```

```
[internet-para-banco] 203.0.113.50 -> 10.30.0.11
  origem: origem anonima: 203.0.113.50
  destino: banco-01, 10.30.0.11, sub-rede dados-privada
  rota: rota dmz-publica -> 0.0.0.0/0, proximo salto 203.0.113.1
  avaliacao: etapa bloqueado: A regra que o desenho inteiro existe para
    sustentar: o banco nao aceita conexao da internet...
  regra: negar entrada 203.0.113.0/24 -> 10.30.0.11/32:5432/tcp [novo] #internet-entra-no-banco
VEREDITO: BLOQUEADO
resultado esperado: bloqueado   obtido: bloqueado   [ok]
```

Instalação:

```powershell
pip install -e ".[dev]"
```

## As três camadas

A propriedade que o desenho quer tornar verdadeira: **o banco não aceita
conexão vinda da internet.** Todo o resto existe para que essa frase seja
consequência do desenho, e não desejo.

| Camada | Sub-rede | Visibilidade | Quem chega |
|---|---|---|---|
| DMZ | `dmz-publica` 203.0.113.0/24 | pública | internet, nas portas de web |
| Aplicação | `app-privada` 10.20.0.0/24 | privada | só a DMZ |
| Dados | `dados-privada` 10.30.0.0/24 | privada, sem rota para fora | só a aplicação e o bastion |
| Gerência | `gestao-privada` 10.10.0.0/24 | privada | o bastion, o único com SSH de fora |
| Parceiro | `parceiro-publica` 198.51.100.0/24 | pública, sem rota de saída | alcança, mas não sai |

O bloco `203.0.113.0/24` é o bloco de documentação da RFC 5737; `198.51.100.0/24`
é o TEST-NET-2 da mesma RFC. Nenhum dos dois existe em rota real.

## Rota e regra são mecanismos diferentes

Uma regra diz o que é **permitido**. Uma rota diz o que é **possível**. Um
pacote sem rota de retorno não é "bloqueado por política": ele simplesmente
não chega, e nenhuma regra poderia mudar isso.

É por isso que o motor verifica a rota **antes** da tabela. O banco é
protegido duas vezes: a regra `internet-entra-no-banco` nega, e a camada de
dados não tem rota para a internet. Qualquer uma sozinha seria insuficiente.

## O motor em cinco etapas

Toda avaliação termina em exatamente uma etapa:

| Etapa | Significado |
|---|---|
| `relacionado` | resposta de conexão que o estado conhece — passa sem reabrir a tabela |
| `sem-rota` | o pacote não tem para onde ir |
| `permitido` | uma regra permitiu |
| `bloqueado` | uma regra negou |
| `sem-regra` | nada disse nada — e o motor nega |

**A ordem é fixa e é a política.** Resposta antes de rota, rota antes de
tabela: trocar duas etapas troca o resultado de milhares de pacotes ao mesmo
tempo.

## Tráfego de retorno, sem abrir exceção

Uma conexão de ida tem resposta, e a resposta não passa por regra nova. Quando
passa, ela morre — e alguém acrescenta uma regra de "resposta" que permite mais
do que a intenção original.

O motor é **stateful**: um pacote marcado como relacionado ou estabelecido,
cujo par de endereços esteja autorizado nas duas direções, passa pelo estado.
A exceção para a resposta é a **conexão**, não uma regra nova — e é por isso
que ela não cresce a cada problema novo.

E marcar qualquer pacote como `relacionado` não contorna nada: sem o par
autorizado, o pacote cai na avaliação normal. Uma tabela que contivesse uma
regra `relacionado`-permitir seria uma porta dos fundos; esta não tem.

## O padrão é negar

Quando nenhuma regra casa, o motor nega. O oposto de uma ACL implícita que
permite. Regra esquecida vira acesso negado — visível, barulhento, corrigido em
um minuto — e não acesso concedido, silencioso.

A tabela termina com um `negar` explícito para que o limite esteja escrito no
arquivo, e não inferido do silêncio.

## O que aprendi

- **Classificar sem histórico é adivinhação.** A primeira versão deste motor não
  tinha manifesto de conexões, e uma resposta bem-sucedida caía na tabela. O
  estado resolveu, e o custo foi um parâmetro.
- **Rota que ignora a origem mente.** A primeira versão da função de rota
  filtrava só pelo destino, e a rota padrão da DMZ "alcançava" o banco. O
  tracer mostrava um próximo salto que nunca seria usado.
- **Ordem no arquivo é política.** A primeira regra que casa decide, e mover
  uma linha muda o que a VPC aceita. Por isso toda regra carrega `motivo`.
- **Um cenário com `porque` genérico não testa nada.** Cada um dos 20 tem a
  frase específica do que ele prova; um que dissesse "teste de firewall"
  passaria sem significar.
- **O relatório distingue "não rodou" de "não foi pedido".** Sem a distinção,
  quem lê conclui que algo foi verificado quando não foi.
- **Crases em brief de shell executam.** Um brief com `conexao.campo` entre
  crases fez o bash rodar como substituição de comando por 15 minutos. Nunca
  mais.

## Testes

```powershell
python -m pytest -v
```

105 testes, 90% de cobertura, 20 cenários. Cobrem o motor nas cinco etapas,
a ordem de avaliação, o tráfego de retorno com e sem estado, o modelo de rede,
as regras, o tracador, os cenários, a CLI e o portão de encoding.

Portões que a suíte não cobre sozinha:

```powershell
python tools/verificar_aceite.py     # as duas metades do critério de aceite
python tools/verificar_encoding.py   # nenhum caractere corrompido
python tools/gerar_exemplo.py        # regenera o exemplo de forma determinística
```

```
1) o arquivo tem os cenarios que a especificacao pede
   20 cenarios, todos com resultado esperado

2) o motor concorda com os vinte cenarios
   20 de 20 concordam com o motor

3) o tracador mostra o ponto exato do bloqueio
   20 de 20 tracados com veredito e regra citada
   etapas cobertas: {'bloqueado': 7, 'permitido': 6, 'sem-regra': 4, 'relacionado': 2, 'sem-rota': 1}

4) as etapas de estado, rota e sem-regra aparecem

ok: os 20 cenarios concordam com o motor, e o tracador mostra o ponto exato de cada decisao
```

## Estrutura

```
lab-backup-recuperacao/
├── src/vpcsim/              # o pacote
├── dados/                   # arquitetura, regras, 20 cenarios
├── docs/                    # modelo de seguranca, menor privilegio
├── exemplos/                # tracos de trafego gerados
├── tests/                   # 105 testes
└── tools/                   # gerador e portões
```

## Limitações

- **Não há ameaça real.** Nenhum pacote atravessa nada; o motor prova lógica
  de endereçamento, não resistência. Um modelo que nunca foi atacado mostra o
  desenho, não o risco.
- **Sem inspeção de pacote.** O motor avalia origem, destino, porta, protocolo
  e estado. Não olha conteúdo, fragmentação nem ordem de chegada.
- **ACLs avaliadas globalmente.** Sem direção por interface, sem ordem de
  avaliação entre ACLs, sem timeout de conexão.
- **Topologia fixa.** Três camadas mais parceiro e gerência; adicionar camada
  exige editar o YAML e as regras, não só declarar.
- **O estado vem do cenário.** As conexões autorizadas são declaradas, não
  observadas. Um motor real construiria a tabela de estado vendo o tráfego; este
  recebe a tabela pronta.
- **IPv4 apenas.** Sem IPv6, sem dual-stack, sem NAT.

## Licença

MIT.

---

## English

A local simulator of a three-tier VPC with a firewall decision engine.

### What it is

DMZ, application and data tiers, plus bastion and balancer, with security
rules and an engine that **evaluates** which traffic is allowed and shows
which rule made the decision. For every packet, the tracer shows the full
path: source, destination, route and the deciding rule.

### Why it was built

Understanding firewall rules by construction teaches more than reading
documentation. A rule takes five minutes to write and five to get wrong; what
teaches is building the engine and watching the result flip when a rule moves.

### How to run

```powershell
python -m vpcsim cenarios
```

```
internet-para-banco                            bloqueado   bloqueado   ok
bastion-para-banco                             permitido   permitido   ok
...
todos os 20 cenarios concordam com o motor
```

Install: `pip install -e ".[dev]"`

### The three tiers

The property the design wants true: **the database accepts no connection from
the internet.**

### Route and rule are different mechanisms

A rule says what is **allowed**. A route says what is **possible**. The engine
checks the route before the table.

### State

Return traffic passes by connection state, not by a new rule. And marking any
packet as `relacionado` bypasses nothing: without the authorized pair, the
packet falls through to normal evaluation.

### Deny by default

When no rule matches, the engine denies. A forgotten rule becomes denied
access — visible, loud, fixed in a minute — not silent granted access.

### Tests

105 tests, 91% coverage, 20 scenarios.

```powershell
python -m pytest -v
python tools/verificar_aceite.py
python tools/verificar_encoding.py
python tools/gerar_exemplo.py
```

### Limitations

- **No real threat.** The engine proves addressing logic, not resistance.
- **No packet inspection.** Source, destination, port, protocol and state only.
- **Globally evaluated ACLs.** No per-interface direction, no order, no timeouts.
- **Fixed topology.**
- **State comes from the scenario**, declared, not observed.
- **IPv4 only.**

### License

MIT.