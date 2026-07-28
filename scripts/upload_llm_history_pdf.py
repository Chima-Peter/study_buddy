#!/usr/bin/env python3
"""Generate a detailed LLM-history PDF and upload it through the ingest API."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib import error, request

import fitz

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "scripts" / "fixtures" / "llm_history" / "history_of_llms.pdf"
DEFAULT_BASE = "http://127.0.0.1:8080/api"

CHAPTERS: list[tuple[str, list[str]]] = [
    (
        "Chapter 1 — Precursors: From Cybernetics to Connectionism (1940s–1980s)",
        [
            (
                "1.1 The intellectual backdrop"
            ),
            (
                "Before large language models existed as a product category, the "
                "conceptual ingredients were already being assembled across "
                "mathematics, neuroscience, and early computing. Claude Shannon's "
                "information theory (1948) framed communication as the "
                "transmission of symbols under uncertainty, introducing entropy "
                "and channel capacity as quantitative tools. Alan Turing's "
                "questions about machine intelligence and computability "
                "established that symbol manipulation could, in principle, "
                "simulate aspects of reasoning. Meanwhile, Warren McCulloch and "
                "Walter Pitts (1943) proposed simplified neural units as logical "
                "devices, linking biological inspiration to discrete computation."
            ),
            (
                "1.2 Perceptrons and the first neural boom"
            ),
            (
                "Frank Rosenblatt's Perceptron (late 1950s) operationalized "
                "learning as weight adjustment from labeled examples. Early "
                "demonstrations were striking enough to attract funding and "
                "media attention, but the models were linear classifiers. The "
                "famous critique by Minsky and Papert (1969) clarified "
                "limitations of single-layer perceptrons on non-linearly "
                "separable problems such as XOR. That critique did not kill "
                "neural research forever, but it redirected much of the field "
                "toward symbolic AI, expert systems, and hand-engineered "
                "knowledge representations throughout the 1970s."
            ),
            (
                "1.3 Backpropagation and distributed representations"
            ),
            (
                "The revival of connectionism in the 1980s rested on multilayer "
                "networks trained with backpropagation. Rumelhart, Hinton, and "
                "Williams popularized practical gradient-based training for "
                "hidden layers, enabling networks to learn internal features "
                "rather than relying solely on engineered inputs. Parallel "
                "Distributed Processing (PDP) argued that cognition could emerge "
                "from many simple units interacting, and that meaning could be "
                "encoded as patterns across vectors rather than as atomic "
                "symbols alone. These ideas later became foundational for "
                "embeddings in NLP: words and contexts as points in continuous "
                "spaces."
            ),
            (
                "1.4 Why this chapter matters for LLMs"
            ),
            (
                "Modern LLMs inherit three durable commitments from this era: "
                "(1) learning from data rather than only writing rules; "
                "(2) representing knowledge in high-dimensional continuous "
                "spaces; and (3) using gradient-based optimization as the "
                "default training paradigm. They also inherit the field's "
                "recurring boom–bust pattern: ambitious claims, compute or data "
                "bottlenecks, skepticism, then a new substrate that unlocks "
                "another leap. Understanding those cycles helps explain why "
                "Transformers felt sudden in 2017 even though their mathematical "
                "and conceptual ancestors were decades old."
            ),
        ],
    ),
    (
        "Chapter 2 — Statistical NLP and the Rise of Embeddings (1990s–2013)",
        [
            (
                "2.1 Language as probability"
            ),
            (
                "As symbolic AI struggled with the open-ended messiness of "
                "natural language, statistical approaches gained ground. "
                "n-gram language models estimated the probability of the next "
                "token from local history, powering speech recognition and "
                "early machine translation. Smoothing techniques, backoff, and "
                "interpolation addressed sparsity. The IBM translation models "
                "and later phrase-based SMT treated translation as decoding "
                "under noisy-channel assumptions. Evaluation moved toward "
                "automatic metrics and held-out likelihood, creating a culture "
                "of measurable incremental progress."
            ),
            (
                "2.2 Feature-rich discriminative models"
            ),
            (
                "Conditional Random Fields, maximum-entropy classifiers, and "
                "structured prediction systems dominated many tagging and "
                "parsing benchmarks. These systems were powerful but brittle: "
                "features were hand-designed (prefixes, POS tags, gazetteers), "
                "and generalization depended on linguistic engineering. The "
                "tension became clear: more features improved in-domain scores, "
                "yet transferring to new domains remained expensive. Neural "
                "methods promised to learn features automatically, but for "
                "years they were competitive mainly when carefully tuned."
            ),
            (
                "2.3 Distributional semantics and word vectors"
            ),
            (
                "A decisive conceptual shift was distributional semantics: a "
                "word's meaning is shaped by the company it keeps. Count-based "
                "methods (LSA, HAL) built co-occurrence matrices and reduced "
                "them with SVD. Then word2vec (Mikolov et al., 2013) and "
                "GloVe popularized efficient predictive or ratio-based "
                "embeddings that captured analogies and semantic similarity "
                "with surprising regularity. Suddenly, NLP pipelines could "
                "initialize with dense vectors that transferred across tasks. "
                "This was not yet a full language model in the modern sense, "
                "but it normalized the idea that text should be computed on "
                "as geometry."
            ),
            (
                "2.4 Bridging to neural sequence models"
            ),
            (
                "By the early 2010s, GPUs, larger corpora, and better toolkits "
                "made neural nets practical again. Embeddings became the "
                "interface layer between classical NLP tasks and deep models. "
                "Researchers began replacing discrete feature templates with "
                "learned representations while keeping task-specific "
                "architectures. The stage was set for sequence models that "
                "could consume variable-length text end-to-end—first with "
                "recurrence, then with attention."
            ),
        ],
    ),
    (
        "Chapter 3 — Sequence Modeling: RNNs, Seq2Seq, and Attention (2014–2017)",
        [
            (
                "3.1 Recurrence as memory"
            ),
            (
                "Recurrent neural networks process tokens step by step, "
                "maintaining a hidden state that summarizes prior context. In "
                "theory this provides unbounded history; in practice vanishing "
                "and exploding gradients limited depth and long-range "
                "dependencies. LSTMs (Hochreiter & Schmidhuber, 1997) and GRUs "
                "re-entered the mainstream around 2014–2015 as practical "
                "remedies, using gated memory cells to preserve information "
                "over longer spans. Neural language models began to outperform "
                "carefully smoothed n-grams on perplexity when given enough "
                "data and compute."
            ),
            (
                "3.2 Encoder–decoder machine translation"
            ),
            (
                "The seq2seq framework (Sutskever et al.; Cho et al.) mapped "
                "a source sentence to a fixed vector, then decoded a target "
                "sentence token by token. This end-to-end framing was "
                "intellectually clean and empirically strong, but the fixed "
                "bottleneck vector struggled with long sentences. Attention "
                "mechanisms (Bahdanau et al., 2015; Luong et al.) let the "
                "decoder look back over encoder states dynamically, aligning "
                "source and target positions. Attention was initially an "
                "engineering fix for translation; conceptually, it reframed "
                "context access as content-based addressing rather than only "
                "sequential compression."
            ),
            (
                "3.3 Character models, CNNs, and multitask learning"
            ),
            (
                "Parallel lines of work explored character-aware models, "
                "convolutional sentence encoders, and multitask objectives "
                "that shared representations across tagging, parsing, and "
                "classification. ELMo (2018, slightly after this chapter's "
                "core window but continuous with it) showed that deep "
                "bidirectional LM states could be frozen or lightly adapted "
                "as contextual embeddings, outperforming static word2vec. The "
                "field was converging on a thesis: pretraining on language "
                "modeling yields general-purpose textual features."
            ),
            (
                "3.4 Limits of recurrence at scale"
            ),
            (
                "RNNs are inherently sequential along time, which constrains "
                "parallelism. Training on long documents is slow; batching "
                "helps but does not remove the step-by-step dependency in the "
                "forward/backward pass. Researchers increasingly asked whether "
                "attention alone—without recurrence—could model sequences if "
                "positional information were injected another way. That "
                "question produced the Transformer, and with it a new scaling "
                "curve for NLP."
            ),
        ],
    ),
    (
        "Chapter 4 — The Transformer Revolution and Bidirectional Pretraining (2017–2020)",
        [
            (
                "4.1 Attention Is All You Need"
            ),
            (
                "Vaswani et al. (2017) introduced the Transformer: stacked "
                "self-attention and feed-forward blocks with residual "
                "connections and layer normalization. Multi-head attention "
                "lets the model jointly attend to information from different "
                "representation subspaces. Positional encodings supply order "
                "signals. Crucially, self-attention over a sequence can be "
                "computed in parallel across positions, matching GPU hardware "
                "far better than recurrence. Machine translation quality "
                "jumped, but the deeper impact was architectural "
                "standardization: one flexible backbone for many sequence "
                "problems."
            ),
            (
                "4.2 GPT: generative pretraining"
            ),
            (
                "OpenAI's GPT (2018) pretrained a Transformer decoder with "
                "next-token prediction, then fine-tuned on discriminative "
                "tasks. The paper emphasized that a single unsupervised "
                "objective plus task-specific heads could rival specialized "
                "architectures. GPT-2 (2019) scaled parameters and data "
                "substantially, demonstrating coherent long-form generation "
                "and zero-shot task behavior via prompting. This shifted "
                "expectations: maybe the right pretrained generative model "
                "already contains latent skills that prompting can elicit."
            ),
            (
                "4.3 BERT and the masked language modeling wave"
            ),
            (
                "BERT (Devlin et al., 2018) used bidirectional encoders with "
                "masked language modeling and next-sentence prediction, then "
                "fine-tuned to SOTA on GLUE and other benchmarks. The success "
                "triggered an explosion of variants: RoBERTa, ALBERT, "
                "DistilBERT, SpanBERT, and multilingual models. Sentence-piece "
                "and WordPiece tokenization became default infrastructure. "
                "Transfer learning in NLP stopped being optional; it became "
                "the default recipe. Encoder-only models excelled at "
                "understanding tasks, while decoder-only models pushed "
                "open-ended generation."
            ),
            (
                "4.4 Scaling laws enter the conversation"
            ),
            (
                "By 2019–2020, labs observed relatively smooth improvements "
                "with model size, dataset size, and compute. T5 reframed NLP "
                "as text-to-text. Reformer, Longformer, and sparse attention "
                "variants attacked quadratic cost. The intellectual center of "
                "gravity moved from crafting task architectures to asking how "
                "far scale plus simple objectives would go. That question "
                "set up GPT-3 and the modern LLM product era."
            ),
        ],
    ),
    (
        "Chapter 5 — Large Language Models at Scale and Alignment (2020–Present)",
        [
            (
                "5.1 Few-shot learning and the GPT-3 moment"
            ),
            (
                "GPT-3 (2020) argued that sufficiently large autoregressive "
                "models exhibit in-context learning: tasks specified in the "
                "prompt, with little or no gradient updates. This reframed "
                "interfaces around natural language instructions and examples. "
                "It also surfaced new issues—hallucination, bias amplification, "
                "prompt sensitivity, and the economics of API-mediated access. "
                "Capability jumps began to feel discontinuous to users even "
                "when underlying scaling curves were smoother."
            ),
            (
                "5.2 Instruction tuning and RLHF"
            ),
            (
                "Raw next-token models optimize for document continuation, not "
                "helpfulness. InstructGPT and related work used supervised "
                "instruction data plus reinforcement learning from human "
                "feedback (RLHF) to steer models toward preferred responses. "
                "ChatGPT popularized conversational alignment for mainstream "
                "audiences. Subsequent recipes explored RLAIF, direct "
                "preference optimization (DPO), constitutional principles, and "
                "tool-use fine-tuning. Alignment became both a safety agenda "
                "and a product quality agenda."
            ),
            (
                "5.3 Open models, multimodality, and agents"
            ),
            (
                "LLaMA, Mistral, Falcon, and other open-weight families "
                "broadened who can train, fine-tune, and evaluate LLMs. "
                "Mixture-of-experts architectures improved parameter "
                "efficiency. Multimodal models linked text to images, audio, "
                "and video. Retrieval-augmented generation connected "
                "parametric memory with external corpora—exactly the pattern "
                "many study assistants now use. Agent frameworks wrapped "
                "models in planning loops with tools, browsers, and code "
                "execution, shifting the unit of value from a single completion "
                "to a multi-step workflow."
            ),
            (
                "5.4 Open problems and historical continuity"
            ),
            (
                "Despite extraordinary progress, core problems remain: "
                "reliable factuality, long-horizon reasoning, privacy, "
                "evaluation beyond static benchmarks, energy cost, and "
                "governance. Historically, each LLM wave reused older ideas—"
                "distributional semantics, likelihood training, attention, "
                "transfer learning—under new compute regimes. The deepest "
                "lesson of LLM history may be that data, architecture, and "
                "objectives co-evolve with hardware. Understanding that "
                "trajectory helps practitioners choose systems wisely: when "
                "to retrieve, when to fine-tune, when to distrust fluent "
                "text, and how today's 'breakthrough' sits on a long "
                "scientific shelf rather than appearing from nowhere."
            ),
        ],
    ),
]


def build_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    width, height = fitz.paper_size("a4")
    margin = 54
    title_size = 18
    heading_size = 13
    body_size = 11
    leading = 15

    # Cover
    page = doc.new_page(width=width, height=height)
    page.insert_textbox(
        fitz.Rect(margin, 180, width - margin, 260),
        "A Concise Deep History of Large Language Models",
        fontsize=22,
        fontname="helv",
        align=1,
    )
    page.insert_textbox(
        fitz.Rect(margin, 270, width - margin, 340),
        "Five chapters on the ideas, architectures, and scaling regimes\n"
        "that produced modern LLMs — from cybernetics to alignment.",
        fontsize=12,
        fontname="helv",
        align=1,
    )
    page.insert_textbox(
        fitz.Rect(margin, 720, width - margin, 760),
        "StudyBuddy ingest fixture · generated for retrieval evaluation",
        fontsize=9,
        fontname="helv",
        align=1,
    )

    for chapter_title, sections in CHAPTERS:
        page = doc.new_page(width=width, height=height)
        y = margin
        used = page.insert_textbox(
            fitz.Rect(margin, y, width - margin, y + 60),
            chapter_title,
            fontsize=title_size,
            fontname="helv",
            align=0,
        )
        y += 70 if used >= 0 else 80

        for block in sections:
            is_heading = block[:2].isdigit() and "." in block[:4]
            size = heading_size if is_heading else body_size
            font = "helv"
            # Estimate needed height roughly by wrapping.
            words = block.split()
            approx_lines = max(1, (len(block) // 90) + 1)
            box_h = approx_lines * leading + (8 if is_heading else 4)
            if y + box_h > height - margin:
                page = doc.new_page(width=width, height=height)
                y = margin
            rect = fitz.Rect(margin, y, width - margin, min(height - margin, y + box_h + 40))
            leftover = page.insert_textbox(
                rect,
                block,
                fontsize=size,
                fontname=font,
                align=0,
            )
            # If text didn't fit, spill to new pages.
            text = block
            while leftover < 0:
                # crude continuation: new page with remaining text estimate
                page = doc.new_page(width=width, height=height)
                y = margin
                rect = fitz.Rect(margin, y, width - margin, height - margin)
                leftover = page.insert_textbox(
                    rect,
                    text,
                    fontsize=size,
                    fontname=font,
                    align=0,
                )
                if leftover < 0:
                    # still overflowing; shrink chunk by writing shorter slices
                    # fallback: write character windows
                    chunk = text[:1800]
                    text = text[1800:]
                    page.insert_textbox(
                        fitz.Rect(margin, margin, width - margin, height - margin),
                        chunk,
                        fontsize=size,
                        fontname=font,
                        align=0,
                    )
                    if not text:
                        leftover = 0
                        break
                else:
                    y = height - margin
                    break
            else:
                y += box_h + (12 if is_heading else 10)

    doc.save(path)
    doc.close()
    return path


def http_json(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    data: dict | bytes | None = None,
    raw: bool = False,
    timeout: int = 120,
):
    body = None
    req_headers = dict(headers or {})
    if data is not None:
        if raw:
            body = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        else:
            body = json.dumps(data).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
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


def upload_and_ingest(
    *,
    base: str,
    token: str,
    pdf_path: Path,
    poll_timeout_s: int,
    poll_interval_s: float,
) -> int:
    auth = {"Authorization": f"Bearer {token}"}
    print(f"Uploading {pdf_path} ({pdf_path.stat().st_size} bytes)")
    status, upload = http_json(
        "POST",
        f"{base}/documents/upload",
        headers=auth,
        data={
            "name": "History of Large Language Models",
            "category": "history",
            "description": (
                "Five-chapter deep survey of LLM history: precursors, "
                "statistical NLP, sequence models, Transformers, and alignment."
            ),
            "file_name": pdf_path.name,
        },
    )
    if status != 200 or not isinstance(upload, dict):
        raise SystemExit(f"upload HTTP {status}: {upload}")

    data = upload["data"]
    doc_id = data["document"]["id"]
    signed_url = data["upload_url"]
    print(f"doc_id={doc_id}")

    put_status, put_body = http_json(
        "PUT",
        signed_url,
        headers={"Content-Type": "application/pdf"},
        data=pdf_path.read_bytes(),
        raw=True,
        timeout=900,
    )
    if put_status != 200:
        raise SystemExit(f"PUT HTTP {put_status}: {put_body}")
    print("PUT ok")

    status, ingest = http_json(
        "POST",
        f"{base}/documents/{doc_id}/ingest",
        headers=auth,
    )
    print(f"ingest HTTP={status}")
    if status not in (200, 202):
        raise SystemExit(f"ingest HTTP {status}: {ingest}")

    deadline = time.time() + poll_timeout_s
    final = "timeout"
    while time.time() < deadline:
        st, payload = http_json(
            "GET",
            f"{base}/documents/{doc_id}",
            headers=auth,
        )
        if st == 200 and isinstance(payload, dict):
            final = payload["data"]["status"]
            print(f"status={final}")
            if final in {"completed", "failed", "cancelled", "error"}:
                break
        time.sleep(poll_interval_s)

    print(f"final_status={final} doc_id={doc_id}")
    return 0 if final == "completed" else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--email", default="chi@gmail.com")
    p.add_argument("--password", default="12345678")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--generate-only", action="store_true")
    p.add_argument("--poll-timeout", type=int, default=600)
    p.add_argument("--poll-interval", type=float, default=2.0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    print("=== GENERATE PDF ===")
    path = build_pdf(args.out)
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    if args.generate_only:
        return 0

    print("\n=== LOGIN ===")
    token = login(args.base, args.email, args.password)
    print("ok")

    print("\n=== UPLOAD + INGEST ===")
    return upload_and_ingest(
        base=args.base,
        token=token,
        pdf_path=path,
        poll_timeout_s=args.poll_timeout,
        poll_interval_s=args.poll_interval,
    )


if __name__ == "__main__":
    sys.exit(main())
