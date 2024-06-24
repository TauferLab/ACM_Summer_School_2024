#!/bin/bash

#export PYPI_USERNAME="..."
#export PYPI_PASSWORD="..."

TAG=$(python3 scripts/new_tag.py) && echo ${TAG}

git commit -a -m "New tag ($TAG)" 
git tag -a $TAG -m "$TAG"
git push origin $TAG
git push origin

rm -f dist/*  
python -m build .
python -m twine upload --username "${PYPI_USERNAME}"  --password "${PYPI_PASSWORD}" --skip-existing "dist/*.whl" --verbose 