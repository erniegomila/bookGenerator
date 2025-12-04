#!/usr/bin/env python3
import os
import json
import uuid
from pathlib import Path
import shutil  # <-- added

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    send_from_directory,
    flash,
)

from book_generator import build_inner_book, merge_preface_and_book

app = Flask(__name__)
app.secret_key = "change-me-to-something-random"

BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "ui_runs"
RUNS_DIR.mkdir(exist_ok=True)


def _safe_float(val, default):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        font_size = _safe_int(request.form.get("font_size"), 20)
        margin_inch = _safe_float(request.form.get("margin_inch"), 1.0)
        page_width_inch = _safe_float(request.form.get("page_width_inch"), 8.625)
        page_height_inch = _safe_float(request.form.get("page_height_inch"), 8.75)
        output_name = request.form.get("output_name") or "children_book.pdf"

        manuscript_file = request.files.get("manuscript_file")
        manuscript_text = request.form.get("manuscript_text", "").strip()

        preface_file = request.files.get("preface_file")
        images_files = request.files.getlist("images")

        if not manuscript_file and not manuscript_text:
            flash("Please upload a manuscript JSON file or paste JSON in the text box.")
            return redirect(url_for("index"))

        run_id = str(uuid.uuid4())
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # delete all other runs so only the latest one uses space
        for existing in RUNS_DIR.iterdir():
            if existing.is_dir() and existing.name != run_id:
                shutil.rmtree(existing, ignore_errors=True)

        images_dir = run_dir / "images"
        images_dir.mkdir(exist_ok=True)

        try:
            if manuscript_file and manuscript_file.filename:
                data = json.load(manuscript_file.stream)
            else:
                data = json.loads(manuscript_text)
        except json.JSONDecodeError as e:
            flash(f"Error parsing manuscript JSON: {e}")
            return redirect(url_for("index"))

        manuscript_path = run_dir / "manuscript.json"
        with open(manuscript_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if preface_file and preface_file.filename:
            preface_path = run_dir / "preface.pdf"
            preface_file.save(preface_path)
        else:
            preface_path = BASE_DIR / "rfh.pdf"
            if not preface_path.exists():
                flash("No preface file uploaded and rfh.pdf not found in project directory.")
                return redirect(url_for("index"))

        for img in images_files:
            if not img.filename:
                continue
            dest = images_dir / img.filename
            img.save(dest)

        inner_book_path = run_dir / "_inner_book_tmp.pdf"
        final_output = run_dir / output_name

        try:
            build_inner_book(
                manuscript_path=str(manuscript_path),
                output_path=str(inner_book_path),
                images_dir=str(images_dir),
                font_size=font_size,
                margin_inch=margin_inch,
                page_width_inch=page_width_inch,
                page_height_inch=page_height_inch,
            )

            merge_preface_and_book(
                preface_path=str(preface_path),
                inner_book_path=str(inner_book_path),
                final_output=str(final_output),
                page_width_inch=page_width_inch,
                page_height_inch=page_height_inch,
            )
        except Exception as e:
            flash(f"Error generating book: {e}")
            return redirect(url_for("index"))

        return redirect(
            url_for("preview", run_id=run_id, filename=final_output.name)
        )

    return render_template(
        "index.html",
        default_font_size=20,
        default_margin_inch=1.0,
        default_output_name="children_book.pdf",
        default_page_width_inch=8.625,
        default_page_height_inch=8.75,
    )


@app.route("/preview/<run_id>/<filename>")
def preview(run_id, filename):
    run_dir = RUNS_DIR / run_id
    pdf_path = run_dir / filename
    if not pdf_path.exists():
        flash("Requested file not found.")
        return redirect(url_for("index"))

    pdf_url = url_for("download_file", run_id=run_id, filename=filename)
    return render_template("preview.html", pdf_url=pdf_url, filename=filename)


@app.route("/download/<run_id>/<filename>")
def download_file(run_id, filename):
    run_dir = RUNS_DIR / run_id
    return send_from_directory(run_dir, filename, as_attachment=False)


if __name__ == "__main__":
    app.run(debug=True)
