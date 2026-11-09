# Downloader

ENM dump + XML parsing + enrichment tool with a local web UI.

## Main Components
- `server_downloader.py`: local backend/API used by the web app.
- `web-tool/`: frontend (`index.html`, `app.js`, `styles.css`).
- `dump_multiple_enms.py`: Execute Dump workflow for multiple ENMs.
- `xml_to_txt.py`: XML parser — reads `.zip`/`.xml`/`.xml.gz` dumps (ZIPs in place, no extraction) and writes one TXT per MO.
- `post_process_4_camilo.py`, `post_process_5_tdd.py`, `post_process_6_5g.py`: enrichment steps.
- `START_DOWNLOADER.bat` / `START_DOWNLOADER_HIDDEN.vbs`: app launchers.

## Setup
1. Create and activate a Python 3 environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Optional (ENM client scripting wheel):
   - `pip install enm_client_scripting-1.22.2-py2.py3-none-any.whl`

## Run
- Visible mode: `START_DOWNLOADER.bat`
- Hidden mode: `START_DOWNLOADER_HIDDEN.vbs`

## Default Folders
- Site list base dir (default): `C:/Downloader/cellref`
- Parser pipeline:
  - Input: ZIP/XML files picked in the XML Parser card (Run All uses the dump output folder)
  - Raw TXT: `C:/Dumps/todos_enms`
  - Processed MOs: `C:/Dumps/LTE_Total`
  - Reports: `C:/Camilo`

## Notes
- Runtime/generated files are ignored by Git.
- Change history is maintained in `alteracoes.md`.

## Rotina de segunda-feira

Abra `START_DOWNLOADER.bat`, configure os ENMs e o escopo e clique em **Run All**.
Na seção XML Parser, deixe marcada **Rotina completa dos notebooks (2 a 6)**.
Na aba **Cellrefs**, informe as pastas de downloads e deixe marcada **Incluir
geração dos cellrefs Vivo no Run All** para encadear a geração.
O Downloader verifica as dependências e referências antes de iniciar o dump,
acrescenta à seleção os MOs usados pelos notebooks (inclusive os MOs externos
necessários aos TermPoints) e executa:

1. Extração ENM por `dump_multiple_enms.py`, usando as conexões e o escopo da interface.
2. Parser direto XML/ZIP → TXT (`xml_to_txt.py`), junto dos dumps, sem Parquet.
3. `3_Arquivos_Glob_parquet.ipynb`.
4. `4_MOs_Camilo.ipynb`, com a correção de Hotel de BTS pela célula física.
5. `5_MOs_TDD.ipynb`.
6. `6_MOs_5G.ipynb`.
7. Se selecionado, `cellref_LTE_v2.ipynb` e `CellRef_5G_v3.ipynb`.
8. Reaplicação dos passos 4 e 5 com o novo cellref, antes da publicação.

Os scripts da rotina semanal, dos cellrefs e dos audits fazem parte do
Downloader, em `bundled_scripts`, incluído no empacotamento. Os notebooks
internos não contêm resultados de execuções anteriores. A interface não solicita
pastas de código e a API usa as cópias internas, inclusive com configurações
antigas. Os arquivos originais permanecem inalterados. As referências
`cellref.xlsx` e `cellref_5g.xlsx` ficam na **pasta única das referências**, no
primeiro cartão da aba ENM Dump (Referências 4G / 5G e lista de sites), com
padrão `C:/Camilo`. O parser e a aba Cellrefs usam essa mesma seleção.
`SCIENCE.xlsx` é opcional: se ausente, os campos de site são derivados do
cellref LTE. A reaplicação física usa uma referência de sites derivada do
cellref recém-gerado, preservando o arquivo SCIENCE existente. O ambiente Python dos subprocessos precisa das
dependências de `requirements.txt`, incluindo `pyarrow`.

As opções de saída são independentes e ficam salvas no navegador:

- **Criar arquivos semanais**: grava em `C:/Camilo` os mesmos nomes com
  `_número da semana` dos notebooks. A conta continua sendo `%U + 1` (não ISO).
  Rodar novamente na mesma semana atualiza os mesmos arquivos; a numeração
  também se repete no ano seguinte, como nos notebooks. Para separar anos,
  selecione uma pasta de histórico por ano.
- **Transferir relatórios para a pasta Vivo**: grava os relatórios definidos
  pelos notebooks em `C:/Vivo Reports`, preservando `LTE/LTE MOs`, `5G/5G MOs`
  e `MoB_IMP`, incluindo `MOs_5G_W<semana>.xlsx`.

Após o processamento completo e após a geração isolada dos cellrefs, a opção
de transferência Vivo também atualiza automaticamente `cellref.xlsx`,
`cellref_5g.xlsx` e `EUtranCell_TDD_FDD.csv` em `MoB_IMP`, usando as versões
finais das pastas de referências e relatórios. Os outros arquivos exportados
pelos notebooks para `MoB_IMP` continuam sendo gravados normalmente.
O mesmo `EUtranCell_TDD_FDD.csv` também é atualizado em `LTE/LTE MOs`.

