# DXF Pipeline (Cabine Primária Blindada)

Script em Python para auditar e exportar o DXF grande `02 - CABINE PIMÁRIA BLINDADA.dxf` (AC1032) localizado na raiz do projeto. Gera relatórios (JSON/CSV), previews (PDF/PNG/SVG) e DXF flatten, com opção de ajustar INSUNITS e tentar exportar DWG (ODA File Converter).

## Requisitos
- macOS (testado em M1/arm64) ou equivalente com Python 3.10+.
- Dependências: `ezdxf`, `pymupdf`, `matplotlib`, `pillow`, `rich`. Todas estão em `requirements.txt`.
- Para exportar DWG: ODA File Converter instalado e acessível no PATH (ou nos caminhos padrão do macOS listados abaixo).

## Instalação (macOS/M1)
```bash
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

## Uso básico
```bash
source .venv/bin/activate
python3 dxf_pipeline.py \
  --input "02 - CABINE PIMÁRIA BLINDADA.dxf" \
  --outdir out
```

Saídas (padrão em `./out`):
- `summary.json`
- `entities_by_type.csv`
- `entities_by_layer.csv`
- `blocks_by_insert.csv`
- `preview_modelspace.pdf` (e `png`; `svg` opcional)
- `flattened.dxf`
- `cleaned_units_fix.dxf` (se usar `--set-insunits`)
- `exported.dwg` (se `--export-dwg` e ODA disponível)

## Flags principais
- `--pdf / --no-pdf` (default: exporta)
- `--png / --no-png` (default: exporta)
- `--svg` (desativado por padrão)
- `--dpi 300`
- `--page {A0|A1|A2|A3|A4}` e `--orientation {auto|portrait|landscape}`
- `--margins-mm 10`
- `--fit-page / --no-fit-page` (default: on). `--scale` desativa o fit automático.
- `--export-flattened-dxf / --no-export-flattened-dxf` (default: on)
- `--export-dwg` (tenta usar ODA)
- `--set-insunits <int>` (grava cópia com $INSUNITS ajustado)
- `--label <nome>` (rótulo para compor o diretório de saída)
- `--timestamped-outdir` (anexa `YYYYmmdd_HHMMSS` ao diretório de saída)

Exemplos:
```bash
# Apenas relatórios + PNG, sem PDF/SVG
python3 dxf_pipeline.py --no-pdf --png --no-svg

# Ajustar INSUNITS para mm (4) e gerar tudo em um diretório customizado
python3 dxf_pipeline.py --set-insunits 4 --outdir "./out/mm_fix"

# Forçar escala 1:100 em A1 paisagem, sem fit automático
python3 dxf_pipeline.py --scale 0.01 --page A1 --orientation landscape --no-fit-page

# Gerar saídas com carimbo de data/hora e rótulo
python3 dxf_pipeline.py --label "versao_teste" --timestamped-outdir
```

## ODA File Converter (opcional, para DWG)
1. Instale o ODA File Converter (graficamente no macOS ou via pacote oficial).
2. Deixe o binário disponível em um destes caminhos ou no PATH:
   - `/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter`
   - `/usr/local/bin/ODAFileConverter`
   - `/opt/ODAFileConverter/ODAFileConverter`
3. Rode com `--export-dwg`. Se não encontrado, o script apenas emitirá aviso.

## Observações técnicas
- O script tenta `recover` e roda `audit`; logs exibem contagens de erros.
- Bounding box: tenta `bbox` do modelspace; se falhar, usa `$EXTMIN/$EXTMAX`.
- Heurística de alerta: se `$INSUNITS==1` (inches) e a extensão X ou Y > 5000, um WARNING é emitido (provável desenho em mm). Nenhuma escala automática é aplicada.
- Export de previews prioriza PyMuPDF (pymupdf); se indisponível, cai para `matplotlib.qsave` com fundo branco e linhas pretas.
