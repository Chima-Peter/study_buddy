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
# LLM research corpora (each format gets a distinct topic family)
# ---------------------------------------------------------------------------

# Plain-text survey: transformers, attention, scaling
TXT_PARAS = [
    "The transformer architecture replaced recurrence with multi-head self-attention, "
    "allowing each token to attend over the full context window in parallel. This "
    "design choice underpins almost every modern large language model.",
    "Scaled dot-product attention computes similarity between queries and keys, then "
    "weights values. Multi-head attention runs several such projections so the model "
    "can track syntax, coreference, and long-range dependencies simultaneously.",
    "Positional information is not inherent to attention. Absolute sinusoidal encodings, "
    "learned embeddings, and rotary position embeddings (RoPE) each trade off "
    "extrapolation, training stability, and length generalization differently.",
    "Scaling laws relate loss to parameter count, dataset size, and compute. Kaplan et "
    "al. and the Chinchilla analysis argued that many models were under-trained relative "
    "to their size, motivating balanced scaling of data and parameters.",
    "Mixture-of-experts layers route tokens to sparse expert FFNs, increasing capacity "
    "without proportional FLOPs per token. Load balancing and expert specialization "
    "remain active research problems for training stability.",
    "Context-window extension via YaRN, ALiBi, or continued pretraining on long "
    "documents aims to preserve short-context quality while enabling book-length "
    "reasoning and retrieval-free citation of earlier passages.",
    "Quantization (GPTQ, AWQ, bitsandbytes) and KV-cache compression reduce inference "
    "memory. Quality degradation is task-dependent: math and code often suffer more "
    "than short-form classification under aggressive 4-bit schemes.",
    "Instruction tuning aligns next-token predictors with user intents. High-quality "
    "curated datasets often outperform larger noisy mixtures for helpfulness, though "
    "diversity still matters for rare skills.",
]

# JSON corpus: evaluation, safety, and alignment findings
JSON_FINDINGS = [
    {
        "topic": "RLHF and preference modeling",
        "summary": (
            "Reinforcement learning from human feedback trains a reward model on "
            "ranked completions, then optimizes the policy with PPO or related "
            "methods. Reward hacking and sycophancy remain failure modes when the "
            "proxy diverges from true human preference."
        ),
        "methods": ["PPO", "reward modeling", "preference pairs"],
        "takeaway": "Preference data quality dominates algorithm choice at modest scale.",
    },
    {
        "topic": "Direct Preference Optimization",
        "summary": (
            "DPO reparameterizes the RLHF objective so the policy can be trained "
            "directly on preference pairs without a separate reward model. It simplifies "
            "pipelines but can overfit to preference noise without careful regularization."
        ),
        "methods": ["DPO", "IPO", "KTO"],
        "takeaway": "Offline preference objectives reduce infra complexity for labs.",
    },
    {
        "topic": "Constitutional AI",
        "summary": (
            "Models critique and revise their own outputs against written principles, "
            "reducing reliance on human labels for harmlessness. Principles must be "
            "precise; vague constitutions yield inconsistent refusals."
        ),
        "methods": ["self-critique", "AI feedback", "principle sets"],
        "takeaway": "Written constitutions scale harmlessness labeling.",
    },
    {
        "topic": "Benchmark saturation",
        "summary": (
            "MMLU, GSM8K, and HumanEval approach ceilings for frontier models, "
            "compressing discriminative signal. Contaminated evaluation sets inflate "
            "reported gains; held-out and dynamic benchmarks are increasingly required."
        ),
        "methods": ["MMLU", "GSM8K", "HumanEval", "LiveCodeBench"],
        "takeaway": "Static benchmarks understate capability differences among top models.",
    },
    {
        "topic": "Jailbreaks and adversarial prompts",
        "summary": (
            "Gradient-based and human-crafted jailbreaks bypass safety filters by "
            "reframing harmful requests as role-play, encoding, or hypotheticals. "
            "Defense-in-depth combines refusal training, classifiers, and runtime monitors."
        ),
        "methods": ["GCG", "PAIR", "circuit breakers"],
        "takeaway": "No single training fix eliminates adaptive attacks.",
    },
    {
        "topic": "Tool use and agents",
        "summary": (
            "Toolformer-style and ReAct-style agents interleave reasoning with API "
            "calls. Reliability hinges on schema adherence, recovery from tool errors, "
            "and limiting open-ended loops that amplify hallucinations."
        ),
        "methods": ["ReAct", "tool schemas", "function calling"],
        "takeaway": "Grounded tools reduce hallucination when APIs are trustworthy.",
    },
]