Para usar os caminhos da Claro, escolha as pastas de referências, notebooks,
saídas e histórico desejadas e desmarque **Transferir relatórios para a pasta
Vivo** e **Incluir geração dos cellrefs Vivo no Run All**. O destino Vivo fica desabilitado e não é exigido nem utilizado na
publicação. As pastas e a opção de transferência ficam salvas no navegador.
O padrão das referências continua `C:/Camilo`. A geração usa os notebooks
Vivo indicados; alterar pastas não converte suas regras para outra operadora.

Os padrões da tela e dos perfis antigos são migrados para a rotina semanal:
BARA, BARB e CTPB selecionados; CTPA desmarcado. A seleção dos ENMs fica salva
nos perfis e ao reabrir a página. As credenciais e os caminhos personalizados
são preservados; somente os caminhos antigos conhecidos são substituídos.

Sem seleção manual, **Run Parser** lê todos os ZIP/XML da pasta de entrada.
A conversão lê os ZIPs diretamente e grava os TXT brutos por MO em
`C:/Dumps/todos_enms`. Os MOs tratados seguem para `C:/Dumps/LTE_Total` e os
relatórios para `C:/Camilo`, preservando os nomes originais dos notebooks.
A limpeza completa da pasta continua acontecendo somente ao iniciar um dump.

O fluxo padrão não cria `.weekly_runs`, `.cellref_runs`, cópias dos XMLs nem
caches Parquet. O registro `downloader_manifest.json` fica junto dos dumps.
Os notebooks 3 a 6 consomem TXT por um adaptador, sem alterar os originais.
Uma falha pode deixar relatórios de etapas anteriores já atualizados, como
no processo manual; consulte o log antes de continuar.

Ao desmarcar o histórico ou a exportação Vivo, somente os relatórios necessários
aos cálculos usam uma pasta temporária do sistema, removida ao final, sem copiar
os dumps. Configurações antigas de API sem `raw_txt_dir` ainda usam o executor
anterior por compatibilidade. Não há agendamento automático.

O executor adapta diferenças de execução fora do Jupyter: remove `%%time` e
pré-visualizações, importa `numpy` explicitamente, fixa a semana durante a
execução e redireciona os caminhos para as pastas configuradas. Também trata
as variantes de maiúsculas/minúsculas dos IDs, colunas opcionais ausentes e
operações de regex incompatíveis com Arrow. Colunas com ao menos um valor
preenchido são conservadas em recortes pequenos (os notebooks usam um mínimo
de 10 ou 100). Identificadores obrigatórios ausentes geram erro; atributos opcionais
ausentes são mantidos vazios com aviso. Sem TDD no escopo, o inventário é
gerado com FDD. As relações NR sem linhas no escopo são informadas como
ignoradas. Erros que os notebooks apenas imprimiam passam a interromper o job.
Nas células de `SignalingRadioBearer` e `CarrierAggregationFunction`, o executor
salva o `df2` calculado para o MO; o original salvava o `df3` de uma célula
anterior, produzindo um relatório de outro MO. Os notebooks originais permanecem
inalterados.

O servidor aceita um fluxo por vez. Uma falha de ENM ou de notebook impede o
avanço para a etapa seguinte e não deve ser exibida como conclusão com sucesso.
Ao cancelar/desconectar, os subprocessos são encerrados quando o servidor
detecta a interrupção do stream. A cópia do dump deve ter uma pasta própria:
a verificação impede selecionar uma pasta cuja limpeza apagaria o código,
os notebooks, referências ou destinos de relatórios.

Validação local: `venv/Scripts/python.exe -m unittest discover -s tests -v`.
O build Nuitka inclui `weekly_workflow.py` e `cellref_workflow.py`; os notebooks e as referências
agora fazem parte do aplicativo; as referências continuam configuráveis. Para usar alterações no código sem
recompilar o executável, inicie por `START_DOWNLOADER.bat`.

## Audits

A aba **Audits** executa os notebooks e scripts Python cadastrados em `audit_workflow.py`,
na ordem apresentada, sem alterar os arquivos originais. Use **Verificar entradas**,
selecione os audits e clique em **Executar selecionados**. O log identifica o
notebook e a célula em execução. A seleção é validada antes do primeiro audit;
uma falha durante a execução interrompe os seguintes. Relatórios de audits já
concluídos permanecem atualizados. Cancelar encerra o subprocesso ao desconectar
o stream, mas não desfaz arquivos que o notebook já gravou.

São usados os caminhos originais em `C:/Camilo`, `C:/Dumps/LTE_Total`,
`C:/Dumps/todos_enms`, `C:/Vivo Reports` e, nos dois relatórios previstos pelo
PSCell Change, `C:/Camilao`. Não são criadas pastas `.weekly_runs` ou
`.cellref_runs` para os audits. O botão **Run All** continua com seu fluxo atual;
os audits são executados separadamente nesta aba.

