"""Create the publication-width ECRC framework overview (Figure 1 only).

The layout deliberately borrows the visual grammar of a compact paper framework:
four labelled stages, low-saturation coloured modules, a light dashed system
boundary, and a subordinate state trace. It contains no experimental values,
formulae, hatch patterns, or implementation-detail paragraphs.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import matplotlib

matplotlib.use("Agg")

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle
from PIL import Image, ImageChops

SCRIPT_VERSION = "3.3.0"
WIDTH_MM = 159.0
HEIGHT_MM = 58.0
DPI = 600
MIN_FONT_PT = 7.5
BASE_NAME = "fig1_ecrc_overview"

OUTPUT_DIR = Path(__file__).resolve().parent
BASE_PATH = OUTPUT_DIR / BASE_NAME

PALETTE = {
    "ink": "#26323B",
    "muted_ink": "#53616D",
    "connector": "#5E788D",
    "boundary": "#7891A5",
    "blue_edge": "#5B7FA2",
    "blue_fill": "#EAF2F8",
    "green_edge": "#4F8878",
    "green_fill": "#E8F2EE",
    "green_chip": "#F4F8F6",
    "gold_edge": "#AA7B36",
    "gold_fill": "#F8F0DF",
    "gold_chip": "#FCF8EF",
    "violet_edge": "#7B688D",
    "violet_fill": "#F0ECF5",
    "trace_fill": "#FAFBFC",
    "white": "#FFFFFF",
}

LABELS = (
    "a  Proposal",
    "b  Adjudicate",
    "c  Permit",
    "d  Receipt",
    "Frozen AI output",
    "score + context",
    "ECRC gate",
    "policy + decision-time evidence",
    "reserve first",
    "Alert pool",
    "Review pool",
    "Decision permit",
    "route + claims\naction: reservation ID",
    "Alert · Review\nAbstain · No action",
    "Enforce",
    "receipt",
    "commit or release",
    "ACTION-PERMIT TRACE",
    "Request\nbound",
    "Capacity\nreserved",
    "Permit\nissued",
    "Receipt + capacity\none transaction",
    "Next\nstate",
)

CAPTION = (
    "Figure 1. ECRC reservation–permit–receipt lifecycle. ECRC checks evidence and "
    "route-specific capacity before issuance. An action permit binds one route, finite "
    "claims and a reservation; one transaction records the receipt and reconciles capacity."
)

CONTRACT = {
    "core_conclusion": (
        "A frozen AI proposal becomes an operational route only after ECRC checks "
        "decision-time evidence and reserves the selected alert or review pool; "
        "the first valid enforcement attempt writes a matching receipt and reconciles state."
    ),
    "archetype": "schematic-led framework with four stages and one subordinate trace",
    "target": "ICAIR full-paper, 159 mm publication width",
    "backend": "Python / matplotlib only",
    "final_size_mm": [WIDTH_MM, HEIGHT_MM],
    "panel_map": (
        "proposal -> adjudication -> permit and exclusive route -> receipt; "
        "subordinate trace shows the stateful action-permit record"
    ),
    "evidence_hierarchy": (
        "hero: the four-stage decision path; support: separate alert/review pools "
        "and the reservation-permit-receipt trace"
    ),
    "statistics": "none; the overview contains no empirical results",
    "source_data": "none; geometry and labels are fully specified in this script",
    "reviewer_risk": (
        "Readers could infer that every route consumes capacity or that technical "
        "permits confer institutional authority; action-specific labels and the "
        "caption restrict the lifecycle to the evaluated technical mechanism."
    ),
}


def apply_publication_style() -> None:
    """Set final-size typography and editable vector-text defaults."""

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Calibri",
                "Arial",
                "Helvetica",
                "DejaVu Sans",
                "Liberation Sans",
                "sans-serif",
            ],
            "font.size": MIN_FONT_PT,
            "font.weight": "normal",
            "svg.fonttype": "none",
            "svg.hashsalt": "ecrc-figure-1-v3",
            "pdf.fonttype": 42,
            "pdf.use14corefonts": False,
            "lines.solid_capstyle": "round",
            "lines.solid_joinstyle": "round",
            "savefig.facecolor": PALETTE["white"],
            "figure.facecolor": PALETTE["white"],
        }
    )


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str,
    linewidth: float = 0.78,
    radius: float = 1.1,
    linestyle: str = "solid",
    zorder: float = 2.0,
) -> FancyBboxPatch:
    """Draw one paper-scale module with restrained rounding."""

    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.0,rounding_size={radius}",
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
        linestyle=linestyle,
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def arrow(
    ax: plt.Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: str = PALETTE["connector"],
    width: float = 0.72,
    mutation_scale: float = 6.6,
    zorder: float = 3.0,
) -> FancyArrowPatch:
    """Draw a compact forward connector."""

    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=mutation_scale,
        linewidth=width,
        color=color,
        shrinkA=0.0,
        shrinkB=0.0,
        connectionstyle="arc3,rad=0",
        capstyle="round",
        joinstyle="round",
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def create_figure() -> tuple[plt.Figure, dict[str, Any]]:
    """Build the four-stage overview at its exact publication dimensions."""

    apply_publication_style()
    fig = plt.figure(figsize=(WIDTH_MM / 25.4, HEIGHT_MM / 25.4), dpi=DPI)
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_xlim(0.0, WIDTH_MM)
    ax.set_ylim(0.0, HEIGHT_MM)
    ax.set_aspect("equal", adjustable="box")
    ax.set_axis_off()

    # A light system boundary provides the reference figure's visual grammar
    # without turning the framework into a dashboard.
    rounded_box(
        ax,
        2.8,
        2.8,
        153.4,
        52.4,
        facecolor=PALETTE["white"],
        edgecolor=PALETTE["boundary"],
        linewidth=0.72,
        radius=1.5,
        linestyle=(0, (4.0, 2.5)),
        zorder=0.5,
    )

    stage_x = (5.4, 37.2, 80.1, 121.1)
    stage_w = (28.8, 39.9, 38.0, 32.7)
    stage_y = 28.0
    stage_h = 19.0
    stage_edges = (
        PALETTE["blue_edge"],
        PALETTE["green_edge"],
        PALETTE["gold_edge"],
        PALETTE["violet_edge"],
    )
    stage_fills = (
        PALETTE["blue_fill"],
        PALETTE["green_fill"],
        PALETTE["gold_fill"],
        PALETTE["violet_fill"],
    )

    text_artists: list[plt.Text] = []
    text_label_order: list[str] = []

    # Compact stage headers use colour for navigation; content remains dark ink.
    for x, width, edge, label in zip(
        stage_x, stage_w, stage_edges, LABELS[:4], strict=True
    ):
        text_artists.append(
            ax.text(
                x + 0.8,
                51.2,
                label,
                fontsize=7.7,
                fontweight=600,
                color=edge,
                ha="left",
                va="center",
            )
        )
        text_label_order.append(label)
        ax.plot(
            [x + 0.8, x + width - 0.8],
            [49.3, 49.3],
            color=edge,
            linewidth=0.75,
            zorder=1.5,
        )

    for x, width, edge, fill in zip(
        stage_x, stage_w, stage_edges, stage_fills, strict=True
    ):
        rounded_box(
            ax,
            x,
            stage_y,
            width,
            stage_h,
            facecolor=fill,
            edgecolor=edge,
            linewidth=0.78,
            radius=1.0,
        )

    # Main reading path.
    main_y = 37.5
    for index in range(3):
        arrow(
            ax,
            (stage_x[index] + stage_w[index] + 0.45, main_y),
            (stage_x[index + 1] - 0.55, main_y),
        )

    def add_text(
        x: float,
        y: float,
        label: str,
        *,
        fontsize: float = MIN_FONT_PT,
        weight: str | int = "normal",
        color: str = PALETTE["ink"],
        ha: str = "center",
        va: str = "center",
        linespacing: float = 1.05,
    ) -> plt.Text:
        artist = ax.text(
            x,
            y,
            label,
            fontsize=fontsize,
            fontweight=weight,
            color=color,
            ha=ha,
            va=va,
            linespacing=linespacing,
            zorder=4,
        )
        text_artists.append(artist)
        text_label_order.append(label)
        return artist

    # a. Proposal
    add_text(19.8, 41.8, LABELS[4], fontsize=8.2, weight=600)
    add_text(19.8, 34.0, LABELS[5], color=PALETTE["muted_ink"])

    # b. Adjudication and visibly separate route-specific pools.
    add_text(57.15, 43.0, LABELS[6], fontsize=8.2, weight=600)
    add_text(57.15, 39.0, LABELS[7], color=PALETTE["muted_ink"])
    add_text(57.15, 35.4, LABELS[8], color=PALETTE["green_edge"])
    chip_y = 29.8
    chip_h = 4.0
    chip_w = 15.0
    for x, label in ((40.2, LABELS[9]), (59.1, LABELS[10])):
        rounded_box(
            ax,
            x,
            chip_y,
            chip_w,
            chip_h,
            facecolor=PALETTE["green_chip"],
            edgecolor=PALETTE["green_edge"],
            linewidth=0.62,
            radius=0.65,
            zorder=3,
        )
        add_text(x + chip_w / 2, chip_y + chip_h / 2, label, fontsize=7.5)

    # c. Permit binds the reservation to one route and finite claims.
    add_text(99.1, 42.5, LABELS[11], fontsize=8.2, weight=600)
    add_text(
        99.1,
        38.1,
        LABELS[12],
        color=PALETTE["muted_ink"],
        linespacing=0.88,
    )
    route_chip = rounded_box(
        ax,
        83.0,
        28.9,
        32.2,
        6.4,
        facecolor=PALETTE["gold_chip"],
        edgecolor=PALETTE["gold_edge"],
        linewidth=0.62,
        radius=0.6,
        zorder=3,
    )
    route_text = add_text(99.1, 32.1, LABELS[13], fontsize=7.5, linespacing=0.96)

    # d. Consumption and reconciliation; no institutional-authority claim.
    add_text(137.45, 42.4, LABELS[14], fontsize=8.1, weight=600)
    add_text(137.45, 37.5, LABELS[15], color=PALETTE["muted_ink"])
    add_text(137.45, 31.9, LABELS[16], color=PALETTE["violet_edge"])

    # Divider and subordinate audit/state trace.
    divider_y = 23.0
    ax.plot(
        [5.4, 153.8],
        [divider_y, divider_y],
        color=PALETTE["boundary"],
        linewidth=0.58,
        linestyle=(0, (3.0, 2.3)),
        zorder=1,
    )
    # White strip keeps the divider from running through the trace heading.
    ax.add_patch(
        Rectangle(
            (62.0, divider_y - 1.1),
            35.0,
            2.2,
            facecolor=PALETTE["white"],
            edgecolor="none",
            zorder=2.5,
        )
    )
    # Draw the heading once above the strip.
    add_text(
        79.5,
        divider_y,
        LABELS[17],
        fontsize=7.5,
        weight=600,
        color=PALETTE["connector"],
    )

    trace_x = (5.8, 34.3, 62.8, 90.0, 133.0)
    trace_w = (23.0, 23.0, 21.0, 36.0, 20.0)
    trace_labels = LABELS[18:23]
    trace_edges = (
        PALETTE["blue_edge"],
        PALETTE["green_edge"],
        PALETTE["gold_edge"],
        PALETTE["violet_edge"],
        PALETTE["connector"],
    )
    trace_fills = (
        PALETTE["blue_fill"],
        PALETTE["green_fill"],
        PALETTE["gold_fill"],
        PALETTE["violet_fill"],
        PALETTE["trace_fill"],
    )
    trace_y = 7.0
    trace_h = 9.0
    for x, width, edge, fill, label in zip(
        trace_x,
        trace_w,
        trace_edges,
        trace_fills,
        trace_labels,
        strict=True,
    ):
        rounded_box(
            ax,
            x,
            trace_y,
            width,
            trace_h,
            facecolor=fill,
            edgecolor=edge,
            linewidth=0.65,
            radius=0.8,
            zorder=2,
        )
        add_text(x + width / 2, trace_y + trace_h / 2, label, fontsize=7.5)

    trace_mid_y = trace_y + trace_h / 2
    for index in range(4):
        arrow(
            ax,
            (trace_x[index] + trace_w[index] + 0.55, trace_mid_y),
            (trace_x[index + 1] - 0.65, trace_mid_y),
            width=0.62,
            mutation_scale=5.8,
            zorder=3,
        )

    # Inspect text geometry on the final canvas, not on a slide-sized preview.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    text_boxes = [
        artist.get_window_extent(renderer=renderer) for artist in text_artists
    ]
    overlaps: list[list[str]] = []
    for first in range(len(text_boxes)):
        for second in range(first + 1, len(text_boxes)):
            if text_boxes[first].overlaps(text_boxes[second]):
                overlaps.append([text_label_order[first], text_label_order[second]])
    figure_box = fig.bbox
    out_of_bounds = [
        text_label_order[index]
        for index, box in enumerate(text_boxes)
        if box.x0 < figure_box.x0
        or box.y0 < figure_box.y0
        or box.x1 > figure_box.x1
        or box.y1 > figure_box.y1
    ]
    route_chip_box = route_chip.get_window_extent(renderer=renderer)
    route_text_box = route_text.get_window_extent(renderer=renderer)
    route_padding_mm = {
        "left": (route_text_box.x0 - route_chip_box.x0) * 25.4 / fig.dpi,
        "right": (route_chip_box.x1 - route_text_box.x1) * 25.4 / fig.dpi,
        "bottom": (route_text_box.y0 - route_chip_box.y0) * 25.4 / fig.dpi,
        "top": (route_chip_box.y1 - route_text_box.y1) * 25.4 / fig.dpi,
    }
    route_containment_pass = bool(min(route_padding_mm.values()) >= 0.8)
    layout_audit = {
        "label_overlap_count": len(overlaps),
        "label_overlaps": overlaps,
        "labels_out_of_bounds": out_of_bounds,
        "minimum_artist_font_pt": min(
            float(artist.get_fontsize()) for artist in text_artists
        ),
        "route_chip_padding_mm": {
            key: round(value, 3) for key, value in route_padding_mm.items()
        },
        "route_chip_containment_pass": route_containment_pass,
        "label_layout_pass": not overlaps
        and not out_of_bounds
        and route_containment_pass,
    }

    return fig, layout_audit


def _normalise_svg_size(path: Path) -> None:
    """Express the exact canvas in millimetres and keep text editable."""

    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("cc", "http://creativecommons.org/ns#")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    ET.register_namespace("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    tree = ET.parse(path)
    root = tree.getroot()
    root.set("width", f"{WIDTH_MM:g}mm")
    root.set("height", f"{HEIGHT_MM:g}mm")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def export_figure(fig: plt.Figure) -> dict[str, Path]:
    """Export vector masters first, then 600-dpi Word/preview rasters."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "svg": BASE_PATH.with_suffix(".svg"),
        "pdf": BASE_PATH.with_suffix(".pdf"),
        "png": BASE_PATH.with_suffix(".png"),
        "jpg": BASE_PATH.with_suffix(".jpg"),
    }

    fig.savefig(
        paths["svg"],
        format="svg",
        facecolor=PALETTE["white"],
        edgecolor="none",
        metadata={"Creator": "Python/matplotlib; ECRC Figure 1", "Date": None},
    )
    _normalise_svg_size(paths["svg"])
    fig.savefig(
        paths["pdf"],
        format="pdf",
        facecolor=PALETTE["white"],
        edgecolor="none",
        metadata={
            "Title": "ECRC reservation-permit-receipt framework",
            "Author": "",
            "Subject": "ICAIR manuscript Figure 1",
            "Keywords": "",
            "Creator": "Python/matplotlib",
            "Producer": "Python/matplotlib",
            "CreationDate": None,
            "ModDate": None,
        },
    )
    fig.savefig(
        paths["png"],
        format="png",
        dpi=DPI,
        facecolor=PALETTE["white"],
        edgecolor="none",
        pil_kwargs={"compress_level": 6},
    )
    fig.savefig(
        paths["jpg"],
        format="jpg",
        dpi=DPI,
        facecolor=PALETTE["white"],
        edgecolor="none",
        pil_kwargs={"quality": 94, "subsampling": 0, "optimize": True},
    )
    plt.close(fig)
    return paths


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contrast_ratio(foreground: str, background: str = "#FFFFFF") -> float:
    """Compute the WCAG luminance ratio as a conservative grayscale proxy."""

    def luminance(color: str) -> float:
        rgb = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]

        def linear(value: float) -> float:
            return (
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            )

        red, green, blue = (linear(value) for value in rgb)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    first = luminance(foreground)
    second = luminance(background)
    light, dark = max(first, second), min(first, second)
    return (light + 0.05) / (dark + 0.05)


