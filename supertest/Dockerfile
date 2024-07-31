FROM ghcr.io/ggerganov/llama.cpp:server-cuda-7c27a19b2eb91bb0f43c7f7aec0386cec2dddc33

ENTRYPOINT ["/bin/sh", "-c"]

RUN apt-get update && apt-get install -y wget pip python3 git 

WORKDIR llama.cpp

RUN wget -q https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q8_0.gguf

COPY script.sh .

RUN chmod +x ./script.sh
RUN chmod 777 .

EXPOSE 8000

RUN git clone --branch main                     https://github.com/Mihaiii/trivia.git
RUN cd trivia && pip install -r requirements.txt
RUN chmod 777 ./trivia

CMD ["./script.sh"]