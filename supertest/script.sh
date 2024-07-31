#!/bin/bash
../llama-server -m ./Meta-Llama-3.1-8B-Instruct-Q8_0.gguf -c 8192 -t 4 --n-gpu-layers 20000 --port 8000 --host 127.0.0.1 --parallel 2 -cb &

sleep 5

cd trivia
uvicorn app:app --port 7860 --host 0.0.0.0