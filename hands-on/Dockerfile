FROM --platform=linux/amd64 continuumio/miniconda3:23.10.0-1

RUN mkdir app
WORKDIR /app

COPY files/ /app/files/
COPY idx_data/ /app/idx_data/
COPY openvisuspy/ /app/openvisuspy/
COPY GEOtiled/geotiled /app/geotiled/
COPY Tutorial.ipynb /app/
COPY Explore_Data.ipynb /app/
COPY *.py /app/
COPY environment.yml /app/

# Install base utilities
RUN apt-get update \
    && apt-get install -y build-essential \
    && apt-get install -y wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install miniconda
# ENV CONDA_DIR /opt/conda
# RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda.sh && \
#     /bin/bash ~/miniconda.sh -b -p /opt/conda

# Put conda in path so we can use conda activate
#ENV PATH=$CONDA_DIR/bin:$PATH

#RUN conda update -n base conda && conda install -n base conda-libmamba-solver && conda config --set solver libmamba

WORKDIR /app

RUN conda env create -f environment.yml
SHELL ["conda", "run", "-n", "NSDF-Tutorial", "/bin/bash", "-c"]

RUN pip install openvisus

WORKDIR /app/geotiled/
RUN pip install -e .

WORKDIR /app/openvisuspy
RUN echo "export PATH=\$PATH:$(pwd)/src" >> ~/.bashrc && \
    echo "export PYTHONPATH=\$PYTHONPATH:$(pwd)/src" >> ~/.bashrc && \
    echo "export BOKEH_ALLOW_WS_ORIGIN='*'" && \
    echo "export BOKEH_RESOURCES='cdn'" && \
    echo "export VISUS_CACHE=/tmp/visus-cache/nsdf-services/somospie" && \
    echo "export VISUS_CPP_VERBOSE=1" && \
    echo "export VISUS_NETSERVICE_VERBOSE=1" && \
    echo "export VISUS_VERBOSE_DISKACCESS=1" && \
    . ~/.bashrc

WORKDIR /app

EXPOSE 8989 5000

RUN conda init
CMD ["conda", "run","-n", "NSDF-Tutorial","jupyter", "lab", "--port=5000", "--no-browser", "--ip=0.0.0.0", "--allow-root", "--NotebookApp.token=''","--NotebookApp.password=''"]
