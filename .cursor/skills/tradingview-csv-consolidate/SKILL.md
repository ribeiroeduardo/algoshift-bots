---
name: tradingview-csv-consolidate
description: >-
  Lê todos os CSV numa pasta de importação TradingView (incluindo o consolidado
  atual para preservar histórico), funde linhas com colunas alinhadas, remove
  duplicados tratando números como iguais após arredondamento (exportações
  sobrepostas diferem só na precisão), grava consolidado ordenado por Time (mais
  recente primeiro) e move para histórico só os CSVs novos (não o consolidado).
  Opção --dedupe-in-place para corrigir um CSV já consolidado. Usar quando o
  utilizador pedir consolidação TradingView, dedupe de balance history ou arquivo.
---

# Consolidação de CSVs TradingView

## Caminhos predefinidos (este utilizador)

| Função | Caminho |
|--------|---------|
| Importação (origem) | `/Users/eduardoribeiro/Library/CloudStorage/GoogleDrive-edunius@gmail.com/Meu Drive/Trades/Import TradingView` |
| Histórico (arquivo) | `/Users/eduardoribeiro/Library/CloudStorage/GoogleDrive-edunius@gmail.com/Meu Drive/Trades/Histórico` |

## Comportamento

1. **Entrada**: todos os `*.csv` na pasta de importação, **incluindo** `consolidado-tradingview.csv` quando existir, para fundir o histórico já consolidado com exportações novas (evita perder trades anteriores).
2. **Colunas**: união das colunas de todos os ficheiros; ordem = primeira ocorrência, colunas novas nos ficheiros seguintes são acrescentadas ao fim.
3. **Unicidade**: chave por coluna na ordem final: `Time` e texto (ex.: `Action`, moeda) com trim; células que são **só número** são comparadas após arredondamento (`Decimal`, default **8** casas — com 10 casas, P&L quase iguais ainda podiam ser tratados como linhas diferentes). Mantém-se a **primeira** ocorrência. Para afinar: `--round-decimals N`.
4. **Saída**: `consolidado-tradingview.csv` na **mesma** pasta de importação, encoding `utf-8-sig`, linhas ordenadas por **`Time` do mais recente ao mais antigo**.
5. **Arquivo**: cada CSV de entrada **exceto** `consolidado-tradingview.csv` é **movido** para a pasta Histórico (o consolidado permanece na pasta de importação e é só regravado). Se já existir um ficheiro com o mesmo nome no histórico, acrescenta-se sufixo `_1`, `_2`, etc.

## Execução

Na raiz do repositório Algoshift:

```bash
python3 .cursor/skills/tradingview-csv-consolidate/scripts/consolidate_tradingview_csvs.py
```

Primeira vez ou para validar sem alterar ficheiros:

```bash
python3 .cursor/skills/tradingview-csv-consolidate/scripts/consolidate_tradingview_csvs.py --dry-run
```

Outras pastas (opcional):

```bash
python3 .cursor/skills/tradingview-csv-consolidate/scripts/consolidate_tradingview_csvs.py --source-dir "/caminho/import" --archive-dir "/caminho/historico"
```

Só deduplicar um ficheiro já existente (ex.: consolidado com duplicados por precisão), sem mover nada:

```bash
python3 .cursor/skills/tradingview-csv-consolidate/scripts/consolidate_tradingview_csvs.py --dedupe-in-place "/caminho/consolidado-tradingview.csv"
```

Ajustar o arredondamento na comparação numérica (raro): `--round-decimals 8`.

## Instruções para o agente

1. Se o utilizador só quiser ver o plano, correr com `--dry-run` e resumir contagens.
2. Se pedir execução real, correr **sem** `--dry-run` e confirmar que a pasta Histórico foi criada se não existia.
3. Não apagar manualmente o `consolidado-tradingview.csv` da pasta de importação salvo pedido explícito; ele entra no merge como histórico e não é movido para o histórico.
4. Se algum CSV estiver aberto noutra app (Excel, Drive), o move pode falhar — reportar o erro e sugerir fechar o ficheiro.

## Ficheiros

- Script: [scripts/consolidate_tradingview_csvs.py](scripts/consolidate_tradingview_csvs.py)