**Sites Novos** compara os históricos existentes e atualiza também
`C:/Vivo Reports/Historico Ativação/Historico_Ativação.xlsx`. O histórico é
reconstruído uma única vez, sem acrescentar a semana atual novamente, e linhas
exatamente duplicadas são removidas. **PSCell ENDC**
precisa do MO bruto `GNBCUUPFunction` em `C:/Dumps/todos_enms`: aceita os
Parquets originais ou `GNBCUUPFunction.txt`, sem gerar Parquet intermediário.
A ausência desse MO aparece como entrada pendente. O audit de distância exige
`haversine`, incluído em `requirements.txt`.

O **PSCell Change** divide os relatórios que ultrapassam o limite de Excel
em abas numeradas, com até 1.048.575 linhas de dados por aba mais o cabeçalho.
O nome do arquivo e as colunas são preservados. A exportação grande usa escrita
sequencial para limitar o consumo de memória. O botão de execução exibe a
quantidade de audits selecionados; disponibilidade de entradas não significa
que todos estejam selecionados ou que já tenham sido executados.

Também estão cadastrados os seis audits de `C:/cellref/scripts`:
`Audit_sCellCandidate.ipynb`, `Missing_EUtranFreqRelation_4G_4G.ipynb`,
`Missing_Neighbor_4G_4G.py`, `Audit_Nearest_NRPCI.py`, `NRPCI_Planning.py` e
`Audit_NRPCI_Neighbor.py`. Selecionar Planning inclui Nearest automaticamente,
antes do planejamento, mantendo os parâmetros padrão dos scripts. O Missing
Neighbor municipal mantém o limite exclusivo de 30%. O NRPCI Neighbor em
Python e o notebook anterior usam o mesmo destino; executar ambos atualiza
esse relatório duas vezes. Os arquivos originais não são modificados.

## Geração e atualização dos cellrefs

O acesso ao portal continua manual, pois exige token. Coloque os XLSX baixados
em `C:/Cellref/LTE_dump` e `C:/Cellref/NR_dump` ou selecione outras pastas na
aba **Cellrefs**. O cabeçalho esperado fica na terceira linha. Pastas com
semanas misturadas, inclusive entre LTE e NR quando identificadas no nome, são
rejeitadas. Mantenha apenas os arquivos da execução desejada.

Os geradores integrados são LTE **v2** e 5G **v3**, incluindo suas regras
de Hotel de BTS, co-setor e azimute.
A geração necessita dos parâmetros ENM, não apenas dos arquivos do portal:
EUtranCell_TDD_FDD, GNBDUFunction, NRCellDU, NRSectorCarrier e SectorCarrier.
SectorCarrier vem da pasta dos MOs processados, independentemente da opção
de transferência Vivo. No Run All, os parâmetros são os recém-gerados.

Para atualizar somente os cellrefs, use **Gerar cellrefs e atualizar** na nova
aba e selecione a pasta dos relatórios ENM existentes. Deixe **Reaplicar os
passos 4 e 5** marcada para atualizar também os relatórios físicos sem repetir
o dump ou o parser XML. São usados os MOs da pasta Output Directory e os
parâmetros brutos retidos pelo Run All. O escopo do inventário deve ser
compatível com os MOs. Se há TDD no inventário e faltam seus dados brutos,
a operação para e solicita uma execução completa, evitando perder as células TDD.

Os cellrefs oficiais e datados ficam nas pastas originais `C:/Cellref/LTE`
e `C:/Cellref/NR`. Os oficiais `cellref.xlsx` e `cellref_5g.xlsx` também são
atualizados na pasta única de referências. A lista de sites é reconstruída apenas dos dois arquivos oficiais;
arquivos históricos e SCIENCE não entram nessa reconstrução. A importação
manual de listas permanece como alternativa.

A aba Cellrefs também usa as pastas originais, sem `.cellref_runs`. Para reaplicar
os passos 4 e 5, os TXT brutos precisam estar disponíveis; se houver TDD no
inventário, seu TXT bruto é obrigatório. Ausência de coordenadas aparece no log.
As opções de histórico semanal e transferência Vivo continuam sendo respeitadas.

O audit PSCell Change usa as regras do PSCell do MoB Tool Box, incorporadas
ao notebook do Downloader em 09/11/2026, com `site_key_mode=cell`.
Os pares são formados pelo site físico da célula; a classificação normaliza
os setores; GUtranFreqRelation é associada por UF, eNB, célula e frequência.
Sem identificação da célula no arquivo de frequência, a execução falha.
Os três relatórios comuns incluem Distance em km, usando as coordenadas LTE
e o complemento do cellref 5G. Coordenadas ausentes deixam Distance vazio.
O audit não aplica corte de distância: no MoB esse corte pertence à geração
de comandos. Os dois relatórios adicionais do notebook continuam disponíveis.
O relatório 5G → 4G preserva também os identificadores configurados de External
e cellLocalId, sem reduzir os candidatos do MoB. Excel acima do limite é
dividido em abas; consumidores precisam ler todas as abas.
O código está embutido e não depende da instalação do MoB. Os hashes das
fontes de referência estão no manifest dos scripts.
Para repetir a comparação dos cálculos sobre os dados atuais, execute
`venv\Scripts\python.exe tests\validate_pscell_against_mob.py` na raiz do
Downloader. A validação intercepta as exportações, usa arquivos temporários e
não atualiza relatórios de produção. A serialização Excel é testada separadamente.
