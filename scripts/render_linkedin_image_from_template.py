#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from lloyds_digest.utils import load_env_file


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def xyxy(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)


def _latest_linkedin_post(path: Path) -> Path | None:
    if not path.exists():
        return None
    candidates = sorted(path.glob("linkedin_post_*.txt"), reverse=True)
    return candidates[0] if candidates else None


def _resolve_template_path(template_arg: Path | None) -> Path:
    candidates = []
    if template_arg:
        candidates.append(template_arg)
    candidates.extend(
        [
            Path("docs/assets/linkedin_image_template.jpg"),
            Path("output/linkedin_images_compare/Lloyds_News_Digest_Image_Template.jpg"),
            Path("output/linkedin_images_compare/Lloyds_News_Digest_Image_Template.png"),
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    searched = ", ".join(str(p) for p in candidates)
    raise SystemExit(f"Template image not found. Checked: {searched}")


def _date_from_filename(path: Path) -> str | None:
    m = re.search(r"linkedin_post_(\d{4}-\d{2}-\d{2})\.txt$", path.name)
    return m.group(1) if m else None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _capitalize_first_letter(text: str) -> str:
    for idx, ch in enumerate(text):
        if ch.isalpha():
            return text[:idx] + ch.upper() + text[idx + 1 :]
    return text


def _extract_headline(lines: list[str]) -> str:
    for ln in lines:
        low = ln.lower()
        if ":" in ln and "signal" in low and not low.startswith(("why ", "read ", "full digest", "alt text", "banner alt text", "#")):
            return ln.split(":", 1)[1].strip() or ln.strip()
    return lines[0] if lines else ""


def _is_highlights_heading(low: str) -> bool:
    norm = low.strip().rstrip(":")
    if "highlight" in norm:
        return True
    return norm.startswith("heads-up")


def _is_highlight_item_line(line: str) -> bool:
    return bool(re.match(r"^(?:\d+\)|[-•])\s+", line))


def _strip_source_noise(text: str) -> str:
    t = " ".join(text.split())
    t = re.sub(r"\(\s*[^)]*(?:\.[^)]+|/[^)]*)\)", "", t)
    t = re.sub(r"\s+[—–-]\s*[A-Za-z0-9._/-]+\.[A-Za-z]{2,}[A-Za-z0-9._/-]*\.?\s*$", "", t)
    t = re.sub(r"\s+[—–-]\s*\(\s*[A-Za-z0-9._/-]+\.[A-Za-z]{2,}[A-Za-z0-9._/-]*\s*\)\.?\s*$", "", t)
    return t.strip(" -—–:;,.")


def _extract_digest_link(line: str) -> str:
    low = line.lower()
    if "digest" not in low and "read it here" not in low:
        return ""
    m = re.search(r"https?://\S+", line)
    if not m:
        return ""
    return m.group(0).rstrip(").,;")


def _split_highlight_text(text: str) -> tuple[str, str]:
    item = " ".join(text.split()).strip()
    if not item:
        return "", ""

    why_match = re.search(r"(?i)\bwhy(?:\s+it\s+matters)?\s*:\s*(.+)$", item)
    if why_match:
        return item[: why_match.start()].strip(" -—–:;,. "), why_match.group(1).strip()

    parts = re.split(r"\s+[—–-]\s+", item)
    if len(parts) >= 2:
        title = parts[0].strip()
        rest = " - ".join(parts[1:]).strip()
        if ":" in rest:
            _, detail = rest.split(":", 1)
            detail = detail.strip()
            if detail:
                return title, detail
        if re.fullmatch(r"\(?[A-Za-z0-9 ._/&-]*\.[A-Za-z]{2,}[^)]*\)?\.?", rest):
            return title, ""
        if len(rest) <= 48 and not re.search(r"[;,.]", rest):
            return title, ""
        return title, rest

    if ":" in item:
        left, right = item.split(":", 1)
        if right.strip() and 1 <= len(left.split()) <= 10:
            return left.strip(), right.strip()

    return item, ""


def _parse_post(post_text: str) -> dict:
    lines = [ln.strip() for ln in post_text.splitlines() if ln.strip()]

    headline = _extract_headline(lines)
    highlights: list[dict[str, str]] = []
    why = ""
    read_link = ""
    in_highlights = False
    pending_idx = -1

    for ln in lines:
        low = ln.lower().strip()

        link = _extract_digest_link(ln)
        if link and not read_link:
            read_link = link

        why_line = re.match(r"(?i)^why(?:\s+this|\s+it)?\s+matters\s*:\s*(.+)$", ln)
        if why_line:
            why_text = why_line.group(1).strip()
            why_text = re.sub(r"(?i)\bread\b.*https?://\S+", "", why_text).strip(" -—–")
            if in_highlights and pending_idx >= 0 and pending_idx < len(highlights) and not highlights[pending_idx].get("detail"):
                highlights[pending_idx]["detail"] = why_text
                pending_idx = -1
                continue
            why = why or why_text
            in_highlights = False
            pending_idx = -1
            continue

        if _is_highlights_heading(low):
            in_highlights = True
            pending_idx = -1
            continue

        if in_highlights and low.startswith(("full digest:", "read ", "#", "alt text:", "banner alt text:")):
            in_highlights = False
            pending_idx = -1
            continue

        if _is_highlight_item_line(ln):
            if not in_highlights:
                in_highlights = True
            item_text = re.sub(r"^(?:\d+\)|[-•])\s*", "", ln).strip()
            title, detail = _split_highlight_text(item_text)
            title = _strip_source_noise(title)
            highlights.append({"title": title or "Key update", "source": "", "detail": detail.strip()})
            pending_idx = len(highlights) - 1 if not detail.strip() else -1
            continue

        if in_highlights and pending_idx >= 0 and pending_idx < len(highlights):
            detail_match = re.match(r"(?i)^why(?:\s+it\s+matters)?\s*:\s*(.+)$", ln)
            if detail_match:
                highlights[pending_idx]["detail"] = detail_match.group(1).strip()
                pending_idx = -1
                continue
            if low.startswith(("read ", "full digest:", "#", "alt text:", "banner alt text:")):
                pending_idx = -1
                in_highlights = False
                continue

    return {
        "headline": headline,
        "highlights": highlights[:4],
        "why": why,
        "read_link": read_link,
    }


def _shorten(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    trimmed = text[: max_chars - 3]
    for sep in [". ", ", ", " - ", " "]:
        idx = trimmed.rfind(sep)
        if idx > max_chars // 2:
            trimmed = trimmed[:idx]
            break
    return trimmed.rstrip(" ,.-") + "..."


def _compact_copy(parsed: dict, run_date: str) -> dict:
    try:
        date_label = datetime.strptime(run_date, "%Y-%m-%d").strftime("%d-%b-%y")
    except ValueError:
        date_label = run_date

    highlights = list(parsed["highlights"])
    while len(highlights) < 4:
        highlights.append({"title": "", "source": "", "detail": ""})

    compact_cards = []
    for item in highlights[:4]:
        title = _shorten(item.get("title", "").strip() or "Key update", 48)
        detail = _shorten(item.get("detail", "").strip() or "No detail available.", 110)
        compact_cards.append({"title": title, "detail": _capitalize_first_letter(detail)})

    link = parsed.get("read_link", "").strip()
    link_display = link.replace("https://", "").replace("http://", "")
    link_display = _shorten(link_display, 88)

    return {
        "date": date_label,
        "headline": _shorten(parsed.get("headline", "").strip(), 130),
        "cards": compact_cards,
        "why": _shorten(parsed.get("why", "").strip(), 210),
        "link": link_display,
    }


def _find_logo_path() -> Path | None:
    candidates = [
        Path("docs/assets/logo.png"),
        Path("src/images/London_Lloyds_Market_News_Digest.png"),
        Path("output/London_Lloyds_Market_News_Digest.png"),
        Path("docs/digests/London_Lloyds_Market_News_Digest.png"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    bold_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    regular_candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in (bold_candidates if bold else regular_candidates):
        path = Path(p)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    out = [words[0]]
    for word in words[1:]:
        test = out[-1] + " " + word
        if draw.textlength(test, font=font) <= max_width:
            out[-1] = test
        else:
            out.append(word)
    return out


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: Box,
    *,
    bold: bool,
    max_size: int,
    min_size: int,
    max_lines: int,
    spacing: int,
) -> tuple[ImageFont.ImageFont, list[str]]:
    for size in range(max_size, min_size - 1, -1):
        font = _load_font(size, bold=bold)
        lines = _wrap_text(draw, text, font, box.w)
        if not lines:
            return font, []
        if len(lines) > max_lines:
            continue
        line_h = int(font.getbbox("Ag")[3] * 1.02)
        total_h = len(lines) * line_h + (len(lines) - 1) * spacing
        if total_h <= box.h:
            return font, lines
    font = _load_font(min_size, bold=bold)
    lines = _wrap_text(draw, text, font, box.w)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _shorten(lines[-1], max(8, len(lines[-1]) - 4))
    return font, lines


def _draw_panel(img: Image.Image, box: Box, fill: tuple[int, int, int, int], outline: tuple[int, int, int, int], radius: int) -> None:
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rounded_rectangle(box.xyxy, radius=radius, fill=fill, outline=outline, width=2)
    img.alpha_composite(ov)


def _draw_logo(img: Image.Image, logo_path: Path, box: Box) -> None:
    logo = Image.open(logo_path).convert("RGBA")
    gray = logo.convert("L")
    mask = gray.point(lambda p: 255 if p > 110 else 0)
    logo_bbox = mask.getbbox()
    if logo_bbox:
        logo = logo.crop(logo_bbox)
    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    logo.thumbnail((box.w, box.h), resample)
    x = box.x + max(0, (box.w - logo.width) // 2)
    y = box.y + max(0, (box.h - logo.height) // 2)
    img.alpha_composite(logo, (x, y))


def _draw_text_block(
    img: Image.Image,
    box: Box,
    text: str,
    *,
    bold: bool,
    max_size: int,
    min_size: int,
    max_lines: int,
    color: tuple[int, int, int],
    align: str = "left",
    spacing: int = 6,
    shadow: bool = True,
) -> None:
    draw = ImageDraw.Draw(img)
    font, lines = _fit_text(
        draw,
        text,
        box,
        bold=bold,
        max_size=max_size,
        min_size=min_size,
        max_lines=max_lines,
        spacing=spacing,
    )
    if not lines:
        return
    line_h = int(font.getbbox("Ag")[3] * 1.02)
    total_h = len(lines) * line_h + (len(lines) - 1) * spacing
    y = box.y + max(0, (box.h - total_h) // 2)
    for line in lines:
        if align == "center":
            tw = int(draw.textlength(line, font=font))
            x = box.x + max(0, (box.w - tw) // 2)
        else:
            x = box.x
        if shadow:
            draw.text((x + 1, y + 1), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=color)
        y += line_h + spacing


def _draw_text_lines(
    img: Image.Image,
    box: Box,
    lines: list[str],
    *,
    font: ImageFont.ImageFont,
    color: tuple[int, int, int],
    align: str = "left",
    spacing: int = 6,
    shadow: bool = True,
) -> None:
    if not lines:
        return
    draw = ImageDraw.Draw(img)
    line_h = int(font.getbbox("Ag")[3] * 1.02)
    total_h = len(lines) * line_h + (len(lines) - 1) * spacing
    y = box.y + max(0, (box.h - total_h) // 2)
    for line in lines:
        if align == "center":
            tw = int(draw.textlength(line, font=font))
            x = box.x + max(0, (box.w - tw) // 2)
        else:
            x = box.x
        if shadow:
            draw.text((x + 1, y + 1), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=color)
        y += line_h + spacing


def _fit_uniform_text_blocks(
    draw: ImageDraw.ImageDraw,
    texts: list[str],
    boxes: list[Box],
    *,
    bold: bool,
    max_size: int,
    min_size: int,
    max_lines: int,
    spacing: int,
) -> tuple[ImageFont.ImageFont, list[list[str]]]:
    for size in range(max_size, min_size - 1, -1):
        font = _load_font(size, bold=bold)
        fitted: list[list[str]] = []
        ok = True
        for text, box in zip(texts, boxes):
            lines = _wrap_text(draw, text, font, box.w)
            if len(lines) > max_lines:
                ok = False
                break
            if lines:
                line_h = int(font.getbbox("Ag")[3] * 1.02)
                total_h = len(lines) * line_h + (len(lines) - 1) * spacing
                if total_h > box.h:
                    ok = False
                    break
            fitted.append(lines)
        if ok:
            return font, fitted

    font = _load_font(min_size, bold=bold)
    fitted = []
    for text, box in zip(texts, boxes):
        lines = _wrap_text(draw, text, font, box.w)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = _shorten(lines[-1], max(8, len(lines[-1]) - 4))
        fitted.append(lines)
    return font, fitted


def _with_left_padding(box: Box, pad: int) -> Box:
    return Box(box.x + pad, box.y, max(1, box.w - pad), box.h)


def _derive_layout(w: int, h: int) -> dict[str, Box]:
    # Normalized placeholders based on existing reference composition.
    layout: dict[str, Box] = {
        "date": Box(int(w * 0.03), int(h * 0.03), int(w * 0.19), int(h * 0.055)),
        "headline": Box(int(w * 0.03), int(h * 0.09), int(w * 0.94), int(h * 0.16)),
        "logo": Box(int(w * 0.74), int(h * 0.01), int(w * 0.23), int(h * 0.08)),
        "label_left": Box(int(w * 0.03), int(h * 0.47), int(w * 0.21), int(h * 0.055)),
        "label_center": Box(int(w * 0.35), int(h * 0.465), int(w * 0.30), int(h * 0.065)),
        "why": Box(int(w * 0.022), int(h * 0.80), int(w * 0.95), int(h * 0.07)),
        "digest": Box(int(w * 0.022), int(h * 0.875), int(w * 0.95), int(h * 0.052)),
    }

    card_w = int(w * 0.205)
    card_h = int(h * 0.22)
    start_x = int(w * 0.022)
    y = int(h * 0.545)
    gap = int(w * 0.012)

    for i in range(4):
        cx = start_x + i * (card_w + gap)
        outer = Box(cx, y, card_w, card_h)
        layout[f"card_{i+1}_panel"] = outer
        layout[f"card_{i+1}_title"] = Box(cx + int(card_w * 0.055), y + int(card_h * 0.06), int(card_w * 0.89), int(card_h * 0.44))
        layout[f"card_{i+1}_detail"] = Box(cx + int(card_w * 0.055), y + int(card_h * 0.50), int(card_w * 0.89), int(card_h * 0.44))

    return layout


def _render_placeholder_map(template_path: Path, out_path: Path, layout: dict[str, Box]) -> None:
    img = Image.open(template_path).convert("RGBA")
    d = ImageDraw.Draw(img)
    for name, box in layout.items():
        if name.endswith("_panel"):
            continue
        d.rectangle(box.xyxy, outline=(255, 110, 20, 255), width=3)
        d.text((box.x + 3, box.y + 3), name, fill=(255, 240, 0, 255), font=_load_font(18, bold=True))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")


def render_image(template_path: Path, post_path: Path, out_path: Path) -> Path:
    raw = _parse_post(_read_text(post_path))
    run_date = _date_from_filename(post_path) or date.today().isoformat()
    copy = _compact_copy(raw, run_date)

    img = Image.open(template_path).convert("RGBA")
    w, h = img.size
    layout = _derive_layout(w, h)
    logo_path = _find_logo_path()
    headline_text_box = _with_left_padding(layout["headline"], int(w * 0.012))
    why_text_box = _with_left_padding(layout["why"], int(w * 0.012))
    digest_text_box = _with_left_padding(layout["digest"], int(w * 0.012))

    # Contrast overlays
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.rectangle((0, 0, w, int(h * 0.33)), fill=(10, 12, 18, 74))
    od.rectangle((0, int(h * 0.49), w, h), fill=(8, 10, 16, 92))
    img.alpha_composite(ov)

    # Panels
    _draw_panel(img, layout["headline"], fill=(12, 16, 23, 145), outline=(186, 153, 103, 185), radius=20)

    for i in range(1, 5):
        panel = layout[f"card_{i}_panel"]
        fill = (34, 57, 79, 176) if i % 2 else (30, 63, 67, 176)
        _draw_panel(img, panel, fill=fill, outline=(210, 178, 130, 195), radius=22)

    _draw_panel(img, layout["why"], fill=(10, 14, 20, 170), outline=(194, 158, 108, 178), radius=12)
    _draw_panel(img, layout["digest"], fill=(9, 12, 18, 178), outline=(190, 153, 102, 170), radius=10)

    # Text
    _draw_text_block(
        img,
        layout["date"],
        copy["date"],
        bold=True,
        max_size=34,
        min_size=20,
        max_lines=1,
        color=(248, 214, 140),
        align="center",
        spacing=4,
    )

    _draw_text_block(
        img,
        headline_text_box,
        copy["headline"],
        bold=True,
        max_size=64,
        min_size=28,
        max_lines=3,
        color=(245, 238, 226),
        align="left",
        spacing=10,
    )

    _draw_text_block(
        img,
        layout["label_left"],
        "Highlights",
        bold=True,
        max_size=55,
        min_size=21,
        max_lines=1,
        color=(241, 196, 112),
        align="left",
        shadow=True,
    )

    _draw_text_block(
        img,
        layout["label_center"],
        "Market signal",
        bold=True,
        max_size=62,
        min_size=26,
        max_lines=1,
        color=(243, 225, 191),
        align="center",
        shadow=True,
    )

    cards = copy["cards"]
    measure_draw = ImageDraw.Draw(img)
    title_boxes = [layout[f"card_{i}_title"] for i in range(1, 5)]
    detail_boxes = [layout[f"card_{i}_detail"] for i in range(1, 5)]
    title_texts = [cards[i - 1]["title"] for i in range(1, 5)]
    detail_texts = [cards[i - 1]["detail"] for i in range(1, 5)]

    title_font, title_lines = _fit_uniform_text_blocks(
        measure_draw,
        title_texts,
        title_boxes,
        bold=False,
        max_size=42,
        min_size=15,
        max_lines=3,
        spacing=4,
    )
    detail_font, detail_lines = _fit_uniform_text_blocks(
        measure_draw,
        detail_texts,
        detail_boxes,
        bold=False,
        max_size=37,
        min_size=14,
        max_lines=4,
        spacing=4,
    )

    for i in range(1, 5):
        _draw_text_lines(
            img,
            title_boxes[i - 1],
            title_lines[i - 1],
            font=title_font,
            color=(244, 234, 214),
            align="left",
            spacing=4,
            shadow=True,
        )
        _draw_text_lines(
            img,
            detail_boxes[i - 1],
            detail_lines[i - 1],
            font=detail_font,
            color=(232, 223, 205),
            align="left",
            spacing=4,
            shadow=True,
        )

    _draw_text_block(
        img,
        why_text_box,
        f"Why it matters: {copy['why']}",
        bold=False,
        max_size=34,
        min_size=16,
        max_lines=2,
        color=(243, 229, 201),
        align="left",
        spacing=5,
    )

    _draw_text_block(
        img,
        digest_text_box,
        f"Read the public digest: {copy['link']}",
        bold=False,
        max_size=32,
        min_size=15,
        max_lines=1,
        color=(245, 205, 130),
        align="left",
        spacing=4,
    )

    if logo_path:
        _draw_logo(img, logo_path, layout["logo"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, format="PNG")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render LinkedIn image from template using explicit text placeholders.")
    parser.add_argument("--template", type=Path, default=None)
    parser.add_argument("--post-file", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--debug-placeholders", action="store_true")
    args = parser.parse_args()

    load_env_file(".env")

    post_path = args.post_file or _latest_linkedin_post(Path("output/linkedin"))
    if not post_path:
        raise SystemExit("No linkedin_post_*.txt file found in output/linkedin")
    if not post_path.exists():
        raise SystemExit(f"Post file not found: {post_path}")
    template_path = _resolve_template_path(args.template)

    run_date = _date_from_filename(post_path) or date.today().isoformat()
    out = args.out or Path("output/linkedin_images") / f"linkedin_image_{run_date}.png"

    out_path = render_image(template_path, post_path, out)
    print(f"Wrote {out_path}")

    if args.debug_placeholders:
        layout = _derive_layout(*Image.open(template_path).size)
        debug_out = out_path.with_name(out_path.stem + "_placeholder_map.png")
        _render_placeholder_map(template_path, debug_out, layout)
        print(f"Wrote {debug_out}")


if __name__ == "__main__":
    main()
