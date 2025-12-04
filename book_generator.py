#!/usr/bin/env python3
import json
import argparse
import re
import os
from glob import glob

from reportlab.platypus import (
    BaseDocTemplate,
    PageTemplate,
    Frame,
    Paragraph,
    PageBreak,
    Spacer,
    Flowable,
)
from reportlab.lib.pagesizes import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors

from PIL import Image as PILImage, ImageStat

from pypdf import PdfReader, PdfWriter, Transformation


def split_into_sentences(text: str):
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p for p in parts if p]


def load_image_paths(images_dir: str = "images"):
    def numeric_key(path: str):
        name = os.path.splitext(os.path.basename(path))[0]
        m = re.search(r'\d+', name)
        if m:
            return (int(m.group()), name.lower())
        return (float("inf"), name.lower())

    exts = ("*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG")
    paths = []
    for pattern in exts:
        paths.extend(glob(os.path.join(images_dir, pattern)))

    paths = sorted(paths, key=numeric_key)

    print("Image order:")
    for p in paths:
        print("  ", os.path.basename(p))

    return paths


def color_from_image(path: str):
    try:
        img = PILImage.open(path).convert("RGB")
        img = img.resize((64, 64))
        stat = ImageStat.Stat(img)
        r, g, b = stat.mean
        print(f"Avg color for {os.path.basename(path)}: {r:.1f}, {g:.1f}, {b:.1f}")
        return colors.Color(r / 255.0, g / 255.0, b / 255.0)
    except Exception as e:
        print(f"Failed to compute color for {path}: {e}")
        return None


def text_color_for_image(path: str, threshold: float = 0.5):
    try:
        img = PILImage.open(path).convert("RGB")
        img = img.resize((64, 64))
        stat = ImageStat.Stat(img)
        r, g, b = stat.mean
        lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
        choice = "WHITE" if lum < threshold else "BLACK"
        print(f"Luminance for {os.path.basename(path)}: {lum:.3f} -> {choice} text")
        if lum < threshold:
            return colors.white
        else:
            return colors.black
    except Exception as e:
        print(f"Failed to compute text color for {path}: {e}")
        return colors.black


class FullPageImage(Flowable):
    def __init__(self, path: str, page_width: float, page_height: float):
        super().__init__()
        self.path = path
        self.page_width = page_width
        self.page_height = page_height
        ir = ImageReader(path)
        self.imgw, self.imgh = ir.getSize()

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def drawOn(self, canvas, x, y, _sW=0):
        self.canv = canvas
        canvas.saveState()
        self.draw()
        canvas.restoreState()

    def draw(self):
        c = self.canv
        pw = float(self.page_width)
        ph = float(self.page_height)
        sx = pw / float(self.imgw)
        sy = ph / float(self.imgh)
        scale = max(sx, sy)
        w = self.imgw * scale
        h = self.imgh * scale
        x = (pw - w) / 2.0
        y = (ph - h) / 2.0
        c.drawImage(
            self.path,
            x,
            y,
            width=w,
            height=h,
            preserveAspectRatio=False,
            mask="auto",
        )


def make_on_page_callback(page_to_image_index, image_paths, page_width, page_height):
    def on_page(canvas, doc):
        page_num = doc.page
        if page_num not in page_to_image_index:
            return
        img_idx = page_to_image_index[page_num]
        if 0 <= img_idx < len(image_paths):
            color = color_from_image(image_paths[img_idx])
            if color is None:
                return
            canvas.saveState()
            canvas.setFillColor(color)
            canvas.rect(0, 0, page_width, page_height, stroke=0, fill=1)
            canvas.restoreState()

    return on_page


def create_fitting_paragraph(
    html_text: str,
    base_style: ParagraphStyle,
    max_width: float,
    max_height: float,
    base_font_size: int,
    min_font_size: int = 10,
):
    size = base_font_size
    last_para = None

    while size >= min_font_size:
        style = ParagraphStyle(
            name=f"{base_style.name}_{size}",
            parent=base_style,
            fontSize=size,
            leading=size + 4,
        )
        para = Paragraph(html_text, style)
        _w, h = para.wrap(max_width, max_height)
        if h <= max_height:
            return para, size
        last_para = para
        size -= 1

    return last_para, min_font_size