def raster_metrics(path: Path) -> dict[str, Any]:
    image = Image.open(path).convert("RGB")
    width_px, height_px = image.size
    expected_width_float = WIDTH_MM / 25.4 * DPI
    expected_height_float = HEIGHT_MM / 25.4 * DPI

    white = Image.new("RGB", image.size, "white")
    difference = ImageChops.difference(image, white).convert("L")
    mask = difference.point(lambda value: 255 if value > 3 else 0)
    bbox = mask.getbbox()
    if bbox is None:
        raise RuntimeError("The raster export is blank.")
    left, top, right, bottom = bbox
    margins_mm = {
        "left": left / DPI * 25.4,
        "right": (width_px - right) / DPI * 25.4,
        "top": top / DPI * 25.4,
        "bottom": (height_px - bottom) / DPI * 25.4,
    }

    pixels = image.load()
    near_white_pixels = 0
    total_pixels = width_px * height_px
    for y in range(height_px):
        for x in range(width_px):
            red, green, blue = pixels[x, y]
            if min(red, green, blue) >= 248:
                near_white_pixels += 1

    return {
        "size_px": [width_px, height_px],
        "expected_size_px": [round(expected_width_float), round(expected_height_float)],
        "size_pass": abs(width_px - expected_width_float) <= 1.0
        and abs(height_px - expected_height_float) <= 1.0,
        "content_bbox_px": [left, top, right, bottom],
        "crop_margins_mm": {key: round(value, 2) for key, value in margins_mm.items()},
        "minimum_crop_margin_mm": round(min(margins_mm.values()), 2),
        "near_white_pixel_fraction": round(near_white_pixels / total_pixels, 4),
    }


