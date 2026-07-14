FROM python:3.12-slim

RUN apt update && apt install -y \
  libmagic-dev \
  poppler-utils \
  tesseract-ocr \
  libreoffice \
  pandoc

RUN pip install "unstructured[all-docs]" \
  langchain-unstructured