def build_inner_book(
    manuscript_path: str,
    output_path: str,
    images_dir: str = "images",
    font_size: int = 20,
    margin_inch: float = 1.0,
    page_width_inch: float = 8.625,
    page_height_inch: float = 8.75,
):
    with open(manuscript_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    title = data.get("title", "")
    author = data.get("author", "")
    pages = data["pages"]
    has_title = bool(title)
    image_paths = load_image_paths(images_dir)

    page_width = page_width_inch * inch
    page_height = page_height_inch * inch
    margin = margin_inch * inch

    doc = BaseDocTemplate(
        output_path,
        pagesize=(page_width, page_height),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )

    frame = Frame(
        margin,
        margin,
        page_width - 2 * margin,
        page_height - 2 * margin,
        id="normal",
    )

    page_to_image_index = {}
    current_page = 1

    if has_title:
        current_page += 1

    img_index = 0
    for _ in range(len(pages)):
        text_page_num = current_page
        if img_index < len(image_paths):
            page_to_image_index[text_page_num] = img_index
        current_page += 2
        img_index += 1

    on_page = make_on_page_callback(page_to_image_index, image_paths, page_width, page_height)
    template = PageTemplate(id="main", frames=[frame], onPage=on_page)
    doc.addPageTemplates([template])

    styles = getSampleStyleSheet()

    body_base = ParagraphStyle(
        "BodyBase",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=font_size,
        leading=font_size + 4,
        alignment=TA_CENTER,
    )

    title_style = ParagraphStyle(
        "TitleCentered",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=26,
        leading=30,
        alignment=TA_CENTER,
    )

    author_style = ParagraphStyle(
        "AuthorCentered",
        parent=styles["BodyText"],
        fontName="Helvetica-Oblique",
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
    )

    story = []

    usable_width = page_width - 2 * margin
    usable_height = page_height - 2 * margin

    if has_title:
        title_para = Paragraph(title, title_style)
        author_para = Paragraph(f"by {author}", author_style) if author else None
        _tw, th = title_para.wrap(usable_width, usable_height)
        total_height = th
        if author_para:
            _aw, ah = author_para.wrap(usable_width, usable_height)
            total_height += 0.25 * inch + ah

        if total_height < usable_height:
            top_space = (usable_height - total_height) / 2.0
        else:
            top_space = 0

        story.append(Spacer(1, top_space))
        story.append(title_para)
        if author_para:
            story.append(Spacer(1, 0.25 * inch))
            story.append(author_para)
        story.append(PageBreak())

    img_index = 0
    for page_text in pages:
        raw_chunks = [p.strip() for p in page_text.split("\n\n") if p.strip()]
        chunk_html_parts = []
        for chunk in raw_chunks:
            sentences = split_into_sentences(chunk)
            chunk_html = "<br/><br/>".join(sentences)
            chunk_html_parts.append(chunk_html)

        html_text = "<br/><br/>".join(chunk_html_parts) if chunk_html_parts else ""

        if img_index < len(image_paths):
            text_color = text_color_for_image(image_paths[img_index])
        else:
            text_color = colors.black

        page_style = ParagraphStyle(
            "BodyPage",
            parent=body_base,
            textColor=text_color,
        )

        para, used_size = create_fitting_paragraph(
            html_text=html_text,
            base_style=page_style,
            max_width=usable_width,
            max_height=usable_height,
            base_font_size=font_size,
            min_font_size=5,
        )

        _w, h = para.wrap(usable_width, usable_height)
        if h < usable_height:
            top_space = (usable_height - h) / 2.0
        else:
            top_space = 0

        story.append(Spacer(1, top_space))
        story.append(para)
        story.append(PageBreak())

        if img_index < len(image_paths):
            img_path = image_paths[img_index]
            img_index += 1
            story.append(FullPageImage(img_path, page_width=page_width, page_height=page_height))
            story.append(PageBreak())
        else:
            story.append(PageBreak())

    doc.build(story)
    print(f"Inner book created: {output_path}")


def _set_all_boxes(page, width, height):
    boxes = ["mediabox", "cropbox", "trimbox", "bleedbox", "artbox"]
    for name in boxes:
        box = getattr(page, name, None)
        if box is not None:
            box.lower_left = (0, 0)
            box.upper_right = (width, height)


def merge_preface_and_book(
    preface_path: str,
    inner_book_path: str,
    final_output: str,
    page_width_inch: float = 8.625,
    page_height_inch: float = 8.75,
):
    if not os.path.exists(preface_path):
        raise FileNotFoundError(f"Preface file not found: {preface_path}")
    if not os.path.exists(inner_book_path):
        raise FileNotFoundError(f"Inner book file not found: {inner_book_path}")

    TARGET_W = page_width_inch * 72.0
    TARGET_H = page_height_inch * 72.0
    TOL = 1.0

    writer = PdfWriter()

    preface_reader = PdfReader(preface_path)
    for page in preface_reader.pages:
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)

        if abs(w - TARGET_W) <= TOL and abs(h - TARGET_H) <= TOL:
            _set_all_boxes(page, TARGET_W, TARGET_H)
            writer.add_page(page)
        else:
            scale = min(TARGET_W / w, TARGET_H / h)
            new_w = w * scale
            new_h = h * scale
            dx = (TARGET_W - new_w) / 2.0
            dy = (TARGET_H - new_h) / 2.0
            _set_all_boxes(page, w, h)
            transform = Transformation().scale(scale, scale).translate(dx, dy)
            page.add_transformation(transform)
            _set_all_boxes(page, TARGET_W, TARGET_H)
            writer.add_page(page)

    inner_reader = PdfReader(inner_book_path)
    for page in inner_reader.pages:
        _set_all_boxes(page, TARGET_W, TARGET_H)
        writer.add_page(page)

    with open(final_output, "wb") as f_out:
        writer.write(f_out)

    print(f"Final book (with preface) created: {final_output}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate a children’s book PDF from a manuscript, "
            "prefaced by rfh.pdf (or another PDF), with optional images, "
            "color-themed text pages, and configurable page size/margins."
        )
    )
    parser.add_argument("manuscript", help="Path to manuscript JSON file")
    parser.add_argument(
        "-o",
        "--output",
        default="children_book.pdf",
        help="Output PDF file name (default: children_book.pdf)",
    )
    parser.add_argument(
        "--preface",
        default="rfh.pdf",
        help="Preface PDF file to put before the book (default: rfh.pdf)",
    )
    parser.add_argument(
        "--images-dir",
        default="images",
        help="Directory containing page images (default: ./images)",
    )
    parser.add_argument(
        "--font-size",
        type=int,
        default=20,
        help="Body font size in points (default: 20)",
    )
    parser.add_argument(
        "--margin-inch",
        type=float,
        default=1.0,
        help="Margin size in inches (all sides, default: 1.0)",
    )
    parser.add_argument(
        "--page-width-inch",
        type=float,
        default=8.625,
        help="Page width in inches (default: 8.625)",
    )
    parser.add_argument(
        "--page-height-inch",
        type=float,
        default=8.75,
        help="Page height in inches (default: 8.75)",
    )

    args = parser.parse_args()

    inner_book_path = "_inner_book_tmp.pdf"

    build_inner_book(
        manuscript_path=args.manuscript,
        output_path=inner_book_path,
        images_dir=args.images_dir,
        font_size=args.font_size,
        margin_inch=args.margin_inch,
        page_width_inch=args.page_width_inch,
        page_height_inch=args.page_height_inch,
    )

    merge_preface_and_book(
        preface_path=args.preface,
        inner_book_path=inner_book_path,
        final_output=args.output,
        page_width_inch=args.page_width_inch,
        page_height_inch=args.page_height_inch,
    )

    try:
        os.remove(inner_book_path)
    except OSError:
        pass


if __name__ == "__main__":
    main()