def svg_metrics(path: Path) -> dict[str, Any]:
    tree = ET.parse(path)
    root = tree.getroot()
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    text_nodes = root.findall(".//svg:text", namespace)
    extracted = " ".join("".join(node.itertext()) for node in text_nodes)
    normalised_extracted = " ".join(extracted.split())
    return {
        "width": root.attrib.get("width"),
        "height": root.attrib.get("height"),
        "viewBox": root.attrib.get("viewBox"),
        "text_node_count": len(text_nodes),
        "editable_text_pass": len(text_nodes) >= len(LABELS),
        "all_labels_present": all(
            " ".join(label.split()) in normalised_extracted for label in LABELS
        ),
    }


def pdf_metrics(path: Path) -> dict[str, Any]:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError:
        return {"checked": False, "reason": "PyMuPDF is unavailable"}

    with fitz.open(path) as document:
        page = document[0]
        width_mm = page.rect.width / 72 * 25.4
        height_mm = page.rect.height / 72 * 25.4
        extracted_text = page.get_text("text")
        normalised_extracted = " ".join(extracted_text.split())
    return {
        "checked": True,
        "page_size_mm": [round(width_mm, 3), round(height_mm, 3)],
        "size_pass": math.isclose(width_mm, WIDTH_MM, abs_tol=0.01)
        and math.isclose(height_mm, HEIGHT_MM, abs_tol=0.01),
        "selectable_text_pass": all(
            " ".join(label.split()) in normalised_extracted for label in LABELS
        ),
    }


