#!/usr/bin/env bash
set -o errexit

# On force Playwright à installer Chrome DANS le dossier du projet
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/src/.playwright

pip install -r requirements.txt
