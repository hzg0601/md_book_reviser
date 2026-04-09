# Markdown Book Reviser

An automation toolkit for producing technical books from Markdown sources.

The project is designed to connect chapter revision, terminology normalization, bibliography retrieval, citation cleanup, figure and table naming, numbering normalization, and final Word generation into a repeatable workflow.

Core implementation lives in [src](src).

## Features

This repository provides:

1. Content revision
2. Terminology extraction and normalization
3. Bibliography search and MLA-style formatting
4. Consistency checks between in-text citations and reference lists
5. Automatic numbering for figures, tables, and equations
6. Markdown structure cleanup and image path normalization
7. DOCX generation and post-processing with Pandoc + python-docx

## Recommended Workflow

Suggested processing order:

1. Normalize structure
2. Revise content
3. Search bibliography and generate `citation.markdown`
4. Rearrange and validate citations
5. Number figures, tables, and equations
6. Normalize terminology
7. Build DOCX output

Related modules:

1. [src/structure_unifier.py](src/structure_unifier.py)
2. [src/content_reviser.py](src/content_reviser.py)
3. [src/bibliography_search_api.py](src/bibliography_search_api.py)
4. [src/citation_rearrange.py](src/citation_rearrange.py) and [src/citation_checker.py](src/citation_checker.py)
5. [src/numbering.py](src/numbering.py)
6. [src/term_normalizer.py](src/term_normalizer.py)
7. [src/build_book_docx.py](src/build_book_docx.py)

## Module Overview

### Foundation and Configuration

- [src/utils.py](src/utils.py)
  - Loads [src/config.yaml](src/config.yaml)
  - Initializes logging under `logs`
  - Provides shared helpers such as `chat_vlm`, `chapter_reader`, and `get_md_path`

### Content and Structure Processing

- [src/content_reviser.py](src/content_reviser.py)
  - Uses a two-stage VLM flow: detect issues first, revise second
  - Produces `issues.json` and `revised.markdown`
- [src/structure_unifier.py](src/structure_unifier.py)
  - Normalizes Markdown image references
  - Removes unreferenced images
- [src/formatter.py](src/formatter.py)
  - Fixes formatting issues that affect Pandoc compatibility
- [src/name_normalizer.py](src/name_normalizer.py)
  - Normalizes figure and table titles, optionally with VLM support
- [src/numbering.py](src/numbering.py)
  - Renumbers figures, tables, equations, and in-text references

### Bibliography and Citation Processing

- [src/bibliography_search_api.py](src/bibliography_search_api.py)
  - Extracts citation clues from chapter text
  - Calls the search service and generates reference entries
  - Merges and deduplicates results into `citation.markdown`
- [src/bibliography_citation_api.py](src/bibliography_citation_api.py)
  - Provides multi-source academic metadata lookup and citation normalization
- [src/citation_rearrange.py](src/citation_rearrange.py)
  - Reorders, classifies, deduplicates, and formats `citation.markdown`
- [src/citation_checker.py](src/citation_checker.py)
  - Checks and fixes citation/reference consistency issues
- [src/renumbering_citation.py](src/renumbering_citation.py)
  - Deduplicates and renumbers citation markers

### Terminology and DOCX Build

- [src/term_normalizer.py](src/term_normalizer.py)
  - Extracts and normalizes terminology across the book
  - Produces `term_dict.json` and `normalized.markdown`
- [src/build_book_docx.py](src/build_book_docx.py)
  - Converts Markdown files to DOCX and merges them
  - Applies post-processing for fonts, images, tables, and equation layout
  - Uses [src/pandoc_docx_defaults.yaml](src/pandoc_docx_defaults.yaml) and [src/pandoc_reference.docx](src/pandoc_reference.docx)

## Requirements

Python dependencies are listed in [requirements.txt](requirements.txt):

- regex
- requests
- loguru
- pyyaml
- python-docx
- docxcompose

You also need Pandoc installed and available in `PATH`.

## Configuration

The main configuration file is [src/config.yaml](src/config.yaml). It contains both `local` and `remote` environments plus a `mode` switch.

Important fields:

- `VLM_ENDPOINT`
- `VLM_MODEL_NAME`
- `VLM_API_KEY`
- `BOCHA_API_KEY`
- `MD_BOOK_PATH`
- `MAX_CHARS_PER_CHUNK`

Recommendations:

1. Do not commit real API keys to a public repository.
2. Prefer environment variables or private local overrides for secrets.

## Quick Start

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Configure path and API keys

Edit [src/config.yaml](src/config.yaml):

1. Set `mode` to `local` or `remote`
2. Set `MD_BOOK_PATH` to your book root directory
3. Fill in the VLM and search API credentials

### 3) Common commands

Check citation consistency:

```bash
python src/citation_checker.py
```

Rearrange `citation.markdown`:

```bash
python src/citation_rearrange.py
```

Run terminology normalization:

```bash
python src/term_normalizer.py
```

Build DOCX:

```bash
python src/build_book_docx.py
```

Build DOCX with explicit input and output paths:

```bash
python src/build_book_docx.py <input_root> --output-dir <output_dir> --output-name book_complete.docx
```

## Input and Output Conventions

### Chapter Layout

By default, the project walks chapter subdirectories under the configured book root. Each chapter usually contains at least one Markdown file.

### Minimal Runnable Example

If you want to validate the workflow on a single chapter first, use a layout like this:

```text
book-demo/
├─ Chapter-01/
│  ├─ chapter.md
│  ├─ citation.markdown
│  └─ images/
│     ├─ fig1.png
│     └─ fig2.png
```

Recommended conventions:

1. Use `chapter.md` as the main chapter file.
2. Use `citation.markdown` for chapter-level references. It can start empty.
3. Store chapter-local image assets under `images/` and reference them with relative paths.

Minimal chapter example:

```markdown
# Chapter 1 Test Chapter

This is a short paragraph that refers to Figure 1-1.

![Test image](images/fig1.png)

## 1.1 Section Title

You can continue with equations, tables, or citation examples here.
```

Then point `MD_BOOK_PATH` in [src/config.yaml](src/config.yaml) to `book-demo` and run:

```bash
python src/build_book_docx.py
```

### Typical Outputs

- Revision outputs: `issues.json`, `revised.markdown`
- Bibliography outputs: `citation.markdown`
- Terminology outputs: `term_dict.json`, `normalized.markdown`
- Build outputs: merged DOCX files under `logs/pandoc_docx`
- Runtime logs: `log_*.log` under `logs`

## Troubleshooting

### 1) Pandoc not found

Symptom: DOCX build fails because Pandoc is not available in `PATH`.

Fix:

1. Install Pandoc.
2. Verify that `pandoc` runs in your terminal.

### 2) Failed to delete the intermediate directory on Windows

Symptom: cleanup ends with a `PermissionError` when removing the intermediate output directory.

Cause: delayed file handle release, OneDrive sync, or antivirus locking the files.

Fix:

1. Use `--keep-intermediate`
2. Write outputs to a non-synced directory
3. Close processes holding the files and retry

### 3) API throttling or transient network errors

Symptom: bibliography search or VLM requests fail intermittently.

Fix:

1. Verify network access and API keys
2. Check retry logs
3. Process chapters in smaller batches

## Development Notes

1. Start with a single chapter before running the full book.
2. Verify outputs stage by stage.
3. Back up important manuscripts before automated rewriting.