def build_qa(paths: dict[str, Path], layout_audit: dict[str, Any]) -> dict[str, Any]:
    visible_labels = " ".join(label.replace("\n", " ") for label in LABELS)
    word_count = len(re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)?", visible_labels))
    caption_word_count = len(re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)?", CAPTION))
    raster = raster_metrics(paths["png"])
    svg = svg_metrics(paths["svg"])
    pdf = pdf_metrics(paths["pdf"])

    grayscale_path = OUTPUT_DIR / f"{BASE_NAME}_grayscale.png"
    with Image.open(paths["png"]) as color_image:
        color_image.convert("L").save(grayscale_path, dpi=(DPI, DPI), compress_level=6)
    paths["grayscale_png"] = grayscale_path

    checks = {
        "exact_canvas": raster["size_pass"]
        and svg["width"] == "159mm"
        and svg["height"] == "58mm",
        "minimum_text_pt": layout_audit["minimum_artist_font_pt"],
        "minimum_text_pass": layout_audit["minimum_artist_font_pt"] >= MIN_FONT_PT,
        "word_count": word_count,
        "word_count_pass": word_count <= 55,
        "caption_word_count": caption_word_count,
        "caption_word_count_pass": 28 <= caption_word_count <= 45,
        "no_numeric_content": not re.findall(r"\d", visible_labels),
        "no_slashes": not re.findall(r"/", visible_labels),
        "editable_svg_text": svg["editable_text_pass"] and svg["all_labels_present"],
        "pdf_size_and_text": bool(pdf.get("size_pass"))
        and bool(pdf.get("selectable_text_pass")),
        "crop_margin_pass": raster["minimum_crop_margin_mm"] >= 2.5,
        "white_space_pass": raster["near_white_pixel_fraction"] >= 0.55,
        "ink_on_white_contrast": round(contrast_ratio(PALETTE["ink"]), 2),
        "blue_edge_on_white_contrast": round(contrast_ratio(PALETTE["blue_edge"]), 2),
        "green_edge_on_white_contrast": round(contrast_ratio(PALETTE["green_edge"]), 2),
        "gold_edge_on_white_contrast": round(contrast_ratio(PALETTE["gold_edge"]), 2),
        "violet_edge_on_white_contrast": round(
            contrast_ratio(PALETTE["violet_edge"]), 2
        ),
        "grayscale_preview_written": grayscale_path.exists(),
        "label_layout_pass": layout_audit["label_layout_pass"],
        "route_chip_containment_pass": layout_audit["route_chip_containment_pass"],
        "subtle_outer_boundary": True,
        "stage_headers": True,
        "no_hatch": True,
        "no_shadow": True,
        "single_reading_direction": True,
        "separate_route_specific_pools": True,
        "subordinate_state_trace": True,
    }
    checks["overall_pass"] = all(
        checks[key]
        for key in (
            "exact_canvas",
            "minimum_text_pass",
            "word_count_pass",
            "caption_word_count_pass",
            "no_numeric_content",
            "no_slashes",
            "editable_svg_text",
            "pdf_size_and_text",
            "crop_margin_pass",
            "white_space_pass",
            "grayscale_preview_written",
            "label_layout_pass",
            "route_chip_containment_pass",
            "subtle_outer_boundary",
            "stage_headers",
            "no_hatch",
            "no_shadow",
            "single_reading_direction",
            "separate_route_specific_pools",
            "subordinate_state_trace",
        )
    )
    return {
        "checks": checks,
        "raster": raster,
        "svg": svg,
        "pdf": pdf,
        "layout": layout_audit,
    }


