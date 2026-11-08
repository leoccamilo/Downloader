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
  - Output: `C:/Downloader/data/output`
  - Enriched: `C:/Downloader/data/enriched`

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
2. `2_Parser_XML_parquet.ipynb`.
3. `3_Arquivos_Glob_parquet.ipynb`.
4. `4_MOs_Camilo.ipynb`, com a correção de Hotel de BTS pela célula física.
5. `5_MOs_TDD.ipynb`.
6. `6_MOs_5G.ipynb`.
7. Se selecionado, `cellref_LTE_v2.ipynb` e `CellRef_5G_v3.ipynb`.
8. Reaplicação dos passos 4 e 5 com o novo cellref, antes da publicação.

Os notebooks são lidos de `C:/Users/leocc/Novos_Audits`, sem alteração dos
originais. As regras de relatórios continuam nesses arquivos; o Downloader
executa suas células Python, sem precisar abrir o Jupyter. As referências
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

Para usar os caminhos da Claro, escolha as pastas de referências, notebooks,
saídas e histórico desejadas e desmarque **Transferir relatórios para a pasta
Vivo** e **Incluir geração dos cellrefs Vivo no Run All**. O destino Vivo fica desabilitado e não é exigido nem utilizado na
publicação. As pastas e a opção de transferência ficam salvas no navegador.
O padrão das referências continua `C:/Camilo`. A geração usa os notebooks
Vivo indicados; alterar pastas não converte suas regras para outra operadora.

Os arquivos processados atuais ficam em **Output Directory** e os relatórios
atuais, sem o sufixo semanal, em **Enriched Files Directory**. Desmarcar o
histórico não impede os arquivos semanais temporários necessários aos joins;
apenas impede sua publicação no destino de histórico. Desmarcar a transferência
Vivo impede a publicação no destino Vivo. **Run Parser** executa as etapas 2–6
nos ZIP/XML selecionados, sem novo acesso ao ENM. Desmarcar a rotina completa
mantém disponível o parser direto XML → TXT e os enriquecimentos anteriores.

Cada execução trabalha em uma pasta nova `.weekly_runs/<execução>`, ao lado
da pasta de saída, e grava um `manifest.json` com os hashes dos notebooks,
semana, avisos e arquivos publicados. As referências e relatórios existentes
não são usados como resultados intermediários. Os destinos só são atualizados
depois que todos os notebooks terminam com sucesso. A substituição de cada
arquivo é atômica; uma falha de disco durante a publicação é registrada no
manifesto com a lista dos arquivos já publicados. Os XML/Parquets temporários
são removidos após sucesso, preservando os MOs necessários à reaplicação em
`Output Directory/.refresh_inputs` (EUtranCellTDD, GUtranFreqRelation,
CapacityState e TermPointToENB). Resultados intermediários e manifestos permanecem
disponíveis para conferência. Em caso de falha, a pasta de trabalho é mantida.
Não há agendamento automático.

O executor adapta diferenças de execução fora do Jupyter: remove `%%time` e
pré-visualizações, importa `numpy` explicitamente, fixa a semana durante a
execução e redireciona os caminhos antigos para a pasta isolada. Também trata
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
continuam externos e configuráveis. Para usar alterações no código sem
recompilar o executável, inicie por `START_DOWNLOADER.bat`.

## Geração e atualização dos cellrefs

O acesso ao portal continua manual, pois exige token. Coloque os XLSX baixados
em `C:/Cellref/LTE_dump` e `C:/Cellref/NR_dump` ou selecione outras pastas na
aba **Cellrefs**. O cabeçalho esperado fica na terceira linha. Pastas com
semanas misturadas, inclusive entre LTE e NR quando identificadas no nome, são
rejeitadas. Mantenha apenas os arquivos da execução desejada.

Os notebooks são lidos de `C:/Cellref/scripts`, sem alteração dos originais:
LTE **v2** e 5G **v3**, incluindo suas regras de Hotel de BTS, co-setor e azimute.
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

Os dois arquivos operacionais são publicados diretamente na pasta única
selecionada: `cellref.xlsx` e `cellref_5g.xlsx`. As fotografias cadastrais
datadas ficam em `history/LTE` e `history/NR` dentro dela, com os nomes dos
notebooks. A lista de sites é reconstruída apenas dos dois arquivos oficiais;
arquivos históricos e SCIENCE não entram nessa reconstrução. A importação
manual de listas permanece como alternativa.

Execuções isoladas desta aba ficam em `.cellref_runs/<execução>`, ao lado da
pasta Output Directory. O manifesto registra a execução; `cellrefs/generation.json`
registra entradas, hashes dos notebooks e cobertura das coordenadas. Ausência
de coordenadas é informada no log. Nenhum cellref ou relatório é publicado se
a geração ou a reaplicação física falhar. As opções de histórico semanal e
transferência Vivo da aba ENM Dump continuam sendo respeitadas.
