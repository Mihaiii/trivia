FROM ghcr.io/ggerganov/llama.cpp:server--b1-e09a800

RUN apt-get update && apt-get install -y wget pip python3 git 

ENTRYPOINT ["/bin/sh", "-c"]

WORKDIR llama.cpp

RUN wget -q https://huggingface.co/Mihaiii/shieldgemma-2b-Q5_K_M-GGUF/resolve/main/shieldgemma-2b-q5_k_m-imat.gguf
RUN wget -q https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q5_K_M.gguf

COPY script.sh .

RUN chmod +x ./script.sh
RUN chmod 777 .

RUN git clone https://github.com/Mihaiii/trivia.git
RUN cd trivia && pip install -r requirements.txt
RUN chmod 777 ./trivia

CMD ["./script.sh"]
