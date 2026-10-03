# Princípio de menor privilégio

O menor privilégio é a regra de segurança mais citada e a menos aplicada, e
o motivo é simples: **ele custa conveniência**. Abrir tudo é sempre mais
rápido, e a diferença entre "rápido agora" e "certo depois" só aparece quando
alguém pergunta como um pacote chegou onde não devia.

Este laboratório implementa o princípio em três lugares, e cada um deles é
uma negação específica em vez de uma permissão geral.

## 1. O banco só recebe da aplicação e do bastion

A regra `aplicacao-entra-no-banco` permite a faixa 10.20.0.0/24 na porta 5432.
A regra `bastion-entra-no-banco` permite um único host, 10.10.0.5, na mesma
porta. Todo o resto é negado — incluindo a DMZ inteira, que é onde um invasor
estaria depois de comprometer um servidor web.

A forma tentadora de escrever isso seria "porta 5432 aberta para a VPC".
Funciona nos testes. E abre o banco para qualquer máquina que um dia entre na
VPC, incluindo a que não existe ainda.

## 2. A camada de dados não fala com a internet

A regra `dados-sai-para-internet` nega qualquer protocolo, qualquer porta. É
a proteção contra exfiltração: mesmo com uma regra de entrada errada, o dado
não sai.

Menor privilégio aplicado à saída, não só à entrada. A maioria dos desenhos
restringe quem entra e esquece de restringir quem sai — e quem sai é onde o
dado vaza.

## 3. A resposta não reabre a tabela

Tráfego de resposta passa pelo **estado da conexão**, não por regra nova. Uma
regra `relacionado`-permitir na tabela seria uma exceção escrita para cada
resposta, e cada exceção é uma permissão que alguém esqueceu de remover depois.

O estado mora no motor, e morre com a conexão. Por isso ele não acumula.

## O que o menor privilégio não é

Não é "negar tudo e liberar sob pedido". Um desenho assim congela: cada
deploy novo precisa de uma exceção, as exceções se acumulam, e em seis meses
a tabela tem quatrocentas regras que ninguém entende — que é exatamente a
situação que o princípio deveria evitar.

É **negar por padrão, permitir por motivo, e escrever o motivo**. Toda regra
deste laboratório carrega `motivo`, e o tracador imprime o motivo da regra
que decidiu. O motivo é o que sobrevive à próxima pessoa que mexer no
arquivo: sem ele, uma regra sem contexto é removida na primeira faxina.
Com ele, a faxina sabe o que pode tocar e o que não pode.

## Como verificar

```powershell
python -m vpcsim cenarios
```

Vinte cenários, cada um com o resultado esperado. Dois deles exercem o
princípio pelo lado da resposta: a resposta do banco para a aplicação passa
pelo estado da conexão, e a mesma resposta sem estado cai na tabela e é
negada. Se o princípio quebrar, um desses dois cenários acusa primeiro.