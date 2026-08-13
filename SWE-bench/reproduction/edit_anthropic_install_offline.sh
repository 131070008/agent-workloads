#!/usr/bin/env bash
# This file is sourced into SWE-ReX's long-lived shell; do not change shell options.
REX_PYTHON=/opt/swerex-runtime/bin/python
REX_SITE=/opt/swerex-runtime/lib/python3.11/site-packages
"$REX_PYTHON" -c 'import tree_sitter, tree_sitter_languages' || return $?
export PYTHONPATH="$REX_SITE${PYTHONPATH:+:$PYTHONPATH}"
echo "{}" > /root/state.json
