#!/bin/bash
if [ -z "$EDITOR_TEMPLATE" ]; then
  echo "EDITOR_TEMPLATE not set" >&2
  exit 1
fi
cp "$EDITOR_TEMPLATE" "$1"
