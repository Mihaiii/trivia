#!/bin/bash
../llama-server -m ./shieldgemma-2b-q5_k_m-imat.gguf -c 8192 -t 4 --port 8000 --host 127.0.0.1 --parallel 2 -cb &
../llama-server -m ./gemma-2-2b-it-Q5_K_M.gguf -c 8192 -t 4 --port 7888 --host 127.0.0.1 --parallel 2 -cb &

sleep 5

cd trivia
uvicorn app:app --port 7860 --host 0.0.0.0