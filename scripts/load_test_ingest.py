#!/usr/bin/env python3
"""Load-test document ingest across formats and sizes.

Generates fixtures, uploads via signed URL, starts ingest, and polls status.

Examples:
  python scripts/load_test_ingest.py \\
    --email chi@gmail.com --password 'Password@1' --profile quick

  python scripts/load_test_ingest.py \\
    --email chi@gmail.com --password 'Password@1' --profile full --parallel 2

  # Generate fixtures only (no API calls)
  python scripts/load_test_ingest.py --generate-only --profile full
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib import error, request

import fitz
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "scripts" / "fixtures" / "load_test"
DEFAULT_BASE = "http://127.0.0.1:8080/api"

# Target sizes (bytes). Generators grow until they meet or slightly exceed these.
KB = 1024
MB = 1024 * KB

PROFILES: dict[str, list[tuple[str, int]]] = {
    # Fast smoke across every format
    "quick": [
        ("txt", 100 * KB),
        ("json", 100 * KB),
        ("csv", 100 * KB),
        ("md", 100 * KB),
        ("png", 200 * KB),
        ("pdf_easy", 200 * KB),
        ("pdf_complex", 500 * KB),
    ],
    # Bigger files of varying sizes
    "medium": [
        ("txt", 1 * MB),
        ("json", 1 * MB),
        ("csv", 1 * MB),
        ("md", 1 * MB),
        ("png", 1 * MB),
        ("pdf_easy", 1 * MB),
        ("pdf_complex", 2 * MB),
        ("txt", 5 * MB),
        ("json", 5 * MB),
        ("csv", 5 * MB),
    ],
    # Stress sizes (may take several minutes)
    "full": [
        ("txt", 100 * KB),
        ("txt", 1 * MB),
        ("txt", 5 * MB),
        ("json", 100 * KB),
        ("json", 1 * MB),
        ("json", 5 * MB),
        ("csv", 100 * KB),
        ("csv", 1 * MB),
        ("csv", 5 * MB),
        ("md", 100 * KB),
        ("md", 1 * MB),
        ("md", 5 * MB),
        ("png", 500 * KB),
        ("png", 2 * MB),
        ("pdf_easy", 500 * KB),
        ("pdf_easy", 2 * MB),
        ("pdf_easy", 5 * MB),
        ("pdf_complex", 1 * MB),
        ("pdf_complex", 5 * MB),
        ("pdf_complex", 10 * MB),
    ],
}


@dataclass
class Case:
    kind: str
    target_bytes: int
    path: Path
    content_type: str

    @property
    def label(self) -> str:
        return f"{self.kind}:{_human_size(self.target_bytes)}"


@dataclass
class Result:
    case: Case
    document_id: str | None
    upload_s: float
    put_s: float
    ingest_http: int | None
    poll_s: float
    final_status: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.final_status == "completed" and self.error is None


def _human_size(n: int) -> str:
    if n >= MB:
        return f"{n / MB:.0f}MB" if n % MB == 0 else f"{n / MB:.1f}MB"
    return f"{n / KB:.0f}KB"


def _ensure_size(path: Path, target: int, grow: Callable[[], None]) -> None:
    """Call grow() until path exists and is >= target bytes."""
    while True:
        if path.exists() and path.stat().st_size >= target:
            return
        grow()


# ---------------------------------------------------------------------------
# Fixture generators
# ---------------------------------------------------------------------------


def generate_txt(path: Path, target: int, run_id: str = "run") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    paragraph = (
        "Study Buddy load-test paragraph. Retrieval, embeddings, and chunking "
        "need enough unique text so the pipeline does real work. "
        f"Token padding {'vector ' * 20}\n\n"
    )
    with path.open("w", encoding="utf-8") as f:
        f.write(f"run_id={run_id}\n\n")
        written = f.tell()
        i = 0
        while written < target:
            block = f"## Section {i}\n{paragraph}"
            f.write(block)
            written += len(block.encode("utf-8"))
            i += 1


def generate_json(path: Path, target: int, run_id: str = "run") -> None:
    """Fewer large objects — avoids RecursiveJsonSplitter chunk explosion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Dense body text keeps byte size up without thousands of tiny records.
    body_pad = ("Architecture guidance for retrieval systems. " * 40) + "\n"
    records: list[dict] = []
    i = 0
    while True:
        records.append(
            {
                "id": i,
                "run_id": run_id,
                "title": f"Record {i}",
                "region": f"R{i % 12}",
                "metrics": {
                    "q1": (i * 3) % 97,
                    "q2": (i * 5) % 97,
                    "q3": (i * 7) % 97,
                    "q4": (i * 11) % 97,
                },
                "body": f"Section {i}\n{body_pad * 3}",
                "tags": [f"tag{(i + k) % 20}" for k in range(3)],
            }
        )
        i += 1
        blob = json.dumps({"run_id": run_id, "documents": records}, indent=2).encode(
            "utf-8"
        )
        if len(blob) >= target:
            path.write_bytes(blob)
            return


