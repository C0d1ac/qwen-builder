FROM alpine:latest
RUN apk add --no-cache wget ca-certificates
WORKDIR /conf


RUN for f in config.json tokenizer.json tokenizer_config.json generation_config.json special_tokens_map.json vocab.json video_preprocessor_config.json preprocessor_config.json model.safetensors.index.json; do wget -c "https://huggingface.co/Qwen/Qwen3.8-Flash-Next/resolve/main/$f"; done

