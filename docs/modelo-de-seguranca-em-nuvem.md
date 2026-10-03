# Modelo de seguranca em nuvem

Este documento expõe o raciocinio por tras do desenho da VPC simulada no laboratorio `vpcsim`. Nao se trata de um manual de regras; trata-se de explicar por que o desenho é como é e o que cada camada faz para que uma propriedade simples se mantenha verdadeira sem depender da sorte.

## Tres camadas, e por que a ordem e a seguranca

A propriedade que a arquitetura quer enunciar e simples de dizer e dificil de garantir: **o banco nao aceita conexao vinda da internet**. Toda a estrutura que segue existe para que essa frase deixe de ser um desejo e se torne consequencia direta do desenho.

O desenho do laboratorio tem quatro camadas organizadas da mais exposta para a mais interna:

```
        internet
            |
     +------+------+
     |    DMZ     |   balancer e servidores web
     +------+------+
            |
     +------+------+
     |  APLICACAO |   servidores de aplicacao, sem acesso direto
     +------+------+
            |
     +------+------+
     |   DADOS    |   banco. So a aplicacao chega aqui
     +------+------+
            |
     +------+------+
     |   GESTAO   |   bastion, o unico ponto de entrada humano
     +------+------+
```

Cada camada tem um papel e uma fronteira:

- **DMZ publica**: o unico lugar onde o trafego da internet é aceito, com `balancer-web`, `web-publico-01` e `web-publico-02` em `dmz-publica` (203.0.113.0/24).
- **Aplicacao privada**: `app-01` e `app-02` em `app-privada` (10.20.0.0/24). Nao aceitam conexao direta da internet; so recebem o que a DMZ entrega.
- **Dados privada**: o banco `banco-01` em `dados-privada` (10.30.0.0/24). Só chega trafego vindo da camada de aplicacao.
- **Gestao privada**: o bastion `bastion` em `gestao-privada` (10.10.0.0/24), o unico no com papel de aceitar conexao externa, ponto de entrada para administracao.

A ordem das camadas não é disposição espacial, é a própria segurança. Se qualquer camada pudesse ser contornada, a frase voltaria a ser desejo. O motor avalia milhares de combinacoes e mostra onde o desenho falha quando as camadas são ignoradas.

## Rota e regra sao mecanismos diferentes

Este e o ponto central do documento e o que a maioria dos materiais sobre seguranca em nuvem nao distingue com clareza: uma regra de firewall e uma rota resolvem perguntas diferentes. Uma regra diz o que é **permitido**; uma rota diz o que é **possível**.

Essa distincao tem consequência pratica direta. Um pacote que chega ao banco vindo da internet pode ser negado por uma regra, mas o problema que importa nao é esse. O problema real é o pacote que já atravessou a DMZ e a camada de aplicacao, ou o pacote de retorno de uma conexao legítima. Ele é validado por regras que o permitem na ida, e aí surge a pergunta: ele consegue voltar?

Se a sub-rede do destino não tem rota de volta, o pacote simplesmente desaparece. Sem rota, não há como responder, e a conexão nunca se estabelece. Na arquitetura do laboratorio, a `dados-privada` não tem rota para a internet (0.0.0.0/0). A única sub-rede com essa rota é a `dmz-publica`.

Isso torna o desenho auditável de um jeito que regras isoladas não tornam: o banco esta protegido duas vezes, uma pela ausencia de rota e outra por regra de firewall, e nenhuma das duas protecoes sozinha bastaria. Sem a regra, bastaria uma rota mal configurada para abrir caminho; sem a regra, a ausencia de rota so protege contra pacotes que a DMZ deixou passar, e uma regra permissiva poderia reabrir o acesso.

A auditabilidade vem justamente da separação de responsabilidade. O arquivo `arquitetura.yaml` contém a estrutura — sub-redes, nos, rotas — e responde à pergunta "o pacote pode ir e voltar". As regras contem a politica — entrada, saida, porta, estado — e respondem a "o trafego e permitido". Quando as duas camadas concordam, a decisao é robusta; quando discordam, o motor revela o conflito.

## Menor privilegio, aplicado ao desenho

Menor privilegio não é um principio abstrato. No desenho do laboratorio ele se traduz numa pergunta concreta: quem chega ate onde.

