FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        texlive-pictures \
        texlive-lang-portuguese \
        texlive-xetex \
        lmodern \
        fonts-inter \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pyyaml==6.0.2

WORKDIR /app
