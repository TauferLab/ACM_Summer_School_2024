#!/bin/bash

# Define the directory name
DIR="openvisuspy"

if [ -d "$DIR" ]; then
    echo "Removing existing $DIR directory..."
    rm -rf "$DIR"
fi
echo "Cloning the openvisuspy repository..."
git clone --single-branch -b nsdf-ahm https://github.com/sci-visus/openvisuspy.git
cd  openvisuspy

echo "export PATH=\$PATH:$(pwd)/src" >> ~/.bashrc
echo "export PYTHONPATH=\$PYTHONPATH:$(pwd)/src" >> ~/.bashrc
echo "export BOKEH_ALLOW_WS_ORIGIN='*'"
echo "export BOKEH_RESOURCES='cdn'"
echo "export VISUS_CACHE=/tmp/visus-cache/nsdf-services/somospie"


echo "export VISUS_CPP_VERBOSE=1"
echo "export VISUS_NETSERVICE_VERBOSE=1"
echo "export VISUS_VERBOSE_DISKACCESS=1"
. ~/.bashrc

echo "Setup completed."
