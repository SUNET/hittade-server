#!/bin/bash

INPUT_DIR="static/sass";
OUTPUT_DIR="static/css";

case $1 in 
  dev) sass $INPUT_DIR:$OUTPUT_DIR --watch;;
  build) sass $INPUT_DIR:$OUTPUT_DIR && echo "Successully built styles to $OUTPUT_DIR";;
esac