# CSV corpus: benchmark / ablation study rows
CSV_STUDIES = [
    (
        "attention_ablation",
        "Vaswani et al. style multi-head width study",
        "Perplexity improves with more heads up to a plateau; very narrow heads lose "
        "syntactic tracking on long dependencies.",
    ),
    (
        "chinchilla_compute",
        "Optimal tokens-per-parameter under fixed FLOPs",
        "Under-trained large models waste compute; equal loss isoquants favor more "
        "tokens for a given parameter budget.",
    ),
    (
        "rope_extrapolation",
        "RoPE base frequency and long-context eval",
        "Increasing RoPE base or using YaRN recovers Needle-in-a-Haystack accuracy "
        "beyond the original training length with modest fine-tuning.",
    ),
    (
        "rlhf_vs_dpo",
        "Helpfulness and honesty preference win rates",
        "DPO matches PPO helpfulness on in-distribution prompts; PPO retains an edge "
        "on out-of-distribution creative writing in some suites.",
    ),
    (
        "rag_vs_long_context",
        "Open-domain QA with retrieval versus 128k context",
        "Dense retrieval with reranking beats naive long-context stuffing on corpus "
        "QA when documents exceed cache-friendly lengths.",
    ),
    (
        "quantization_gsm8k",
        "INT4 weight-only math reasoning retention",
        "AWQ preserves GSM8K better than naive round-to-nearest; code generation "
        "shows larger drops than short-answer science questions.",
    ),
    (
        "moe_routing",
        "Expert load balance and downstream MMLU",
        "Auxiliary load-balancing losses reduce dead experts; over-balancing can "
        "hurt specialization on niche STEM topics.",
    ),
    (
        "speculative_decoding",
        "Draft model acceptance rate vs wall-clock",
        "A well-matched draft model yields 1.5–3× tokens/sec with negligible quality "
        "change when verification uses the target model logits.",
    ),
]

# Markdown: RAG, retrieval, and grounding literature notes
MD_SECTIONS = [
    (
        "Dense Retrieval for Grounding",
        "Dense passage retrievers map queries and documents into a shared embedding "
        "space. Contrastive training on question–passage pairs enables semantic match "
        "beyond lexical overlap, which is essential for paraphrased scientific claims.",
        "Hybrid BM25 + dense retrieval often wins on technical corpora where rare "
        "entity names must still match exactly.",
    ),
    (
        "Chunking Strategies",
        "Chunk size and overlap control recall versus precision in RAG. Too-small "
        "chunks lose discourse; too-large chunks dilute embeddings and waste context. "
        "Structure-aware splits (headings, code fences) outperform fixed windows.",
        "Parent-document retrieval returns small chunks for matching but expands to "
        "surrounding sections for generation.",
    ),
    (
        "Reranking and Compression",
        "Cross-encoder rerankers rescore top-k hits with full query–document attention. "
        "Contextual compression and LLM extractors trim retrieved text so the generator "
        "sees only claim-supporting sentences.",
        "Reranking gains are largest when the first-stage retriever is recall-oriented.",
    ),
    (
        "Attribution and Faithfulness",
        "Faithfulness metrics check whether generated statements are entailed by "
        "retrieved evidence. Citation markers help users verify claims but do not "
        "guarantee correct grounding without explicit attribution training.",
        "Self-consistency across sampled answers can flag unsupported numeric claims.",
    ),
    (
        "Multimodal Retrieval",
        "Vision–language models retrieve figures and tables alongside text. ColBERT-style "
        "late interaction and CLIP-style dual encoders offer different latency–recall "
        "tradeoffs for slide decks and paper PDFs.",
        "OCR quality remains a bottleneck for scanned proceedings and whiteboard photos.",
    ),
]