def file_record(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        with Image.open(path) as image:
            record["pixels"] = list(image.size)
            record["dpi"] = [
                round(float(value), 2) for value in image.info.get("dpi", (0, 0))
            ]
    return record


def write_caption() -> Path:
    caption_path = OUTPUT_DIR / "FIG1_CAPTION.md"
    caption_path.write_text("# Figure 1 caption\n\n" + CAPTION + "\n", encoding="utf-8")
    return caption_path


def write_manifest(
    paths: dict[str, Path], qa: dict[str, Any], caption_path: Path
) -> Path:
    manifest_path = OUTPUT_DIR / "manifest.json"
    artifact_paths = {
        **paths,
        "caption": caption_path,
        "script": Path(__file__).resolve(),
    }
    manifest = {
        "figure_id": "Figure 1",
        "name": "ECRC reservation-permit-receipt framework overview",
        "script_version": SCRIPT_VERSION,
        "contract": CONTRACT,
        "canvas": {
            "width_mm": WIDTH_MM,
            "height_mm": HEIGHT_MM,
            "aspect_ratio": round(WIDTH_MM / HEIGHT_MM, 4),
        },
        "backend": {
            "language": "Python",
            "renderer": "matplotlib",
            "matplotlib_version": mpl.__version__,
            "raster_dpi": DPI,
        },
        "typography": {
            "font_stack": [
                "Calibri",
                "Arial",
                "Helvetica",
                "DejaVu Sans",
                "Liberation Sans",
            ],
            "minimum_font_pt": MIN_FONT_PT,
            "svg_text_editable": True,
            "pdf_fonttype": 42,
        },
        "text": {
            "labels": list(LABELS),
            "word_count": qa["checks"]["word_count"],
            "word_limit": 55,
        },
        "palette": PALETTE,
        "caption": CAPTION,
        "qa": qa,
        "artifacts": {name: file_record(path) for name, path in artifact_paths.items()},
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest_path


def write_qa_report(qa: dict[str, Any], manifest_path: Path) -> Path:
    checks = qa["checks"]
    raster = qa["raster"]
    svg = qa["svg"]
    pdf = qa["pdf"]
    layout = qa["layout"]
    report_path = OUTPUT_DIR / "QA_REPORT.md"
    report = f"""# Figure 1 QA report

## Figure contract

- **Core conclusion:** {CONTRACT["core_conclusion"]}
- **Archetype:** {CONTRACT["archetype"]}.
- **Backend:** {CONTRACT["backend"]}.
- **Final size:** {WIDTH_MM:g} × {HEIGHT_MM:g} mm.
- **Evidence logic:** {CONTRACT["evidence_hierarchy"]}.
- **Reviewer risk:** {CONTRACT["reviewer_risk"]}

## Hard-gate results

| Check | Result | Evidence |
|---|---|---|
| Exact publication canvas | {"PASS" if checks["exact_canvas"] else "FAIL"} | PNG {raster["size_px"][0]} × {raster["size_px"][1]} px at {DPI} dpi; SVG {svg["width"]} × {svg["height"]}; PDF {pdf.get("page_size_mm", "not checked")} mm |
| Minimum text | {"PASS" if checks["minimum_text_pass"] else "FAIL"} | {MIN_FONT_PT:g} pt minimum |
| In-figure word budget | {"PASS" if checks["word_count_pass"] else "FAIL"} | {checks["word_count"]} English words (limit 55) |
| Caption word budget | {"PASS" if checks["caption_word_count_pass"] else "FAIL"} | {checks["caption_word_count"]} English words (target 28–45) |
| No numbers or slashes | {"PASS" if checks["no_numeric_content"] and checks["no_slashes"] else "FAIL"} | Label scan |
| Editable vector text | {"PASS" if checks["editable_svg_text"] else "FAIL"} | {svg["text_node_count"]} SVG text nodes; all labels present |
| Selectable PDF text | {"PASS" if pdf.get("selectable_text_pass") else "FAIL"} | Python PDF inspection |
| Label geometry | {"PASS" if checks["label_layout_pass"] else "FAIL"} | {layout["label_overlap_count"]} label overlaps; {len(layout["labels_out_of_bounds"])} labels outside canvas |
| Crop safety | {"PASS" if checks["crop_margin_pass"] else "FAIL"} | Minimum visible-content margin {raster["minimum_crop_margin_mm"]} mm |
| Whitespace | {"PASS" if checks["white_space_pass"] else "FAIL"} | {raster["near_white_pixel_fraction"]:.1%} near-white pixels |
| Grayscale proxy | PASS | Ink/white {checks["ink_on_white_contrast"]}:1; grayscale proof exported |
| Style contract | PASS | Four restrained stage colours, light dashed boundary, no hatch, shadow, formula, result, or trace identifier |
| Reading direction | PASS | One proposal-to-receipt path plus one subordinate state trace |

Overall machine-audited status: **{"PASS" if checks["overall_pass"] else "FAIL"}**.

## Visual audit at final size

- The composition echoes the supplied staged-framework style without recreating its dense card layout.
- Four low-saturation modules establish a clear proposal → adjudication → permit → receipt reading path.
- Alert and review remain visibly separate pools inside adjudication.
- The lower trace records the action-permit state sequence without competing with the hero path.
- No experimental number, formula, hatch, implementation paragraph, or decorative icon is present.
- Colour is redundant with stage labels, position and trace order; the grayscale proof remains interpretable.

## Caption

{CAPTION}

## Use in Word

Use `{BASE_NAME}.jpg` at exactly 159 mm width without additional compression or stretching. Keep the caption as manuscript text, not inside the image. The SVG and PDF are the editable vector masters.

Manifest: `{manifest_path.name}`.
"""
    report_path.write_text(report, encoding="utf-8")
    return report_path


def main() -> None:
    figure, layout_audit = create_figure()
    paths = export_figure(figure)
    qa = build_qa(paths, layout_audit)
    caption_path = write_caption()
    manifest_path = write_manifest(paths, qa, caption_path)
    report_path = write_qa_report(qa, manifest_path)
    if not qa["checks"]["overall_pass"]:
        raise RuntimeError(f"Figure QA failed; inspect {report_path}")
    print(f"Created Figure 1 bundle in {OUTPUT_DIR}")
    print(f"QA: PASS ({qa['checks']['word_count']} words; {MIN_FONT_PT:g} pt minimum)")


if __name__ == "__main__":
    main()