- O bastion é onde o acesso externo termina. O menor privilegio exige que qualquer conexao externa chegue por um único ponto, com identidade e historico controlados, em vez de espalhada pelas camadas. Aceitar acesso externo no banco, na camada de aplicacao ou na DMZ resolveria o problema de administacao localmente, mas ampliaria cada vez mais a superficie de ataque.
- A DMZ recebe o trafego da internet, mas só o seu papel exige, não sendo um caminho livre.
- A aplicacao só recebe o que a DMZ precisa entregar. Nem a internet, nem o banco conseguem chegar a ela por iniciativa propria.
- O banco só recebe o que a aplicacao precisa processar, e só na porta e protocolo da conexao de dados.

Administrar o banco diretamente, com SSH de uma faixa de operacoes, seria mais simples e errado. Um erro dessa regra colocaria os dados sensiveis expostos, sem camada intermediaria amortecendo o impacto. O bastion faz o caminho para o banco passar por um ponto visivel e controlado, revogavel de uma vez só.

## Ordem de avaliacao e o custo de reordenar

As regras são avaliadas de cima para baixo e a primeira que casa vence. Esse modelo é o mesmo das ACLs de rede e dos filtros de pacote tradicionais, e a consequência prática é que a ordem no arquivo de regras é parte da propria politica de seguranca, e nao um detalhe de organizacao.

A consequencia direta: duas regras que se contradizem nao sao um erro de sintaxe, são uma politica. Se a regra de "permitir" aparece antes da regra de "negar", o permitido vence e o negar nunca é atingido. Uma tabela bem intencionada, com a ordem errada, permite o que pretendia bloquear, e o motor mostra isso sem aviso: ele executa a politica como está escrita.

Por isso cada regra carrega um `motivo`. O motivo é a unica coisa que sobrevive quando a regra é movida de lugar. Sem motivo, a ordem do arquivo é um segredo guardado pelo arquivo; com motivo, o proximo leitor entende que aquela regra existe para nao bloquear o monitoramento, ou para manter compatibilidade, ou para restringir uma faixa que mudou. Mover uma regra sem ler o motivo dos outros é o passo que mais frequentemente destrói uma politica sem deixar registro do por que a mudança foi feita.

Ha tambem uma distincao entre regras de ida e de resposta que vale destacar. Uma conexao tem resposta, e a resposta nao passa por uma regra nova: ela volta pelo mesmo estado da conexao. Tratar a resposta como trafego novo é o erro clasico, com duas consequências ruins ao mesmo tempo: a resposta é bloqueada e a conexao permitida morre, e, para consertar, alguém adiciona uma regra de "retorno" que permite mais do que a intenção original. O campo de estado (`novo`, `relacionado`, `estabelecido`) existe para que o retorno seja reconhecido como parte de uma conexao ja autorizada, e não como uma nova discussao.

## O que o motor ensina e o desenho nao

É preciso dizer honestamente o que este laboratorio faz e o que não faz.

O laboratorio faz algo concreto e valioso: ele construiu um motor que avalia milhares de combinacoes de trafego contra um desenho completo, e mostra o resultado como um todo. Isso ensina a avaliar o desenho inteiro, nao regras isoladas. O perigo de revisar regras uma a uma é achar que cada uma esta correta e nao perceber que o conjunto permite o que nao permitia. Mover uma regra de lugar, mudar uma rota ou esquecer de validar a rede de retorno pode reabrir um acesso sem que nenhuma regra individual tenha sido modificada de forma suspeita. O motor torna visivel esse efeito de conjunto.

O laboratorio não mede o que importa em produção, e seria enganoso fingir o contrario. Neste ambiente:

- não ha ameaça real, só combinações de campos de pacote;
- nao ha ataque, só avaliações de permissao;
- nao ha tempo, só a ordem dos vetores de avaliacao;
- nao ha vazamento de dado, só o trajeto de um pacote ficticio.

Um modelo que nunca foi atacado mostra o desenho, nao o risco. O que ele comprova é coerencia interna: as regras sao consistentes com as rotas, as rotas sao consistentes com o que a arquitetura declarou, e a propriedade "o banco nao aceita conexao vinda da internet" se mantém quando o desenho é percorrido na integralidade.

Isso é um resultado honesto, e é o resultado mais proximo do que um motor como este pode entregar. A seguranca em producao envolve algo que nenhuma tabela de regras em um simulador consegue capturar: o adversario nao segue os campos de pacote do desenho, o tempo introduz configuracoes que mudaram sem registro, e um dado vaza mesmo quando todas as regras estao certas. Mas um desenho coerente e auditável nao é otimo demais para comecar; é o que permite que, quando o real chegar, seja possivel saber o que mudou e por que.