# PNG OCR lines: concise research captions (unique theme: interpretability)
PNG_LINES = [
    "Mechanistic interpretability maps circuits inside transformers to algorithms.",
    "Induction heads copy prior token patterns and enable in-context learning.",
    "Activation patching localizes which layers carry factual associations.",
    "Sparse autoencoders aim to disentangle polysemantic neuron activations.",
    "Attention knockout experiments test whether heads are necessary for a behavior.",
    "Logit lens reads intermediate residual streams as vocabulary distributions.",
    "Causal scrubbing validates that a proposed circuit actually explains a task.",
    "Representation engineering steers concepts via linear directions in activation space.",
    "Grokking shows delayed generalization after prolonged overfitting on small data.",
    "Superposition packs many features into fewer dimensions than the feature count.",
]

# Easy PDF: pretraining, tokenization, data curation
PDF_EASY_PARAS = [
    "Byte-pair encoding and SentencePiece tokenize text into subword units, balancing "
    "vocabulary size against sequence length. Poor tokenization of code or non-English "
    "scripts wastes context and harms sample efficiency.",
    "Pretraining corpora mix web text, books, code, and academic PDFs. Deduplication, "
    "quality filtering, and PII scrubbing strongly affect downstream safety and factuality.",
    "Masked language modeling (BERT) and causal language modeling (GPT) induce different "
    "representations. Decoder-only causal LMs dominate generative assistants despite "
    "bidirectional encoders remaining useful for embedding models.",
    "Warmup, cosine decay, and AdamW weight decay stabilize large runs. Gradient "
    "clipping and mixed precision (bf16) are standard; loss spikes often trace to "
    "data pathologies or learning-rate mistakes.",
    "Continued pretraining on domain text (law, biomedicine, code) shifts the prior "
    "before instruction tuning. Catastrophic forgetting of general skills can be "
    "mitigated with replay mixtures.",
    "Synthetic data from stronger teachers expands rare reasoning traces, but "
    "self-training on model outputs can amplify style artifacts and hidden biases "
    "unless filtered against verified solutions.",
]

# Complex PDF: multimodal + systems tables
PDF_COMPLEX_ROWS = [
    ("GPT-4V", "vision+text", "strong", "diagrams, UI, charts"),
    ("LLaVA", "CLIP+LLM", "open", "instruction-tuned VLM"),
    ("Flamingo", "gated x-attn", "few-shot", "interleaved image-text"),
    ("Kosmos", "multimodal", "grounding", "perception-language"),
    ("Whisper", "speech→text", "robust", "multilingual ASR"),
    ("MusicLM", "audio gen", "cascade", "text-to-music"),
    ("DiT", "diffusion", "latents", "transformer denoiser"),
    ("SAM", "segmentation", "promptable", "vision foundation"),
]

PDF_COMPLEX_CAPTIONS = [
    "Figure: Latency versus tokens/sec for speculative decoding with matched draft models.",
    "Figure: Expert utilization histogram under different load-balancing coefficients.",
    "Table notes: Open multimodal models still trail proprietary systems on chart QA.",
    "Discussion: Unified embedding spaces simplify cross-modal retrieval for study tools.",
    "Systems note: Continuous batching and paged attention dominate serving efficiency.",
]


def _cycle(items: list, i: int):
    return items[i % len(items)]


# ---------------------------------------------------------------------------
# Fixture generators
# ---------------------------------------------------------------------------