def generate_csv(path: Path, target: int, run_id: str = "run") -> None:
    """Fewer rows with long notes — parse_csv makes one doc per row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = ["id", "run_id", "metric", "region", "q1", "q2", "q3", "q4", "notes"]
    long_note = (
        "csv load note with enough prose for embedding work. " * 40
    )
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        i = 0
        while f.tell() < target:
            writer.writerow(
                [
                    i,
                    run_id,
                    f"M{i % 50}",
                    f"R{i % 12}",
                    (i * 3) % 97,
                    (i * 5) % 97,
                    (i * 7) % 97,
                    (i * 11) % 97,
                    f"{long_note} row={i}",
                ]
            )
            i += 1


def generate_md(path: Path, target: int, run_id: str = "run") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(f"# Study Buddy Load Test\n\nrun_id={run_id}\n\n")
        i = 0
        while f.tell() < target:
            f.write(f"## Section {i}\n\n")
            f.write(
                "Markdown fixture for unstructured parsing and splitting.\n\n"
            )
            f.write(f"- Throughput target: {(i + 1) * 100} rps\n")
            f.write(f"- Latency budget: {50 + i}ms\n")
            f.write(f"- Retention: {30 + (i % 60)} days\n\n")
            f.write("```python\n")
            f.write(f"def appendix_{i}(payload):\n")
            f.write(f"    return {{'section': {i}, 'payload': payload}}\n")
            f.write("```\n\n")
            f.write("| Col A | Col B | Col C |\n| --- | --- | --- |\n")
            f.write(f"| {i} | region-{i % 8} | value-{(i * 13) % 100} |\n\n")
            i += 1


def generate_text_rich_png(path: Path, target: int, run_id: str = "run") -> None:
    """PNG packed with readable text for OCR / image ingest paths."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Scale canvas until compressed PNG is large enough
    width, height = 1200, 1600
    attempt = 0
    while True:
        img = Image.new("RGB", (width, height), color=(248, 246, 240))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18
            )
            title_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28
            )
        except OSError:
            font = ImageFont.load_default()
            title_font = font

        draw.text(
            (40, 30),
            f"Study Buddy OCR Load Fixture {run_id} #{attempt}",
            fill=(20, 40, 60),
            font=title_font,
        )
        y = 80
        line_idx = 0
        while y < height - 40:
            line = (
                f"L{line_idx:04d}  Region=R{line_idx % 12}  "
                f"Q1={(line_idx * 3) % 97} Q2={(line_idx * 5) % 97}  "
                f"Note: vector retrieval table cell detail {line_idx}"
            )
            draw.text((40, y), line, fill=(30, 30, 30), font=font)
            y += 22
            line_idx += 1
            if line_idx % 40 == 0:
                draw.line((40, y, width - 40, y), fill=(180, 180, 180), width=1)
                y += 10

        # Mild noise so compression does not shrink too aggressively
        pixels = img.load()
        for n in range(0, width * height, max(1, (width * height) // 8000)):
            x = n % width
            yy = (n // width) % height
            r, g, b = pixels[x, yy]
            pixels[x, yy] = (r ^ (n % 7), g, b ^ ((n // 3) % 5))

        img.save(path, format="PNG", optimize=False)
        size = path.stat().st_size
        if size >= target:
            return
        # Grow canvas for next attempt
        width = int(width * 1.25)
        height = int(height * 1.25)
        attempt += 1
        if attempt > 12:
            raise RuntimeError(
                f"Could not grow PNG to {target} bytes (got {size})"
            )


def generate_pdf_easy(path: Path, target: int, run_id: str = "run") -> None:
    """Text-only multi-page PDF (cheap to parse)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page_n = 0
    while True:
        page = doc.new_page(width=612, height=792)
        page_n += 1
        y = 48
        page.insert_text(
            (36, y),
            f"Easy PDF load test {run_id} — page {page_n}",
            fontsize=14,
        )
        y += 28
        for row in range(38):
            page.insert_text(
                (36, y),
                (
                    f"P{page_n} R{row}: Study notes on chunking, embeddings, "
                    f"and retrieval. Metric={(row * page_n) % 97} "
                    + ("text " * 6)
                ),
                fontsize=9,
            )
            y += 16
            if y > 760:
                break
        if page_n % 3 == 0:
            doc.save(path, deflate=True, garbage=1)
            if path.stat().st_size >= target:
                doc.close()
                return
    doc.save(path, deflate=True, garbage=1)
    doc.close()


def generate_pdf_complex(path: Path, target: int, run_id: str = "run") -> None:
    """PDF with tables + embedded noisy images (heavier pipeline)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page_n = 0
    seed = 1

    def noise_png(w: int = 900, h: int = 280, seed: int = 0) -> bytes:
        n = w * h * 3
        body = bytearray(n)
        for i in range(n):
            body[i] = (i * 41 + seed * 19 + (i // 3) * 11) & 0xFF
        pix = fitz.Pixmap(fitz.csRGB, w, h, bytes(body), False)
        return pix.tobytes("png")

    while True:
        page = doc.new_page(width=612, height=792)
        page_n += 1
        y = 36
        page.insert_text(
            (36, y),
            f"Complex PDF {run_id} — page {page_n} (tables + images)",
            fontsize=13,
        )
        y += 24
        cols = ["Metric", "Region", "Q1", "Q2", "Q3", "Q4", "Notes"]
        page.insert_text((36, y), " | ".join(cols), fontsize=9)
        y += 14
        for row in range(22):
            values = [
                f"M{row}",
                f"R{(row + page_n) % 12}",
                f"{(row * 3 + page_n) % 97}",
                f"{(row * 5 + page_n) % 97}",
                f"{(row * 7 + page_n) % 97}",
                f"{(row * 11 + page_n) % 97}",
                f"detail {(row + page_n) * 17} " + ("cell " * 3),
            ]
            page.insert_text((36, y), " | ".join(values), fontsize=8)
            y += 12
            if y > 480:
                break

        png = noise_png(seed=seed)
        seed += 1
        page.insert_image(fitz.Rect(36, 520, 576, 760), stream=png)

        if page_n % 2 == 0:
            tmp = path.with_suffix(".part.pdf")
            doc.save(tmp, deflate=False, garbage=0)
            if tmp.stat().st_size >= target:
                tmp.replace(path)
                doc.close()
                return
            tmp.replace(path)

    doc.save(path, deflate=False, garbage=0)
    doc.close()


GENERATORS: dict[str, tuple[Callable[[Path, int], None], str, str]] = {
    # kind -> (generator, extension, content-type)
    "txt": (generate_txt, ".txt", "text/plain"),
    "json": (generate_json, ".json", "application/json"),
    "csv": (generate_csv, ".csv", "text/csv"),
    "md": (generate_md, ".md", "text/markdown"),
    "png": (generate_text_rich_png, ".png", "image/png"),
    "pdf_easy": (generate_pdf_easy, ".pdf", "application/pdf"),
    "pdf_complex": (generate_pdf_complex, ".pdf", "application/pdf"),
}


def build_cases(profile: str, fixtures_dir: Path, run_id: str) -> list[Case]:
    specs = PROFILES[profile]
    cases: list[Case] = []
    for kind, target in specs:
        gen, ext, ctype = GENERATORS[kind]
        name = f"{kind}_{_human_size(target).lower()}_{run_id}{ext}"
        path = fixtures_dir / name
        print(f"  generate {name} (target {_human_size(target)}) ...", flush=True)
        t0 = time.perf_counter()
        gen(path, target, run_id=run_id)
        size = path.stat().st_size
        print(
            f"    -> {size / KB:.1f} KB in {time.perf_counter() - t0:.2f}s",
            flush=True,
        )
        cases.append(
            Case(kind=kind, target_bytes=target, path=path, content_type=ctype)
        )
    return cases


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def http_json(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    data=None,
    raw: bool = False,
    timeout: int = 600,
):
    body = None
    req_headers = dict(headers or {})
    if data is not None and not raw:
        body = json.dumps(data).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    elif data is not None and raw:
        body = data if isinstance(data, bytes) else data.encode("utf-8")
    req = request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw_body = resp.read()
            text = raw_body.decode("utf-8") if raw_body else ""
            try:
                return resp.status, json.loads(text) if text else None
            except json.JSONDecodeError:
                return resp.status, text
    except error.HTTPError as e:
        raw_body = e.read()
        text = raw_body.decode("utf-8") if raw_body else ""
        try:
            return e.code, json.loads(text) if text else None
        except json.JSONDecodeError:
            return e.code, text


def login(base: str, email: str, password: str) -> str:
    status, payload = http_json(
        "POST",
        f"{base}/authentication/login",
        data={"email": email, "password": password},
    )
    if status != 200:
        # Try register once, then login again
        http_json(
            "POST",
            f"{base}/authentication/register",
            data={"email": email, "password": password, "name": email.split("@")[0]},
        )
        status, payload = http_json(
            "POST",
            f"{base}/authentication/login",
            data={"email": email, "password": password},
        )
    if status != 200 or not isinstance(payload, dict):
        raise SystemExit(f"Login failed HTTP {status}: {payload}")
    return payload["data"]["token"]


def run_case(
    base: str,
    token: str,
    case: Case,
    *,
    poll_timeout_s: int,
    poll_interval_s: float,
) -> Result:
    auth = {"Authorization": f"Bearer {token}"}
    ts = int(time.time())
    doc_name = f"Load {case.label} {ts}"

    t_upload = time.perf_counter()
    status, upload = http_json(
        "POST",
        f"{base}/system/documents/upload",
        headers=auth,
        data={
            "name": doc_name,
            "category": "load_test",
            "description": f"load test {case.kind} {_human_size(case.target_bytes)}",
            "file_name": case.path.name,
        },
    )
    upload_s = time.perf_counter() - t_upload
    if status != 200 or not isinstance(upload, dict):
        return Result(
            case=case,
            document_id=None,
            upload_s=upload_s,
            put_s=0,
            ingest_http=None,
            poll_s=0,
            final_status="error",
            error=f"upload HTTP {status}: {upload}",
        )

    data = upload["data"]
    doc_id = data["document"]["id"]
    signed_url = data["upload_url"]
    print(f"   doc_id={doc_id} uploading bytes...", flush=True)

    t_put = time.perf_counter()
    put_status, put_body = http_json(
        "PUT",
        signed_url,
        headers={"Content-Type": case.content_type},
        data=case.path.read_bytes(),
        raw=True,
        timeout=900,
    )
    put_s = time.perf_counter() - t_put
    if put_status != 200:
        return Result(
            case=case,
            document_id=doc_id,
            upload_s=upload_s,
            put_s=put_s,
            ingest_http=None,
            poll_s=0,
            final_status="error",
            error=f"PUT HTTP {put_status}: {put_body}",
        )

    status, ingest = http_json(
        "POST",
        f"{base}/system/documents/{doc_id}/ingest",
        headers=auth,
    )
    print(f"   ingest HTTP={status}", flush=True)
    if status not in (200, 202):
        return Result(
            case=case,
            document_id=doc_id,
            upload_s=upload_s,
            put_s=put_s,
            ingest_http=status,
            poll_s=0,
            final_status="error",
            error=f"ingest HTTP {status}: {ingest}",
        )

    t_poll = time.perf_counter()
    final = "timeout"
    deadline = time.time() + poll_timeout_s
    last_status = "pending"
    while time.time() < deadline:
        time.sleep(poll_interval_s)
        st, body = http_json(
            "GET",
            f"{base}/system/documents/{doc_id}",
            headers=auth,
        )
        if st != 200 or not isinstance(body, dict):
            continue
        doc_status = body["data"]["status"]
        if doc_status != last_status:
            print(
                f"   status={doc_status} t+{time.perf_counter() - t_poll:.0f}s",
                flush=True,
            )
            last_status = doc_status
        if doc_status in ("completed", "failed", "cancelled"):
            final = doc_status
            break
    poll_s = time.perf_counter() - t_poll

    return Result(
        case=case,
        document_id=doc_id,
        upload_s=upload_s,
        put_s=put_s,
        ingest_http=status,
        poll_s=poll_s,
        final_status=final,
        error=None if final == "completed" else f"ended as {final}",
    )


def print_summary(results: list[Result]) -> int:
    print("\n=== SUMMARY ===")
    print(
        f"{'CASE':<28} {'SIZE':>10} {'UPLOAD':>8} {'PUT':>8} "
        f"{'POLL':>8} {'STATUS':<12} DOC_ID"
    )
    ok = 0
    for r in results:
        size = r.case.path.stat().st_size if r.case.path.exists() else 0
        mark = "OK" if r.ok else "FAIL"
        if r.ok:
            ok += 1
        print(
            f"{r.case.label:<28} {_human_size(size):>10} "
            f"{r.upload_s:7.2f}s {r.put_s:7.2f}s {r.poll_s:7.2f}s "
            f"{mark + '/' + r.final_status:<12} {r.document_id or '-'}"
        )
        if r.error and not r.ok:
            print(f"  error: {r.error}")
    print(f"\nPassed {ok}/{len(results)}")
    return 0 if ok == len(results) else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest pipeline load test")
    p.add_argument("--base", default=DEFAULT_BASE, help="API base URL")
    p.add_argument("--email", default="chi@gmail.com")
    p.add_argument("--password", default="Password@1")
    p.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="quick",
        help="Fixture size matrix",
    )
    p.add_argument(
        "--fixtures-dir",
        type=Path,
        default=DEFAULT_FIXTURES,
        help="Where generated files are stored",
    )
    p.add_argument(
        "--generate-only",
        action="store_true",
        help="Only build fixtures; skip API calls",
    )
    p.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Concurrent ingest jobs (1 = sequential)",
    )
    p.add_argument("--poll-timeout", type=int, default=600)
    p.add_argument("--poll-interval", type=float, default=2.0)
    p.add_argument(
        "--kinds",
        nargs="+",
        choices=sorted(GENERATORS),
        help="Optional subset of kinds (default: all in profile)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    run_id = str(int(time.time()))
    print(f"Profile={args.profile} fixtures={args.fixtures_dir} run_id={run_id}")
    args.fixtures_dir.mkdir(parents=True, exist_ok=True)

    print("=== GENERATE FIXTURES ===")
    cases = build_cases(args.profile, args.fixtures_dir, run_id=run_id)
    if args.kinds:
        cases = [c for c in cases if c.kind in set(args.kinds)]
        if not cases:
            raise SystemExit("No cases left after --kinds filter")

    if args.generate_only:
        print("Generate-only done.")
        return 0

    print("\n=== LOGIN ===")
    token = login(args.base, args.email, args.password)
    print("ok")

    print(f"\n=== INGEST ({len(cases)} cases, parallel={args.parallel}) ===")
    results: list[Result] = []

    if args.parallel <= 1:
        for case in cases:
            print(f"\n-> {case.label} ({case.path.name})")
            result = run_case(
                args.base,
                token,
                case,
                poll_timeout_s=args.poll_timeout,
                poll_interval_s=args.poll_interval,
            )
            results.append(result)
            print(
                f"   status={result.final_status} "
                f"upload={result.upload_s:.2f}s put={result.put_s:.2f}s "
                f"poll={result.poll_s:.2f}s doc={result.document_id}"
            )
    else:
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futs = {
                pool.submit(
                    run_case,
                    args.base,
                    token,
                    case,
                    poll_timeout_s=args.poll_timeout,
                    poll_interval_s=args.poll_interval,
                ): case
                for case in cases
            }
            for fut in as_completed(futs):
                case = futs[fut]
                result = fut.result()
                results.append(result)
                print(
                    f"-> {case.label}: {result.final_status} "
                    f"poll={result.poll_s:.2f}s doc={result.document_id}"
                )

    # Stable order for summary
    order = {c.label: i for i, c in enumerate(cases)}
    results.sort(key=lambda r: order.get(r.case.label, 0))
    return print_summary(results)


if __name__ == "__main__":
    sys.exit(main())
