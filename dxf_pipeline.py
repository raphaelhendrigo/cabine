#!/usr/bin/env python3
"""
Pipeline para análise e exportação de um DXF grande (AC1032).

Gera relatórios (JSON/CSV), previews (PDF/PNG/SVG) e DXF flatten.
Opcionalmente ajusta INSUNITS e tenta converter para DWG se o ODA File Converter estiver instalado.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
import sys
from datetime import datetime
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import ezdxf
from ezdxf.audit import Auditor
from ezdxf.bbox import extents as bbox_extents
from ezdxf.document import Drawing
from ezdxf.layouts import Modelspace

try:
    from rich.logging import RichHandler
except ImportError:  # pragma: no cover - opcional
    RichHandler = None


LOGGER = logging.getLogger("dxf-pipeline")
ISO_SIZES_MM: Dict[str, Tuple[int, int]] = {
    "A0": (841, 1189),
    "A1": (594, 841),
    "A2": (420, 594),
    "A3": (297, 420),
    "A4": (210, 297),
}
DEFAULT_INPUT = Path(__file__).resolve().parent / "02 - CABINE PIMÁRIA BLINDADA.dxf"


@dataclass
class PreviewOptions:
    pdf: bool
    png: bool
    svg: bool
    dpi: int
    page: str
    orientation: str
    margins_mm: float
    fit_page: bool
    scale: Optional[float]


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers = None
    if RichHandler is not None:
        handlers = [RichHandler(rich_tracebacks=True)]
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=handlers,
    )


def load_doc(path: Path) -> Tuple[Drawing, Optional[Auditor]]:
    LOGGER.info("Carregando DXF (recover/audit): %s", path)
    try:
        doc, auditor = ezdxf.recover(str(path))
    except Exception:
        LOGGER.warning("Recover falhou, tentando leitura direta...")
        doc = ezdxf.readfile(str(path))
        auditor = None
    if auditor:
        if auditor.errors:
            LOGGER.warning("Recover encontrou %d problemas", len(auditor.errors))
        else:
            LOGGER.info("Recover sem erros reportados.")
    try:
        audit = doc.audit()
        if audit.errors:
            LOGGER.warning("Auditoria detectou %d problemas adicionais", len(audit.errors))
    except Exception as exc:  # pragma: no cover - diagnóstico
        LOGGER.warning("Auditoria falhou: %s", exc)
    return doc, auditor


def safe_header_value(doc: Drawing, key: str, default=None):
    try:
        return doc.header.get(key, default)
    except Exception:
        return default


def compute_extents(doc: Drawing, msp: Modelspace) -> Dict:
    extmin: Optional[Tuple[float, float, float]] = None
    extmax: Optional[Tuple[float, float, float]] = None
    source = "modelspace_bbox"
    try:
        box = bbox_extents(msp, fast=True)
        if box.has_data:
            extmin = tuple(float(v) for v in box.extmin)
            extmax = tuple(float(v) for v in box.extmax)
    except Exception as exc:
        LOGGER.warning("Falha ao calcular bounding box pelo modelspace: %s", exc)
    if extmin is None or extmax is None:
        source = "header_EXTMIN_EXTMAX"
        extmin = safe_header_value(doc, "$EXTMIN")
        extmax = safe_header_value(doc, "$EXTMAX")
        if extmin is not None:
            extmin = tuple(float(v) for v in extmin)
        if extmax is not None:
            extmax = tuple(float(v) for v in extmax)
    size: Optional[Tuple[float, float, float]] = None
    if extmin is not None and extmax is not None:
        size = (
            extmax[0] - extmin[0],
            extmax[1] - extmin[1],
            extmax[2] - extmin[2],
        )
    return {"source": source, "extmin": extmin, "extmax": extmax, "size": size}


def compute_stats(doc: Drawing) -> Dict:
    msp = doc.modelspace()
    entity_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    block_insert_counts: Counter[str] = Counter()

    for entity in msp:
        dxftype = entity.dxftype()
        entity_counts[dxftype] += 1
        layer_counts[entity.dxf.layer] += 1
        if dxftype == "INSERT":
            block_insert_counts[entity.dxf.name] += 1

    extents = compute_extents(doc, msp)
    insunits = int(safe_header_value(doc, "$INSUNITS", 0) or 0)
    width = extents["size"][0] if extents.get("size") else None
    height = extents["size"][1] if extents.get("size") else None
    if insunits == 1 and ((width and width > 5000) or (height and height > 5000)):
        LOGGER.warning(
            "INSUNITS==1 (inches) mas a extensão é muito grande (%.2f x %.2f). "
            "Provavelmente o desenho está em mm.",
            width or -1,
            height or -1,
        )

    total_entities = sum(entity_counts.values())
    layers = sorted(layer.dxf.name for layer in doc.layers)
    blocks = sorted(block.name for block in doc.blocks)
    blocks_with_counts = {name: block_insert_counts.get(name, 0) for name in blocks}

    return {
        "dxfversion": doc.dxfversion,
        "handseed": safe_header_value(doc, "$HANDSEED", ""),
        "insunits": insunits,
        "extents": extents,
        "total_entities_modelspace": total_entities,
        "entity_counts": dict(entity_counts),
        "layer_counts": dict(layer_counts),
        "layers": layers,
        "blocks": blocks,
        "insert_counts_by_block": blocks_with_counts,
    }


def write_reports(stats: Dict, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    summary_path = outdir / "summary.json"
    summary_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    LOGGER.info("Resumo salvo em %s", summary_path)

    def write_csv(data: Dict[str, int], path: Path, headers: Tuple[str, str]) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for key, value in sorted(data.items(), key=lambda kv: kv[0]):
                writer.writerow([key, value])
        LOGGER.info("CSV salvo em %s", path)

    write_csv(stats["entity_counts"], outdir / "entities_by_type.csv", ("type", "count"))
    write_csv(stats["layer_counts"], outdir / "entities_by_layer.csv", ("layer", "count"))
    write_csv(
        stats["insert_counts_by_block"],
        outdir / "blocks_by_insert.csv",
        ("block", "insert_count"),
    )


def resolve_page_size(page: str, orientation: str, bbox_size: Optional[Tuple[float, float, float]]) -> Tuple[float, float]:
    base_size = ISO_SIZES_MM.get(page.upper())
    if not base_size:
        raise ValueError(f"Tamanho de página inválido: {page}")
    w_mm, h_mm = base_size
    if orientation == "auto" and bbox_size:
        orientation = "landscape" if bbox_size[0] >= bbox_size[1] else "portrait"
    if orientation == "landscape":
        w_mm, h_mm = h_mm, w_mm
    return float(w_mm), float(h_mm)


def build_layout(page: str, orientation: str, margins_mm: float, bbox_size: Optional[Tuple[float, float, float]]) -> Tuple:
    from ezdxf.addons.drawing import layout as drawing_layout

    w_mm, h_mm = resolve_page_size(page, orientation, bbox_size)
    margins = drawing_layout.Margins(margins_mm, margins_mm, margins_mm, margins_mm)
    page_def = drawing_layout.Page(width=w_mm, height=h_mm, units=drawing_layout.Units.mm, margins=margins)
    return page_def, drawing_layout


def render_with_pymupdf(
    doc: Drawing,
    msp: Modelspace,
    outdir: Path,
    preview_opts: PreviewOptions,
    bbox_size: Optional[Tuple[float, float, float]],
) -> None:
    try:
        from ezdxf.addons.drawing import pymupdf
        from ezdxf.addons.drawing import config as drawing_config
        from ezdxf.addons.drawing import RenderContext, Frontend
    except ImportError as exc:
        raise RuntimeError(f"PyMuPDF/ezdxf drawing backend não disponível: {exc}") from exc

    page_def, drawing_layout = build_layout(
        preview_opts.page, preview_opts.orientation, preview_opts.margins_mm, bbox_size
    )
    settings = drawing_layout.Settings(
        fit_page=preview_opts.fit_page if preview_opts.scale is None else False,
        scale=preview_opts.scale or 1.0,
        crop_at_margins=True,
    )
    config = drawing_config.Configuration(
        color_policy=drawing_config.ColorPolicy.BLACK,
        background_policy=drawing_config.BackgroundPolicy.WHITE,
    )
    recorder = pymupdf.PyMuPdfBackend()
    ctx = RenderContext(doc)
    Frontend(ctx, recorder, config=config).draw_layout(msp, finalize=True)
    render = recorder.get_replay(page_def, settings=settings)
    render.set_background("#FFFFFF")

    if preview_opts.pdf:
        pdf_path = outdir / "preview_modelspace.pdf"
        pdf_path.write_bytes(render.get_pdf_bytes())
        LOGGER.info("PDF gerado em %s", pdf_path)
    if preview_opts.png:
        png_path = outdir / "preview_modelspace.png"
        render.get_pixmap(dpi=preview_opts.dpi, alpha=False).save(str(png_path))
        LOGGER.info("PNG gerado em %s", png_path)
    if preview_opts.svg:
        svg_path = outdir / "preview_modelspace.svg"
        svg_content = render.get_svg_image()
        svg_path.write_text(svg_content, encoding="utf-8")
        LOGGER.info("SVG gerado em %s", svg_path)


def render_with_matplotlib(
    doc: Drawing,
    msp: Modelspace,
    outdir: Path,
    preview_opts: PreviewOptions,
    bbox_size: Optional[Tuple[float, float, float]],
) -> None:
    try:
        from ezdxf.addons.drawing import matplotlib
        from ezdxf.addons.drawing import config as drawing_config
    except ImportError as exc:
        raise RuntimeError(f"Matplotlib backend não disponível: {exc}") from exc

    w_mm, h_mm = resolve_page_size(preview_opts.page, preview_opts.orientation, bbox_size)
    size_inches = (w_mm / 25.4, h_mm / 25.4)
    config = drawing_config.Configuration(
        color_policy=drawing_config.ColorPolicy.BLACK,
        background_policy=drawing_config.BackgroundPolicy.WHITE,
    )
    if preview_opts.pdf:
        pdf_path = outdir / "preview_modelspace.pdf"
        matplotlib.qsave(
            msp,
            str(pdf_path),
            bg="#FFFFFF",
            fg="#000000",
            dpi=preview_opts.dpi,
            size_inches=size_inches,
            config=config,
        )
        LOGGER.info("PDF (matplotlib) gerado em %s", pdf_path)
    if preview_opts.png:
        png_path = outdir / "preview_modelspace.png"
        matplotlib.qsave(
            msp,
            str(png_path),
            bg="#FFFFFF",
            fg="#000000",
            dpi=preview_opts.dpi,
            size_inches=size_inches,
            config=config,
        )
        LOGGER.info("PNG (matplotlib) gerado em %s", png_path)
    if preview_opts.svg:
        svg_path = outdir / "preview_modelspace.svg"
        matplotlib.qsave(
            msp,
            str(svg_path),
            bg="#FFFFFF",
            fg="#000000",
            dpi=preview_opts.dpi,
            size_inches=size_inches,
            config=config,
        )
        LOGGER.info("SVG (matplotlib) gerado em %s", svg_path)


def export_previews(
    doc: Drawing,
    msp: Modelspace,
    outdir: Path,
    preview_opts: PreviewOptions,
    bbox_size: Optional[Tuple[float, float, float]],
) -> None:
    if not (preview_opts.pdf or preview_opts.png or preview_opts.svg):
        LOGGER.info("Previews desativados.")
        return
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        render_with_pymupdf(doc, msp, outdir, preview_opts, bbox_size)
    except RuntimeError as exc:
        LOGGER.warning("%s; tentando fallback matplotlib...", exc)
        render_with_matplotlib(doc, msp, outdir, preview_opts, bbox_size)


def export_flattened_dxf(doc: Drawing, msp: Modelspace, outdir: Path) -> None:
    from ezdxf.addons.drawing import dxf as dxf_backend
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing import config as drawing_config

    outdir.mkdir(parents=True, exist_ok=True)
    out_doc = ezdxf.new(dxfversion=doc.dxfversion or "R2010")
    out_msp = out_doc.modelspace()
    config = drawing_config.Configuration(
        color_policy=drawing_config.ColorPolicy.BLACK,
        background_policy=drawing_config.BackgroundPolicy.WHITE,
    )
    backend = dxf_backend.DXFBackend(out_msp, color_mode=dxf_backend.ColorMode.RGB)
    ctx = RenderContext(doc)
    Frontend(ctx, backend, config=config).draw_layout(msp, finalize=True)
    flat_path = outdir / "flattened.dxf"
    out_doc.saveas(flat_path)
    LOGGER.info("DXF flattened salvo em %s", flat_path)


def export_units_fix(doc: Drawing, outdir: Path, insunits: int) -> None:
    fixed = doc.copy()
    fixed.header["$INSUNITS"] = insunits
    path = outdir / "cleaned_units_fix.dxf"
    fixed.saveas(path)
    LOGGER.info("DXF com INSUNITS ajustado (%s) salvo em %s", insunits, path)


def find_oda_converter() -> Optional[Path]:
    candidates = [
        Path("/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"),
        Path("/usr/local/bin/ODAFileConverter"),
        Path("/opt/ODAFileConverter/ODAFileConverter"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def export_dwg(input_dxf: Path, outdir: Path) -> None:
    converter = find_oda_converter()
    if not converter:
        LOGGER.warning(
            "ODA File Converter não encontrado. Instale e adicione ao PATH para habilitar exportação DWG."
        )
        return
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / "exported.dwg"
    # ODA CLI usa diretórios; usamos o diretório do arquivo como entrada e um filtro pelo nome.
    cmd = [
        str(converter),
        str(input_dxf.parent),
        str(outdir),
        input_dxf.name,
        "ACAD2018",
        "DWG",
        "0",  # recurse
        "1",  # audit
    ]
    LOGGER.info("Executando ODA File Converter: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if target.exists():
            LOGGER.info("DWG exportado em %s", target)
        else:
            LOGGER.warning("Conversão executada, mas %s não apareceu. Verifique o log do ODA.", target)
    except subprocess.CalledProcessError as exc:
        LOGGER.warning("ODA File Converter falhou: %s", exc)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline de análise e exportação de DXF.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Arquivo DXF de entrada.")
    parser.add_argument("--outdir", type=Path, default=Path("out"), help="Diretório de saída.")
    parser.add_argument("--label", type=str, default=None, help="Rótulo/nome para compor o diretório de saída.")
    parser.add_argument("--no-label", dest="label", action="store_const", const=None, help="Não usar rótulo (override).")
    parser.add_argument(
        "--timestamped-outdir",
        action="store_true",
        help="Anexa timestamp (YYYYmmdd_HHMMSS) ao diretório de saída.",
    )
    parser.add_argument(
        "--no-timestamped-outdir",
        action="store_false",
        dest="timestamped_outdir",
        help="Não anexar timestamp ao diretório de saída.",
    )
    parser.add_argument("--pdf", dest="pdf", action="store_true", help="Exportar PDF.")
    parser.add_argument("--no-pdf", dest="pdf", action="store_false", help="Não exportar PDF.")
    parser.add_argument("--png", dest="png", action="store_true", help="Exportar PNG.")
    parser.add_argument("--no-png", dest="png", action="store_false", help="Não exportar PNG.")
    parser.add_argument("--svg", dest="svg", action="store_true", help="Exportar SVG.")
    parser.add_argument("--no-svg", dest="svg", action="store_false", help="Não exportar SVG.")
    parser.add_argument("--dpi", type=int, default=300, help="DPI para PNG/PDF (default: 300).")
    parser.add_argument("--page", choices=list(ISO_SIZES_MM.keys()), default="A3", help="Tamanho da página.")
    parser.add_argument(
        "--orientation",
        choices=["auto", "portrait", "landscape"],
        default="auto",
        help="Orientação da página.",
    )
    parser.add_argument("--margins-mm", type=float, default=10.0, help="Margem em mm.")
    parser.add_argument("--fit-page", dest="fit_page", action="store_true", help="Ajustar conteúdo à página.")
    parser.add_argument("--no-fit-page", dest="fit_page", action="store_false", help="Desativar fit automático.")
    parser.add_argument("--scale", type=float, default=None, help="Escala fixa (desativa fit-page).")
    parser.add_argument(
        "--export-flattened-dxf",
        dest="export_flattened_dxf",
        action="store_true",
        help="Exportar DXF flatten (default: on).",
    )
    parser.add_argument(
        "--no-export-flattened-dxf",
        dest="export_flattened_dxf",
        action="store_false",
        help="Não exportar DXF flatten.",
    )
    parser.add_argument(
        "--export-dwg",
        dest="export_dwg",
        action="store_true",
        help="Tentar exportar DWG via ODA File Converter.",
    )
    parser.add_argument(
        "--set-insunits",
        type=int,
        default=None,
        help="Se definido, grava cópia do DXF com $INSUNITS ajustado.",
    )
    parser.add_argument("--verbose", action="store_true", help="Logs verbosos.")
    parser.set_defaults(pdf=True, png=True, svg=False, fit_page=True, export_flattened_dxf=True, export_dwg=False)
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)

    input_path = args.input
    if not input_path.exists():
        LOGGER.error("Arquivo de entrada não encontrado: %s", input_path)
        return 1
    outdir = args.outdir
    if args.label:
        outdir = outdir / args.label
    if args.timestamped_outdir:
        outdir = outdir / datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Usando diretório de saída: %s", outdir)

    doc, _ = load_doc(input_path)
    stats = compute_stats(doc)
    write_reports(stats, outdir)

    preview_opts = PreviewOptions(
        pdf=args.pdf,
        png=args.png,
        svg=args.svg,
        dpi=args.dpi,
        page=args.page,
        orientation=args.orientation,
        margins_mm=args.margins_mm,
        fit_page=args.fit_page,
        scale=args.scale,
    )
    bbox_size = stats["extents"].get("size")
    try:
        export_previews(doc, doc.modelspace(), outdir, preview_opts, bbox_size)
    except Exception as exc:
        LOGGER.error("Falha ao gerar previews: %s", exc)

    if args.export_flattened_dxf:
        try:
            export_flattened_dxf(doc, doc.modelspace(), outdir)
        except Exception as exc:
            LOGGER.error("Falha ao gerar DXF flattened: %s", exc)

    if args.set_insunits is not None:
        try:
            export_units_fix(doc, outdir, args.set_insunits)
        except Exception as exc:
            LOGGER.error("Falha ao salvar DXF com INSUNITS ajustado: %s", exc)

    if args.export_dwg:
        try:
            export_dwg(input_path, outdir)
        except Exception as exc:
            LOGGER.error("Falha ao tentar converter DWG: %s", exc)

    LOGGER.info("Pipeline finalizado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