def generate_txt(path: Path, target: int, run_id: str = "run") -> None:
    """Survey-style notes on transformers, attention, and scaling laws."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(
            "A Working Survey of Large Language Model Foundations\n"
            f"(fixture run_id={run_id})\n\n"
            "This note collects readable research commentary on architectures that "
            "underpin contemporary LLMs. Each section expands a distinct idea so the "
            "document remains useful for retrieval and study, not only load testing.\n\n"
        )
        i = 0
        while f.tell() < target:
            para = _cycle(TXT_PARAS, i)
            f.write(f"{i + 1}. {para}\n\n")
            f.write(
                f"   Elaborating further ({run_id}/{i}): researchers compare wall-clock "
                f"training efficiency, inference latency, and downstream transfer when "
                f"varying depth, width, and data mixture. Related reading often cites "
                f"attention variants, optimizer choices, and evaluation contamination "
                f"controls for claim {i + 1}.\n\n"
            )
            i += 1


def generate_json(path: Path, target: int, run_id: str = "run") -> None:
    """Structured findings on alignment, evaluation, and agents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    i = 0
    while True:
        base = _cycle(JSON_FINDINGS, i)
        records.append(
            {
                "id": f"{run_id}-{i}",
                "corpus": "llm_alignment_eval",
                "topic": base["topic"],
                "summary": base["summary"],
                "methods": base["methods"],
                "takeaway": base["takeaway"],
                "discussion": (
                    f"Entry {i} expands on {base['topic']} for study-buddy retrieval. "
                    f"Practitioners should track dataset provenance, judge–model bias, "
                    f"and whether reported gains survive fresh prompts outside the "
                    f"original preference distribution. Cross-check against related "
                    f"work on {_cycle(JSON_FINDINGS, i + 1)['topic']}."
                ),
                "open_questions": [
                    f"How stable is {base['topic']} under distribution shift?",
                    "Which automatic judges correlate with expert labels?",
                    "What failure modes appear only at deployment scale?",
                ],
            }
        )
        i += 1
        blob = json.dumps(
            {
                "title": "LLM Alignment and Evaluation Digest",
                "run_id": run_id,
                "documents": records,
            },
            indent=2,
        ).encode("utf-8")
        if len(blob) >= target:
            path.write_bytes(blob)
            return


def generate_csv(path: Path, target: int, run_id: str = "run") -> None:
    """Benchmark / ablation study table with readable research notes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "study_id",
        "run_id",
        "experiment",
        "focus",
        "metric_name",
        "metric_value",
        "params_b",
        "tokens_b",
        "notes",
    ]
    metrics = [
        ("perplexity", 12.4),
        ("mmlu", 0.71),
        ("gsm8k", 0.58),
        ("humaneval", 0.44),
        ("win_rate", 0.62),
        ("latency_ms", 38.0),
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        i = 0
        while f.tell() < target:
            key, focus, note = _cycle(CSV_STUDIES, i)
            metric_name, metric_base = _cycle(metrics, i)
            writer.writerow(
                [
                    f"{key}_{i}",
                    run_id,
                    key,
                    focus,
                    metric_name,
                    round(metric_base + (i % 17) * 0.01, 4),
                    7 + (i % 65),
                    140 + (i * 3) % 400,
                    (
                        f"{note} Study row {i} documents how {focus.lower()} interacts "
                        f"with {metric_name} under controlled ablations. Interpret "
                        f"gains cautiously when evaluation sets may overlap pretraining."
                    ),
                ]
            )
            i += 1


def generate_md(path: Path, target: int, run_id: str = "run") -> None:
    """Markdown literature notes on RAG, retrieval, and grounding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(
            "# Retrieval-Augmented Generation: Research Notes\n\n"
            f"*run_id={run_id}*\n\n"
            "These notes summarize practical research themes for grounding LLMs on "
            "external knowledge. Sections are written to be independently retrievable.\n\n"
        )
        i = 0
        while f.tell() < target:
            title, body, tip = _cycle(MD_SECTIONS, i)
            f.write(f"## {i + 1}. {title}\n\n")
            f.write(f"{body}\n\n")
            f.write(f"**Practice tip:** {tip}\n\n")
            f.write(
                f"| Aspect | Guidance |\n| --- | --- |\n"
                f"| Indexing | Prefer semantic chunk IDs stable across re-embeds |\n"
                f"| Evaluation | Measure answer faithfulness, not only BLEU/ROUGE |\n"
                f"| Failure mode | Retrieved-but-ignored context still yields fluent errors |\n\n"
            )
            f.write(
                "```text\n"
                f"query → retrieve(k) → rerank → compress → generate → cite\n"
                f"# iteration {i} / {run_id}\n"
                "```\n\n"
            )
            i += 1


