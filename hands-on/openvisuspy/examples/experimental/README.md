
## (EXPERIMENTAL and DEPRECATED) Use Pure Python Backend

This version may be used for cpython too in case you cannot install C++ OpenVisus (e.g., WebAssembly).

It **will not work with S3 cloud-storage blocks**.

Bokeh dashboards:

```
python3 -m bokeh serve "dashboards"  --dev --address localhost --port 8888 --args --py  --single
python3 -m bokeh serve "dashboards"  --dev --address localhost --port 8888 --args --py  --multi
```

Panel dashboards:

```
python -m panel serve "dashboards"  --dev --address localhost --port 8888 --args --py --single
python -m panel serve "dashboards"  --dev --address localhost --port 8888 --args --py --multi
```

Jupyter notebooks:

```
export VISUS_BACKEND=py
python3 -m jupyter notebook ./examples/notebooks
```

### Demos

REMEMBER to resize the browswe  window, **otherwise it will not work**:

- https://scrgiorgio.it/david_subsampled.html
- https://scrgiorgio.it/2kbit1.html
- https://scrgiorgio.it/chess_zip.html

DEVELOPERS notes:
- grep for `openvisuspy==` and **change the version consistently**.

### PyScript

Serve local directory

```
export VISUS_BACKEND=py
python3 examples/server.py --directory ./
```

Open the urls in your Google Chrome browser:

- http://localhost:8000/examples/pyscript/index.html 
- http://localhost:8000/examples/pyscript/2kbit1.html 
- http://localhost:8000/examples/pyscript/chess_zip.html 
- http://localhost:8000/examples/pyscript/david_subsampled.html

### JupyterLite

```
export VISUS_BACKEND=py
ENV=/tmp/openvisuspy-lite-last
python3 -m venv ${ENV}
source ${ENV}/bin/activate

# Right now jupyter lite seems to build the output based on installed packages. 
# There should be other ways (e.g., JSON file or command line) for specifying packages, but for now creating a virtual env is good enough\
# you need to have exactly the same package version inside your jupyter notebook (see `12-jupyterlite.ipynb`)
python3 -m pip install \
    jupyterlite==0.1.0b20 pyviz_comms numpy pandas requests xmltodict xyzservices pyodide-http colorcet \
    https://cdn.holoviz.org/panel/0.14.3/dist/wheels/bokeh-2.4.3-py3-none-any.whl \
    panel==0.14.2 \
    openvisuspy==1.0.100 \
    jupyter_server 

rm -Rf ${ENV}/_output 
jupyter lite build --contents /mnt/c/projects/openvisuspy/examples/notebooks --output-dir ${ENV}/_output

# change port to avoid caching
PORT=14445
python3 -m http.server --directory ${ENV}/_output --bind localhost ${PORT}

# or serve
jupyter lite serve --contents ./examples/notebooks --output-dir ${ENV}/_output --port ${PORT} 

# copy the files somewhere for testing purpouse
rsync -arv ${ENV}/_output/* <username>@<hostname>:jupyterlite-demos/
```

