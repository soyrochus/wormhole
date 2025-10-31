#!/bin/bash

# create-x-icons.sh
# Script to convert a 1024x1024 PNG icon to multi-resolution ICO and ICNS files.
# Assumes ImageMagick and icnsutils are installed.
#
# Ubuntu/Debian (apt) install:
#   sudo apt update
#   sudo apt install -y imagemagick icnsutils
#
# Tools used:
#   - identify/convert (from ImageMagick)
#   - png2icns (from icnsutils)
#
# Usage: ./create-x-icons.sh input-icon.png
# Outputs: input-icon.ico and input-icon.icns

set -e  # Exit on any error

if [ $# -ne 1 ]; then
    echo "Usage: $0 <input-icon.png>" >&2
    echo "Input PNG must be 1024x1024 resolution." >&2
    exit 1
fi

input_png="$1"
base_name="${input_png%.*}"  # Remove .png extension

# Check if input file exists
if [ ! -f "$input_png" ]; then
    echo "Error: Input file '$input_png' not found." >&2
    exit 1
fi

# Verify resolution (optional, but good practice)
resolution=$(identify -format "%wx%h" "$input_png" 2>/dev/null || echo "unknown")
if [ "$resolution" != "1024x1024" ]; then
    echo "Warning: Input resolution is $resolution, expected 1024x1024. Proceeding anyway." >&2
fi

echo "Generating resized PNGs from $input_png..."

# Common sizes
sizes=(16 32 48 64 128 256 512 1024)

# Generate resized PNGs with high quality
for size in "${sizes[@]}"; do
    if [ $size -eq 1024 ]; then
        ln -sf "$input_png" "${base_name}-${size}.png"  # Symlink original for 1024
    else
        convert "$input_png" -resize "${size}x${size}!" -quality 100 "${base_name}-${size}.png"
    fi
done

echo "Creating ICO file: ${base_name}.ico"

# ICO sizes: 16,32,48,64,128,256,1024 (common Windows sizes)
ico_sizes=(16 32 48 64 128 256 1024)
ico_files=()
for size in "${ico_sizes[@]}"; do
    ico_files+=("${base_name}-${size}.png")
done
convert "${ico_files[@]}" "${base_name}.ico"

echo "Creating ICNS file: ${base_name}.icns"

# ICNS sizes: 16,32,128,256,512,1024 (standard macOS sizes)
icns_sizes=(16 32 128 256 512 1024)
icns_files=()
for size in "${icns_sizes[@]}"; do
    icns_files+=("${base_name}-${size}.png")
done
png2icns "${base_name}.icns" "${icns_files[@]}"

# Clean up intermediate PNGs
rm -f "${base_name}-"*.png

echo "Done! Generated: ${base_name}.ico and ${base_name}.icns"