def generate_text_rich_png(path: Path, target: int, run_id: str = "run") -> None:
    """Text-rich PNG on mechanistic interpretability (OCR-friendly)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1200, 1600
    attempt = 0
    while True:
        img = Image.new("RGB", (width, height), color=(248, 246, 240))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 17
            )
            title_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26
            )
        except OSError:
            font = ImageFont.load_default()
            title_font = font

        draw.text(
            (40, 28),
            "Mechanistic Interpretability Brief",
            fill=(20, 40, 60),
            font=title_font,
        )
        draw.text(
            (40, 62),
            f"Readable OCR fixture · run {run_id} · pass {attempt}",
            fill=(60, 60, 60),
            font=font,
        )
        y = 100
        line_idx = 0
        while y < height - 40:
            line = _cycle(PNG_LINES, line_idx)
            # Wrap-ish by truncating long lines for canvas width
            draw.text(
                (40, y),
                f"{line_idx + 1:02d}. {line}",
                fill=(30, 30, 30),
                font=font,
            )
            y += 24
            if line_idx % 5 == 4:
                draw.text(
                    (40, y),
                    (
                        f"    Note: circuit analyses should state the exact task, "
                        f"model family, and intervention used (n={line_idx})."
                    ),
                    fill=(50, 50, 70),
                    font=font,
                )
                y += 24
            line_idx += 1

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
        width = int(width * 1.25)
        height = int(height * 1.25)
        attempt += 1
        if attempt > 12:
            raise RuntimeError(
                f"Could not grow PNG to {target} bytes (got {size})"
            )


def generate_pdf_easy(path: Path, target: int, run_id: str = "run") -> None:
    """Text PDF primer on pretraining, tokenization, and data curation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page_n = 0
    para_i = 0
    while True:
        page = doc.new_page(width=612, height=792)
        page_n += 1
        y = 48
        page.insert_text(
            (36, y),
            f"LLM Pretraining Primer ({run_id}) — page {page_n}",
            fontsize=13,
        )
        y += 28
        while y < 740:
            para = _cycle(PDF_EASY_PARAS, para_i)
            # PyMuPDF insert_text does not wrap; emit shorter lines
            words = (
                f"[{para_i + 1}] {para} "
                f"Additional context for page {page_n}: compare filtering "
                f"pipelines, tokenizer fertility, and validation loss curves."
            ).split()
            line = ""
            for w in words:
                trial = f"{line} {w}".strip()
                if len(trial) > 95:
                    page.insert_text((36, y), line, fontsize=9)
                    y += 12
                    line = w
                    if y >= 740:
                        break
                else:
                    line = trial
            if y < 740 and line:
                page.insert_text((36, y), line, fontsize=9)
                y += 16
            para_i += 1
            if y >= 740:
                break
        if page_n % 3 == 0:
            doc.save(path, deflate=True, garbage=1)
            if path.stat().st_size >= target:
                doc.close()
                return
    doc.save(path, deflate=True, garbage=1)
    doc.close()


def generate_pdf_complex(path: Path, target: int, run_id: str = "run") -> None:
    """PDF survey with multimodal model tables + supporting figures."""
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
            f"Multimodal LLM Systems Survey ({run_id}) — p.{page_n}",
            fontsize=12,
        )
        y += 22
        page.insert_text(
            (36, y),
            _cycle(PDF_COMPLEX_CAPTIONS, page_n),
            fontsize=9,
        )
        y += 20
        page.insert_text(
            (36, y),
            "Model | Modality | Strength | Typical use",
            fontsize=9,
        )
        y += 14
        for row in range(16):
            model, modality, strength, use = _cycle(
                PDF_COMPLEX_ROWS, page_n + row
            )
            page.insert_text(
                (36, y),
                f"{model} | {modality} | {strength} | {use} | row {row}",
                fontsize=8,
            )
            y += 12
            if y > 480:
                break

        page.insert_text(
            (36, y + 4),
            (
                "Discussion: serving stacks combine continuous batching, paged KV "
                "cache, and speculative decoding; multimodal inputs increase "
                "prefill cost and memory fragmentation."
            ),
            fontsize=8,
        )

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


GENERATORS: dict[str, tuple[Callable[..., None], str, str]] = {
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

    # python scripts/load_test_ingest.py --email chi@gmail.com --password 'Password@1' --profile quick
# larger: --profile medium | --profile full
