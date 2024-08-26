FROM --platform=linux/amd64 continuumio/miniconda3:23.10.0-1

RUN mkdir app
WORKDIR /app


COPY *.ipynb /app/
COPY environment.yml /app/

# Install base utilities
RUN apt-get update \
    && apt-get install -y build-essential \
    && apt-get install -y wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN conda env create -f environment.yml
SHELL ["conda", "run", "-n", "NSDF-Tutorial", "/bin/bash", "-c"]

RUN pip install openvisus
RUN conda init