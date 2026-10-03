#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
python3 "$DIR/cli.py" export
read -p "Press Enter to exit..."
